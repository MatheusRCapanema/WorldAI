"""Ações dos reinos: validação, cota e ciclo de vida (seção 7).

Cada tipo de ação registra:
- `validar(m, reino, p) -> Plano`: lê o estado e lança `Rejeicao` se a ação
  não pode ser aceita. Não escreve no estado.
- `aplicar(estado, ev)`: redutor chamado dentro de `acao_aceita`.
- `concluir(m, acao)`: opcional, roda quando a duração termina.

O evento `acao_aceita` guarda custos, cota e os dados que o redutor precisa.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .economia import alocacao_efetiva, capacidade, leis_ativas, nivel_ativo, provincias_do_reino, r3
from .motor import Rejeicao, tratador_agenda
from .nucleo import usar_id
from .redutor import agendar, informativo, redutor
from .regras import (
    CONSTRUCOES,
    LEIS,
    MAX_LEIS,
    MAX_NIVEL,
    RECURSOS,
    SETORES,
)


@dataclass
class Plano:
    custos: dict = field(default_factory=dict)
    duracao: int | None = None  # ms; None = instantânea
    dados: dict = field(default_factory=dict)  # vai para acao_aceita.dados.extra
    depois: Callable | None = None  # fn(m, ev_aceita): emite consequências imediatas


@dataclass
class TipoAcao:
    cota: str  # "ordens" ou "mensagens"
    custo_cota: Callable[[dict], int]
    validar: Callable
    aplicar: Callable | None = None
    concluir: Callable | None = None
    cancelavel: bool = False
    desfazer: Callable | None = None  # redutor do cancelamento


ACOES: dict[str, TipoAcao] = {}

DESLIGADAS = {
    "colonizar", "explorar_ruina", "pesquisar", "contratar_mercenarios", "enviar_emissario",
    "cancelar_oferta", "definir_pedagio", "mudar_capital",
}


def acao(tipo: str, cota: str = "ordens", custo: int | Callable = 1, cancelavel: bool = False):
    def registrar(validar):
        ACOES[tipo] = TipoAcao(
            cota=cota,
            custo_cota=custo if callable(custo) else (lambda p, n=custo: n),
            validar=validar,
            cancelavel=cancelavel,
        )
        return validar

    return registrar


def ao_aplicar(tipo: str):
    def registrar(fn):
        ACOES[tipo].aplicar = fn
        return fn

    return registrar


def ao_concluir(tipo: str):
    def registrar(fn):
        ACOES[tipo].concluir = fn
        return fn

    return registrar


def ao_cancelar(tipo: str):
    def registrar(fn):
        ACOES[tipo].desfazer = fn
        return fn

    return registrar


# ---------------------------------------------------------------- execução


def executar_acao(m, reino: str, acao_req: dict) -> dict:
    if not isinstance(acao_req, dict) or not isinstance(acao_req.get("tipo"), str):
        raise Rejeicao("formato_invalido", "A ação precisa de um campo 'tipo'")
    tipo = acao_req["tipo"]
    params = acao_req.get("parametros") or {}
    if not isinstance(params, dict):
        raise Rejeicao("formato_invalido", "'parametros' precisa ser um objeto")
    comentario = acao_req.get("comentario")
    if comentario is not None and (not isinstance(comentario, str) or len(comentario) > 500):
        raise Rejeicao("formato_invalido", "'comentario' tem no máximo 500 caracteres")
    if tipo in DESLIGADAS or tipo not in ACOES:
        raise Rejeicao("acao_desconhecida", f"A ação '{tipo}' não existe ou está desligada nesta era")
    ta = ACOES[tipo]
    r = m.estado["reinos"][reino]
    try:
        n_cota = int(ta.custo_cota(params))
    except (TypeError, ValueError):
        raise Rejeicao("formato_invalido", "parâmetros inválidos")
    if r["cota"][ta.cota] < n_cota:
        raise Rejeicao("cota_esgotada", f"Sem {ta.cota} suficientes hoje", {"necessario": n_cota, "disponivel": r["cota"][ta.cota]})
    try:
        plano: Plano = ta.validar(m, reino, params)
    except (KeyError, TypeError, ValueError) as e:
        raise Rejeicao("formato_invalido", f"parâmetros inválidos: {e}")
    faltas = {}
    for res, q in plano.custos.items():
        disp = r["estoque"].get(res, 0)
        if disp + 1e-9 < q:
            faltas[res] = {"necessario": q, "disponivel": r3(disp)}
    if faltas:
        texto = ", ".join(f"{r3(v['necessario'] - v['disponivel'])} {k}" for k, v in faltas.items())
        raise Rejeicao("recursos_insuficientes", f"Faltam {texto}", faltas)

    acao_id = m.novo_id("acao", "acao")
    conclusao = m.agora + plano.duracao if plano.duracao else None
    cota_restante = dict(r["cota"])
    cota_restante[ta.cota] -= n_cota
    resposta = {
        "acao_id": acao_id,
        "status": "aceita",
        "aceita_em": m.iso(m.agora),
        "conclusao_prevista": m.iso(conclusao) if conclusao else None,
        "custos": {k: r3(v) for k, v in plano.custos.items()},
        "cota_restante": cota_restante,
        "seq": m.armazem.ultimo_seq_reino(reino) + 1,
    }
    ev = m.emitir(
        "acao_aceita",
        {
            "acao_id": acao_id,
            "reino": reino,
            "tipo": tipo,
            "parametros": params,
            "custos": {k: r3(v) for k, v in plano.custos.items()},
            "cota": {ta.cota: n_cota},
            "conclusao_em": conclusao,
            "chave_idempotencia": acao_req.get("chave_idempotencia"),
            "comentario": comentario,
            "extra": plano.dados,
            "resposta": resposta,
        },
        [reino],
    )
    if plano.depois:
        plano.depois(m, ev)
    return resposta


@redutor("acao_aceita")
def _acao_aceita(estado, ev):
    d = ev["dados"]
    usar_id(estado, "acao", d["acao_id"])
    r = estado["reinos"][d["reino"]]
    for k, n in d["cota"].items():
        r["cota"][k] -= n
    for res, q in d["custos"].items():
        r["estoque"][res] = r3(r["estoque"][res] - q)
    estado["acoes"][d["acao_id"]] = {
        "id": d["acao_id"],
        "reino": d["reino"],
        "tipo": d["tipo"],
        "parametros": d["parametros"],
        "custos": d["custos"],
        "extra": d["extra"],
        "status": "em_andamento" if d["conclusao_em"] else "concluida",
        "aceita_em": ev["ocorrido_em"],
        "conclusao_em": d["conclusao_em"],
        "agenda": None,
        "resposta": d["resposta"],
    }
    if d["chave_idempotencia"]:
        estado["idempotencia"][f"{d['reino']}|{d['chave_idempotencia']}"] = {"acao": d["acao_id"], "em": ev["ocorrido_em"]}
    ta = ACOES[d["tipo"]]
    if ta.aplicar:
        ta.aplicar(estado, ev)
    if d["conclusao_em"] and ta.concluir:
        estado["acoes"][d["acao_id"]]["agenda"] = agendar(estado, ev, d["conclusao_em"], "concluir_acao", {"acao": d["acao_id"]})


@tratador_agenda("concluir_acao")
def _concluir(m, item):
    acao_ = m.estado["acoes"].get(item["dados"]["acao"])
    if acao_ is None or acao_["status"] != "em_andamento":
        return
    ACOES[acao_["tipo"]].concluir(m, acao_)


def concluir_ok(m, acao_: dict, tipo_evento: str, dados: dict, visivel: list[str] | None = None):
    """Emite o evento de resultado e marca a ação como concluída."""
    dados = dict(dados)
    dados["acao_id"] = acao_["id"]
    m.emitir(tipo_evento, dados, visivel or [acao_["reino"]], causa=acao_["id"])
    m.emitir("acao_concluida", {"acao_id": acao_["id"], "tipo": acao_["tipo"]}, [acao_["reino"]], causa=acao_["id"])


def falhar(m, acao_: dict, motivo: str):
    m.emitir("acao_falhou", {"acao_id": acao_["id"], "tipo": acao_["tipo"], "motivo": motivo}, [acao_["reino"]], causa=acao_["id"])


@redutor("acao_concluida", "acao_falhou")
def _acao_fim(estado, ev):
    a = estado["acoes"][ev["dados"]["acao_id"]]
    a["status"] = "concluida" if ev["tipo"] == "acao_concluida" else "falhou"


# ---------------------------------------------------------------- validação comum


def provincia_propria(m, reino: str, pid) -> dict:
    p = m.estado["provincias"].get(pid)
    if p is None:
        raise Rejeicao("formato_invalido", f"província desconhecida: {pid}")
    if p["dono"] != reino:
        raise Rejeicao("sem_permissao", "A província não é do reino")
    return p


def exigir(cond: bool, mensagem: str, detalhes: dict | None = None, codigo: str = "precondicao_falhou"):
    if not cond:
        raise Rejeicao(codigo, mensagem, detalhes)


# ---------------------------------------------------------------- economia e governo


@acao("alocar_trabalho")
def _v_alocar(m, reino, p):
    prov = provincia_propria(m, reino, p["provincia"])
    setores = p["setores"]
    exigir(isinstance(setores, dict) and set(setores) <= set(SETORES) - {"ocioso"}, "setores inválidos", codigo="formato_invalido")
    valores = {s: int(setores.get(s, 0)) for s in SETORES if s != "ocioso"}
    exigir(all(v >= 0 for v in valores.values()) and sum(valores.values()) <= 100, "a soma dos setores passa de 100%", codigo="formato_invalido")
    valores["ocioso"] = 100 - sum(valores.values())
    origem = {s: round(v, 4) for s, v in alocacao_efetiva(prov, m.agora, m.params).items()}
    return Plano(duracao=None, dados={"origem": origem, "alvo": valores})


@ao_aplicar("alocar_trabalho")
def _a_alocar(estado, ev):
    d = ev["dados"]
    prov = estado["provincias"][d["parametros"]["provincia"]]
    prov["alocacao_origem"] = d["extra"]["origem"]
    prov["alocacao_alvo"] = d["extra"]["alvo"]
    prov["alocacao_desde"] = ev["ocorrido_em"]


@acao("definir_impostos")
def _v_impostos(m, reino, p):
    aliq = int(p["aliquota"])
    exigir(0 <= aliq <= 50, "alíquota fora de 0 a 50", codigo="formato_invalido")
    r = m.estado["reinos"][reino]
    ultima = r["aliquota_mudou_em"]
    exigir(ultima is None or m.agora - ultima >= m.params.duracao(24), "só 1 mudança de alíquota a cada 24 h")
    return Plano(dados={"aliquota": aliq})


@ao_aplicar("definir_impostos")
def _a_impostos(estado, ev):
    r = estado["reinos"][ev["dados"]["reino"]]
    r["aliquota"] = ev["dados"]["extra"]["aliquota"]
    r["aliquota_mudou_em"] = ev["ocorrido_em"]


@acao("promulgar_lei", cancelavel=True)
def _v_lei(m, reino, p):
    lei = p["lei"]
    exigir(lei in LEIS, f"lei desconhecida: {lei}", codigo="formato_invalido")
    r = m.estado["reinos"][reino]
    exigir(lei not in r["leis"], "lei já ativa ou em promulgação")
    exigir(len(r["leis"]) < MAX_LEIS, "máximo de 3 leis", codigo="limite_atingido")
    espera = r["leis_espera"].get(lei)
    exigir(espera is None or espera <= m.agora, "lei revogada há pouco, em espera")
    return Plano(custos={"ouro": LEIS[lei]["custo"]} if LEIS[lei]["custo"] else {}, duracao=m.params.duracao(24))


@ao_aplicar("promulgar_lei")
def _a_lei(estado, ev):
    d = ev["dados"]
    estado["reinos"][d["reino"]]["leis"][d["parametros"]["lei"]] = {"vale_em": d["conclusao_em"], "acao": d["acao_id"]}


@ao_concluir("promulgar_lei")
def _c_lei(m, a):
    concluir_ok(m, a, "lei_em_vigor", {"lei": a["parametros"]["lei"]}, ["publico"])


@ao_cancelar("promulgar_lei")
def _x_lei(estado, a):
    estado["reinos"][a["reino"]]["leis"].pop(a["parametros"]["lei"], None)


informativo("lei_em_vigor")


@acao("revogar_lei")
def _v_revogar(m, reino, p):
    r = m.estado["reinos"][reino]
    lei = p["lei"]
    exigir(lei in r["leis"] and r["leis"][lei]["vale_em"] <= m.agora, "lei não está ativa")
    return Plano(dados={"espera_ate": m.agora + m.params.dias_jogo(7)})


@ao_aplicar("revogar_lei")
def _a_revogar(estado, ev):
    d = ev["dados"]
    r = estado["reinos"][d["reino"]]
    r["leis"].pop(d["parametros"]["lei"], None)
    r["leis_espera"][d["parametros"]["lei"]] = d["extra"]["espera_ate"]


def _duracao_obra(m, prov, horas):
    """Seção 6: −10% por 10 pontos de ofícios acima de 15%, até −40%."""
    of = alocacao_efetiva(prov, m.agora, m.params)["oficios"]
    reducao = min(0.4, max(0.0, (of - 15) // 10 * 0.10))
    return m.params.duracao(horas * (1 - reducao))


@acao("construir", cancelavel=True)
def _v_construir(m, reino, p):
    prov = provincia_propria(m, reino, p["provincia"])
    tipo = p["construcao"]
    exigir(tipo in CONSTRUCOES, f"construção desconhecida: {tipo}", codigo="formato_invalido")
    c = CONSTRUCOES[tipo]
    if c.desligada:
        raise Rejeicao("acao_desconhecida", f"'{tipo}' está desligada nesta era")
    exigir(prov["ocupante"] is None, "província ocupada")
    exigir(len(prov["construcoes"]) < prov["slots"], "sem slot livre", {"slots": prov["slots"]})
    exigir(not c.exige_jazida or bool(prov["jazidas"]), "exige jazida")
    exigir(not c.exige_costa or prov["costeira"], "exige costa")
    if tipo == "muralha":
        exigir(nivel_ativo(prov, "muralha") == 0 and not any(x["tipo"] == "muralha" for x in prov["construcoes"].values()), "já há muralha")
    cid = m.novo_id("con", "con")
    return Plano(custos=dict(c.custo), duracao=_duracao_obra(m, prov, c.duracao_h), dados={"construcao_id": cid})


@ao_aplicar("construir")
def _a_construir(estado, ev):
    d = ev["dados"]
    cid = d["extra"]["construcao_id"]
    usar_id(estado, "con", cid)
    estado["provincias"][d["parametros"]["provincia"]]["construcoes"][cid] = {
        "id": cid, "tipo": d["parametros"]["construcao"], "nivel": 0, "ativa": True, "obra_ate": d["conclusao_em"],
    }


@ao_concluir("construir")
def _c_obra(m, a):
    pid = a["parametros"]["provincia"]
    cid = a["extra"]["construcao_id"]
    prov = m.estado["provincias"][pid]
    if cid not in prov["construcoes"]:
        return falhar(m, a, "construção não existe mais")
    if prov["dono"] != a["reino"]:
        return falhar(m, a, "a província mudou de dono")
    c = prov["construcoes"][cid]
    concluir_ok(m, a, "construcao_concluida", {"provincia": pid, "construcao": cid, "tipo": c["tipo"], "nivel": c["nivel"] + 1})


@redutor("construcao_concluida")
def _construcao_concluida(estado, ev):
    d = ev["dados"]
    prov = estado["provincias"][d["provincia"]]
    c = prov["construcoes"][d["construcao"]]
    c["nivel"] = d["nivel"]
    c["obra_ate"] = None
    if c["tipo"] == "muralha":
        prov["muralha_integridade"] = 100.0 * c["nivel"]


@ao_cancelar("construir")
def _x_construir(estado, a):
    estado["provincias"][a["parametros"]["provincia"]]["construcoes"].pop(a["extra"]["construcao_id"], None)


@acao("melhorar", cancelavel=True)
def _v_melhorar(m, reino, p):
    prov = provincia_propria(m, reino, p["provincia"])
    cid = p["construcao"]
    exigir(cid in prov["construcoes"], "construção não existe", codigo="formato_invalido")
    c = prov["construcoes"][cid]
    exigir(c["obra_ate"] is None, "construção em obra")
    exigir(prov["ocupante"] is None, "província ocupada")
    muralha_caida = c["tipo"] == "muralha" and prov["muralha_integridade"] <= 0
    alvo = 1 if muralha_caida else c["nivel"] + 1
    exigir(alvo <= MAX_NIVEL, "nível máximo")
    base = CONSTRUCOES[c["tipo"]]
    custos = {k: v * alvo for k, v in base.custo.items()}
    return Plano(custos=custos, duracao=_duracao_obra(m, prov, base.duracao_h * alvo),
                 dados={"construcao_id": cid, "nivel_anterior": c["nivel"], "nivel_novo": alvo})


ao_concluir("melhorar")(_c_obra)


@ao_aplicar("melhorar")
def _a_melhorar(estado, ev):
    d = ev["dados"]
    c = estado["provincias"][d["parametros"]["provincia"]]["construcoes"][d["extra"]["construcao_id"]]
    c["obra_ate"] = d["conclusao_em"]
    c["nivel"] = d["extra"]["nivel_novo"] - 1


@ao_cancelar("melhorar")
def _x_melhorar(estado, a):
    c = estado["provincias"][a["parametros"]["provincia"]]["construcoes"].get(a["extra"]["construcao_id"])
    if c:
        c["obra_ate"] = None
        c["nivel"] = a["extra"]["nivel_anterior"]


@acao("demolir")
def _v_demolir(m, reino, p):
    prov = provincia_propria(m, reino, p["provincia"])
    exigir(p["construcao"] in prov["construcoes"], "construção não existe", codigo="formato_invalido")
    exigir(prov["construcoes"][p["construcao"]]["obra_ate"] is None, "construção em obra: use cancelar_acao")
    return Plano()


@ao_aplicar("demolir")
def _a_demolir(estado, ev):
    d = ev["dados"]
    prov = estado["provincias"][d["parametros"]["provincia"]]
    c = prov["construcoes"].pop(d["parametros"]["construcao"])
    if c["tipo"] == "muralha":
        prov["muralha_integridade"] = 0.0


@acao("cancelar_acao")
def _v_cancelar(m, reino, p):
    a = m.estado["acoes"].get(p["acao"])
    exigir(a is not None and a["reino"] == reino, "ação não encontrada", codigo="sem_permissao")
    exigir(a["status"] == "em_andamento", "ação não está em andamento")
    exigir(ACOES[a["tipo"]].cancelavel, f"'{a['tipo']}' não pode ser cancelada no protótipo")
    devolve = {k: r3(v / 2) for k, v in a["custos"].items()}
    return Plano(dados={"devolve": devolve})


@ao_aplicar("cancelar_acao")
def _a_cancelar(estado, ev):
    d = ev["dados"]
    a = estado["acoes"][d["parametros"]["acao"]]
    a["status"] = "cancelada"
    if a["agenda"]:
        estado["agenda"].pop(a["agenda"], None)
    r = estado["reinos"][d["reino"]]
    for res, q in d["extra"]["devolve"].items():
        r["estoque"][res] = r3(r["estoque"][res] + q)
    ta = ACOES[a["tipo"]]
    if ta.desfazer:
        ta.desfazer(estado, a)


# ---------------------------------------------------------------- presente (transferência direta)


@acao("presentear")
def _v_presentear(m, reino, p):
    para = p["para"]
    exigir(para in m.estado["reinos"] and para != reino, "destino inválido", codigo="formato_invalido")
    recursos = {k: float(v) for k, v in p["recursos"].items()}
    exigir(all(k in RECURSOS and v > 0 for k, v in recursos.items()) and recursos, "recursos inválidos", codigo="formato_invalido")
    # Simplificação: transferência imediata com a taxa de transporte de 10% (seção 8.1)
    recebe = {k: r3(v * 0.9) for k, v in recursos.items()}
    cap = capacidade(m.estado, para, m.params)

    def depois(m, ev):
        m.emitir("presente_recebido", {"de": reino, "recursos": recebe, "capacidade": cap}, [reino, para], causa=ev["dados"]["acao_id"])

    return Plano(custos=recursos, depois=depois)


@redutor("presente_recebido")
def _presente(estado, ev):
    d = ev["dados"]
    para = [r for r in ev["visivel_para"] if r != d["de"]][0]
    est = estado["reinos"][para]["estoque"]
    for k, v in d["recursos"].items():
        est[k] = r3(est[k] + v if k == "ouro" else min(d["capacidade"], est[k] + v))


# ---------------------------------------------------------------- leitura para outros módulos


def leis_do_reino(estado, reino, t):
    return leis_ativas(estado["reinos"][reino], t)


def provincias(estado, reino):
    return provincias_do_reino(estado, reino)
