"""API mínima (seção 17.2) sobre FastAPI.

Variáveis de ambiente:
- ARENA_RELOGIO: `real` (padrão, relógio de parede UTC), `acelerado` (o mundo
  anda ARENA_VELOCIDADE vezes mais rápido) ou `manual` (só anda por /admin/avancar).
- ARENA_VELOCIDADE: horas de mundo por hora real no modo acelerado (padrão 360,
  ou seja, 1 dia de mundo a cada 4 minutos).
- ARENA_SEMENTE, ARENA_INICIO (ISO, meia-noite UTC; padrão: hoje).
- ARENA_BOTS: reinos governados pelos bots, separados por vírgula, ou `todos`.
- ARENA_TOKENS: `reino_a:tokenA,reino_b:tokenB,...`. Sem isso, o token de
  desenvolvimento de cada reino é `dev-<reino>`.
- ARENA_ADMIN_TOKEN: token das rotas /admin (padrão `dev-admin`).
- DATABASE_URL: se definido, o log vai para o PostgreSQL; senão fica em memória.

Ao subir com um log existente, o motor refaz o estado a partir dele.
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from .armazenamento import MemoriaEventos
from .bots import criar_bots
from .motor import Motor, hash_estado
from .regras import (
    BIOMAS, CLAUSULAS_SUPORTADAS, CONSTRUCOES, LEIS, UNIDADES, VERSAO_REGRAS, Parametros,
)
from .tempo import DIA, HORA, agora_real, de_iso, inicio_do_dia, iso
from .visao import estado_do_reino, mundo_publico


class Relogio:
    def __init__(self, modo: str, base_mundo: int, velocidade: float = 360.0):
        self.modo = modo
        self.velocidade = velocidade
        self.base_mundo = base_mundo
        self.base_real = agora_real()
        self.manual = base_mundo

    def agora(self) -> int:
        if self.modo == "real":
            return agora_real()
        if self.modo == "acelerado":
            return self.base_mundo + int((agora_real() - self.base_real) * self.velocidade)
        return self.manual


class Servidor:
    """Motor + relógio + bots, com um trava para acesso concorrente."""

    def __init__(self, motor: Motor, relogio: Relogio, tokens: dict[str, str], admin_token: str, bots: list[str]):
        self.motor = motor
        self.relogio = relogio
        self.tokens = tokens  # token -> reino
        self.admin_token = admin_token
        self.trava = threading.RLock()
        todos = criar_bots(motor.estado)
        self.bots = {r: todos[r] for r in bots}
        self.ultimo_bot = motor.agora
        self.acks: dict[str, int] = {}
        self.taxa: dict[str, deque] = defaultdict(deque)

    def sincronizar(self) -> None:
        """Avança o motor até o relógio, rodando os bots a cada 3 horas de mundo."""
        with self.trava:
            alvo = self.relogio.agora()
            if self.bots:
                proximo = (self.ultimo_bot // (3 * HORA) + 1) * 3 * HORA
                while proximo <= alvo and not self.motor.estado["encerrada"]:
                    self.motor.avancar_ate(proximo)
                    for rid, bot in self.bots.items():
                        for a in bot.decidir(estado_do_reino(self.motor, rid), proximo, self.motor.params.fator):
                            self.motor.submeter(rid, a, origem="bot")
                    self.ultimo_bot = proximo
                    proximo += 3 * HORA
            if alvo > self.motor.agora:
                self.motor.avancar_ate(alvo)

    def limitar(self, reino: str) -> None:
        """10 requisições por segundo por reino (seção 7.1)."""
        agora = time.monotonic()
        fila = self.taxa[reino]
        while fila and agora - fila[0] > 1.0:
            fila.popleft()
        if len(fila) >= 10:
            raise HTTPException(429, {"status": "rejeitada", "erro": {"codigo": "taxa_excedida", "mensagem": "Mais de 10 requisições por segundo"}})
        fila.append(agora)


def _tokens_do_ambiente(reinos: list[str]) -> dict[str, str]:
    texto = os.environ.get("ARENA_TOKENS")
    if texto:
        pares = [p.split(":", 1) for p in texto.split(",") if p.strip()]
        return {tok.strip(): reino.strip() for reino, tok in pares}
    return {f"dev-{r}": r for r in reinos}


def criar_servidor_do_ambiente() -> Servidor:
    dsn = os.environ.get("DATABASE_URL")
    if dsn:
        from .armazenamento import PostgresEventos

        armazem = PostgresEventos(dsn)
    else:
        armazem = MemoriaEventos()
    modo = os.environ.get("ARENA_RELOGIO", "real")
    if armazem.ultimo_seq() > 0:
        motor = Motor.do_log(armazem)
    else:
        inicio_txt = os.environ.get("ARENA_INICIO")
        inicio = de_iso(inicio_txt) if inicio_txt else inicio_do_dia(agora_real())
        motor = Motor.nova_era(int(os.environ.get("ARENA_SEMENTE", "42")), inicio, Parametros(), armazem)
    base = motor.agora if modo != "real" else agora_real()
    relogio = Relogio(modo, base, float(os.environ.get("ARENA_VELOCIDADE", "360")))
    bots_txt = os.environ.get("ARENA_BOTS", "")
    reinos = sorted(motor.estado["reinos"])
    bots = reinos if bots_txt == "todos" else [b for b in bots_txt.split(",") if b in reinos]
    return Servidor(motor, relogio, _tokens_do_ambiente(reinos), os.environ.get("ARENA_ADMIN_TOKEN", "dev-admin"), bots)


def criar_app(servidor: Servidor | None = None, sincronizar_em_fundo: bool = True) -> FastAPI:
    estado_app: dict = {"srv": servidor}

    @asynccontextmanager
    async def ciclo(app: FastAPI):
        if estado_app["srv"] is None:
            estado_app["srv"] = criar_servidor_do_ambiente()
        tarefa = None
        if sincronizar_em_fundo and estado_app["srv"].relogio.modo != "manual":
            async def laco():
                while True:
                    await asyncio.to_thread(estado_app["srv"].sincronizar)
                    await asyncio.sleep(1.0)

            tarefa = asyncio.create_task(laco())
        yield
        if tarefa:
            tarefa.cancel()

    app = FastAPI(title="Arena de Reinos: motor do mundo", version=VERSAO_REGRAS, lifespan=ciclo)

    def srv() -> Servidor:
        s = estado_app["srv"]
        if s is None:
            raise HTTPException(503, "servidor iniciando")
        return s

    def reino_autenticado(authorization: str = Header(default="")) -> str:
        s = srv()
        token = authorization.removeprefix("Bearer ").strip()
        reino = s.tokens.get(token)
        if not reino:
            raise HTTPException(401, "token inválido")
        s.limitar(reino)
        return reino

    def admin(authorization: str = Header(default="")) -> None:
        if authorization.removeprefix("Bearer ").strip() != srv().admin_token:
            raise HTTPException(401, "token de administração inválido")

    @app.get("/v1/estado")
    def get_estado(reino: str = Depends(reino_autenticado)):
        s = srv()
        s.sincronizar()
        with s.trava:
            return estado_do_reino(s.motor, reino)

    @app.get("/v1/eventos")
    def get_eventos(desde: int = Query(0, ge=0), limite: int = Query(500, ge=1, le=500), reino: str = Depends(reino_autenticado)):
        s = srv()
        s.sincronizar()
        with s.trava:
            return {"eventos": s.motor.armazem.eventos_do_reino(reino, desde, limite), "ultimo_seq": s.motor.armazem.ultimo_seq_reino(reino)}

    @app.post("/v1/eventos/ack")
    def post_ack(corpo: dict, reino: str = Depends(reino_autenticado)):
        s = srv()
        seq = int(corpo.get("seq", 0))
        s.acks[reino] = max(s.acks.get(reino, 0), seq)
        return {"seq": s.acks[reino]}

    @app.post("/v1/acoes")
    def post_acoes(corpo: dict, reino: str = Depends(reino_autenticado)):
        s = srv()
        s.sincronizar()
        with s.trava:
            if "acoes" in corpo:
                lote = corpo["acoes"]
                if not isinstance(lote, list) or not 1 <= len(lote) <= 20:
                    return JSONResponse({"status": "rejeitada", "erro": {"codigo": "formato_invalido", "mensagem": "um lote tem de 1 a 20 ações"}}, 422)
                return {"resultados": [{"http": st, **res} for st, res in (s.motor.submeter(reino, a) for a in lote)]}
            status, res = s.motor.submeter(reino, corpo)
            return JSONResponse(res, status)

    @app.get("/v1/acoes/{acao_id}")
    def get_acao(acao_id: str, reino: str = Depends(reino_autenticado)):
        s = srv()
        with s.trava:
            a = s.motor.estado["acoes"].get(acao_id)
            if a is None or a["reino"] != reino:
                raise HTTPException(404, "ação não encontrada")
            return {k: a[k] for k in ("id", "tipo", "parametros", "status", "custos", "resposta")} | {
                "conclusao_prevista": iso(a["conclusao_em"]) if a["conclusao_em"] else None
            }

    @app.get("/v1/cota")
    def get_cota(reino: str = Depends(reino_autenticado)):
        s = srv()
        s.sincronizar()
        with s.trava:
            cota = s.motor.estado["reinos"][reino]["cota"]
            return dict(cota, renova_em=iso((s.motor.agora // DIA + 1) * DIA))

    @app.get("/v1/mundo")
    def get_mundo():
        s = srv()
        s.sincronizar()
        with s.trava:
            return mundo_publico(s.motor)

    @app.get("/v1/regras")
    def get_regras():
        s = srv()
        return {
            "versao": VERSAO_REGRAS,
            "parametros": s.motor.params.como_dict(),
            "biomas": BIOMAS,
            "construcoes": {k: {"custo": v.custo, "duracao_h": v.duracao_h, "manutencao": v.manutencao, "desligada": v.desligada} for k, v in CONSTRUCOES.items()},
            "unidades": {k: {"ataque": u.ataque, "defesa": u.defesa, "custo": u.custo, "treino_h": u.treino_h, "soldo": u.soldo} for k, u in UNIDADES.items()},
            "leis": LEIS,
            "clausulas": list(CLAUSULAS_SUPORTADAS),
        }

    @app.post("/admin/avancar", dependencies=[Depends(admin)])
    def admin_avancar(horas: float = Query(1, gt=0, le=24 * 120)):
        s = srv()
        if s.relogio.modo == "real":
            raise HTTPException(409, "no relógio real o mundo não pode ser adiantado")
        with s.trava:
            if s.relogio.modo == "manual":
                s.relogio.manual = s.relogio.agora() + int(horas * HORA)
            else:
                s.relogio.base_mundo += int(horas * HORA)
        s.sincronizar()
        return {"agora": iso(s.motor.agora), "dia": s.motor.estado["dia"], "eventos": s.motor.armazem.ultimo_seq()}

    @app.get("/admin/verificar", dependencies=[Depends(admin)])
    def admin_verificar():
        """Refaz o estado do zero pelo log e compara com o estado ao vivo."""
        s = srv()
        with s.trava:
            vivo = hash_estado(s.motor.estado)
            refeito = hash_estado(Motor.do_log(s.motor.armazem).estado)
        return {"identico": vivo == refeito, "hash": vivo, "eventos": s.motor.armazem.ultimo_seq()}

    @app.exception_handler(HTTPException)
    async def erro_http(request: Request, exc: HTTPException):
        corpo = exc.detail if isinstance(exc.detail, dict) else {"detail": exc.detail}
        return JSONResponse(corpo, exc.status_code)

    return app


app = criar_app()
