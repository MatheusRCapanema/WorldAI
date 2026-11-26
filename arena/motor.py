"""Núcleo do motor: relógio, emissão de eventos, agenda e envio de ações.

Ordem dentro de um instante (seção 18.2):
  1. virada do dia   2. tick econômico   3. eventos agendados
  4. rodadas de combate   5. ações dos reinos   6. eventos de mundo (desligado)

As ações (5) entram por `submeter`, que primeiro avança o relógio até o
instante da ação. Assim tudo o que vence naquele instante roda antes dela.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Callable

from . import redutor as R
from .armazenamento import ArmazemEventos, MemoriaEventos
from .regras import VERSAO_REGRAS, Parametros
from .tempo import DIA, HORA, iso, proxima_hora

# Registro de tratadores da agenda: tipo -> fn(motor, item)
AGENDA: dict[str, Callable] = {}


def tratador_agenda(tipo: str):
    def registrar(fn):
        AGENDA[tipo] = fn
        return fn

    return registrar


class Rejeicao(Exception):
    """Ação rejeitada na validação (seção 17.3). Não gasta cota."""

    def __init__(self, codigo: str, mensagem: str, detalhes: dict | None = None):
        super().__init__(mensagem)
        self.codigo = codigo
        self.mensagem = mensagem
        self.detalhes = detalhes or {}


PUBLICO = "publico"


class Motor:
    def __init__(self, armazem: ArmazemEventos | None = None):
        self.armazem: ArmazemEventos = armazem or MemoriaEventos()
        self.estado: dict = {}
        self.params = Parametros()
        self._agenda_atual: str | None = None
        self._origem_atual: str = "motor"
        self._idem_rejeitadas: dict = {}
        self.ao_emitir: list[Callable[[dict], None]] = []
        # Relógio do motor. Fica fora do estado: o estado só guarda o instante do
        # último fato, e o relógio pode estar adiante dele.
        self.relogio: int = 0

    # ------------------------------------------------------------------ criação

    @classmethod
    def nova_era(cls, semente: int, inicio: int, params: Parametros | None = None, armazem: ArmazemEventos | None = None):
        from .mapa import criar_estado_inicial

        _carregar_modulos()
        m = cls(armazem)
        if m.armazem.ultimo_seq() > 0:
            raise RuntimeError("o armazém já tem eventos; use Motor.do_log")
        params = params or Parametros()
        m.params = params
        if inicio % DIA != 0:
            raise ValueError("a era começa à meia-noite UTC")
        inicial = criar_estado_inicial(semente, inicio, params)
        m.estado = {"agenda": {}, "contadores": {}}
        m.relogio = inicio
        m._emitir_em(inicio, "era_iniciada", {"semente": semente, "estado_inicial": inicial}, [PUBLICO])
        return m

    @classmethod
    def do_log(cls, armazem: ArmazemEventos):
        """Reconstrói o estado do zero refazendo o log (seção 18.1)."""
        _carregar_modulos()
        m = cls(armazem)
        m.estado = {"agenda": {}, "contadores": {}}
        for ev in armazem.todos():
            R.aplicar(m.estado, ev)
        if not m.estado.get("reinos"):
            raise RuntimeError("log vazio ou sem era_iniciada")
        m.params = Parametros.de_dict(m.estado["parametros"])
        m.relogio = m.estado["agora"]
        return m

    # ------------------------------------------------------------------ eventos

    @property
    def agora(self) -> int:
        return self.relogio

    def emitir(self, tipo: str, dados: dict, visivel_para: list[str], causa: str | None = None, origem: str | None = None) -> dict:
        return self._emitir_em(self.agora, tipo, dados, visivel_para, causa, origem)

    def _emitir_em(self, instante, tipo, dados, visivel_para, causa=None, origem=None) -> dict:
        seq = self.estado.get("seq_global", 0) + 1
        ev = {
            "seq_global": seq,
            "id": f"evt_{seq:08d}",
            "ocorrido_em": instante,
            "tipo": tipo,
            "origem": origem or self._origem_atual,
            "causa": causa,
            "dados": dados,
            "visivel_para": sorted({v for v in visivel_para if v}),
            "versao_regras": VERSAO_REGRAS,
        }
        if self._agenda_atual:
            ev["agenda_concluida"] = self._agenda_atual
            self._agenda_atual = None
        # Cópia normalizada em JSON: o log guarda exatamente o que um replay lerá.
        ev = json.loads(json.dumps(ev))
        R.aplicar(self.estado, ev)
        self.armazem.anexar(ev)
        for cb in self.ao_emitir:
            cb(ev)
        return ev

    # ------------------------------------------------------------------ relógio

    def avancar_ate(self, t: int) -> None:
        """Processa tudo o que acontece até o instante `t`, inclusive."""
        from . import economia, militar  # noqa: F401  (registram tratadores)

        while not self.estado["encerrada"]:
            prox_tick = proxima_hora(self.estado["ultimo_tick"])
            prox_agenda = min((a["instante"] for a in self.estado["agenda"].values()), default=None)
            prox = prox_tick if prox_agenda is None else min(prox_tick, max(prox_agenda, self.agora))
            if prox > t:
                break
            self.relogio = max(self.relogio, prox)
            self._processar_instante(prox)
        if t > self.relogio and not self.estado["encerrada"]:
            self.relogio = t

    def _processar_instante(self, instante: int) -> None:
        from .economia import tick_economico, virada_do_dia

        if instante == proxima_hora(self.estado["ultimo_tick"]):
            if instante >= self.estado["fim"]:
                from .ranking import encerrar_era

                encerrar_era(self)
                return
            if instante % DIA == 0:
                virada_do_dia(self)
            tick_economico(self)
        # Agenda: prioridade 3 (eventos) antes de 4 (combate); depois ordem de agendamento.
        while True:
            vencidos = [a for a in self.estado["agenda"].values() if a["instante"] <= instante]
            if not vencidos:
                break
            item = min(vencidos, key=lambda a: (a["prioridade"], a["instante"], a["ordem"]))
            self._executar_agenda(item)

    def _executar_agenda(self, item: dict) -> None:
        fn = AGENDA[item["tipo"]]
        self._agenda_atual = item["id"]
        try:
            fn(self, item)
        finally:
            if self._agenda_atual is not None:
                # nenhum evento foi emitido: registra o descarte para o replay
                self.emitir("agenda_descartada", {"item": item["id"], "tipo": item["tipo"]}, [])

    # ------------------------------------------------------------------ ações

    def submeter(self, reino: str, acao: dict, instante: int | None = None, origem: str | None = None) -> tuple[int, dict]:
        """Valida e aplica uma ação. Devolve (status_http, corpo) como na seção 17.3."""
        from .acoes import executar_acao

        if instante is not None:
            self.avancar_ate(instante)
        if reino not in self.estado["reinos"]:
            return 404, {"status": "rejeitada", "erro": {"codigo": "sem_permissao", "mensagem": "reino desconhecido"}}
        chave = acao.get("chave_idempotencia")
        if chave:
            ja = self.estado["idempotencia"].get(f"{reino}|{chave}")
            if ja and self.agora - ja["em"] <= DIA:
                return 202, self.estado["acoes"][ja["acao"]]["resposta"]
            rej = self._idem_rejeitadas.get(f"{reino}|{chave}")
            if rej and self.agora - rej[0] <= DIA:
                return 422, rej[1]
        self._origem_atual = origem or f"reino:{reino}"
        try:
            if self.estado["encerrada"]:
                raise Rejeicao("era_encerrada", "A era acabou")
            resposta = executar_acao(self, reino, acao)
            return 202, resposta
        except Rejeicao as r:
            corpo = {
                "status": "rejeitada",
                "erro": {"codigo": r.codigo, "mensagem": r.mensagem, "detalhes": r.detalhes},
                "cota_restante": dict(self.estado["reinos"][reino]["cota"]),
            }
            if chave:
                self._idem_rejeitadas[f"{reino}|{chave}"] = (self.agora, corpo)
            return 422, corpo
        finally:
            self._origem_atual = "motor"

    # ------------------------------------------------------------------ utilidades

    def novo_id(self, prefixo: str, chave: str, deslocamento: int = 0) -> str:
        """Próximo id de um tipo. O contador só muda no redutor (`usar_id`) do
        evento que cria o objeto; aqui só se calcula o valor."""
        n = self.estado["contadores"].get(chave, 0) + 1 + deslocamento
        return f"{prefixo}_{n:04d}"

    def hash_estado(self) -> str:
        return hash_estado(self.estado)

    def iso(self, ms: int) -> str:
        return iso(ms)


def hash_estado(estado: dict) -> str:
    limpo = copy.deepcopy(estado)
    limpo["contadores"].pop("_agenda_sub", None)
    texto = json.dumps(limpo, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(texto.encode()).hexdigest()


def _carregar_modulos() -> None:
    from . import acoes, comercio, diplomacia, economia, militar, nucleo, ranking  # noqa: F401


__all__ = ["Motor", "Rejeicao", "PUBLICO", "tratador_agenda", "HORA", "DIA"]
