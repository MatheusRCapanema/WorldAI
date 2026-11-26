"""Mensagens, tratados e reputação (seção 9)."""

from __future__ import annotations

from .acoes import Plano, acao, exigir
from .economia import capacidade, r3
from .motor import Rejeicao, tratador_agenda
from .nucleo import usar_id
from .redutor import agendar, informativo, redutor
from .regras import CLAUSULAS_SUPORTADAS, RECURSOS
from .relacoes import em_guerra, guerra_entre, tem_clausula, tratados_ativos

MAX_TRATADOS = 12
TAXA_TRANSPORTE = 0.10


# ---------------------------------------------------------------- mensagens


@acao("enviar_mensagem", cota="mensagens")
def _v_mensagem(m, reino, p):
    texto = p["texto"]
    exigir(isinstance(texto, str) and 0 < len(texto) <= 2000, "texto de 1 a 2.000 caracteres", codigo="formato_invalido")
    para = p["para"]
    if para == "publico":
        # Moderação automática fica para depois (seção 20.2, item 5): aqui tudo é publicado.
        return Plano(depois=lambda m, ev: m.emitir("mensagem_publica", {"de": reino, "texto": texto}, ["publico"], causa=ev["dados"]["acao_id"]))
    para = [para] if isinstance(para, str) else list(para)
    exigir(1 <= len(para) <= 3, "um canal privado tem até 4 reinos", codigo="formato_invalido")
    exigir(all(r in m.estado["reinos"] and r != reino for r in para), "destino inválido", codigo="formato_invalido")
    return Plano(depois=lambda m, ev: m.emitir("mensagem_recebida", {"de": reino, "para": sorted(para), "texto": texto},
                                               [reino] + para, causa=ev["dados"]["acao_id"]))


informativo("mensagem_recebida", "mensagem_publica", "tratado_aceito_parcial")


# ---------------------------------------------------------------- tratados


def _validar_recursos(rec) -> dict:
    exigir(isinstance(rec, dict) and rec, "recursos inválidos", codigo="formato_invalido")
    out = {}
    for k, v in rec.items():
        exigir(k in RECURSOS and float(v) > 0, f"recurso inválido: {k}", codigo="formato_invalido")
        out[k] = float(v)
    return out


def _validar_clausulas(m, partes, clausulas) -> list[dict]:
    exigir(isinstance(clausulas, list) and clausulas, "o tratado precisa de cláusulas", codigo="formato_invalido")
    out = []
    for c in clausulas:
        tipo = c.get("tipo")
        if tipo not in CLAUSULAS_SUPORTADAS:
            raise Rejeicao("formato_invalido", f"cláusula não suportada no protótipo: {tipo}")
        n = {"tipo": tipo}
        if tipo in ("pagamento_unico", "pagamento_periodico"):
            exigir(c["de"] in partes and c["para"] in partes and c["de"] != c["para"], "de/para precisam ser partes", codigo="formato_invalido")
            n.update(de=c["de"], para=c["para"], recursos=_validar_recursos(c["recursos"]))
            if tipo == "pagamento_periodico":
                n["a_cada_dias"] = int(c["a_cada_dias"])
                exigir(n["a_cada_dias"] >= 1, "a_cada_dias >= 1", codigo="formato_invalido")
                n["_ms"] = m.params.dias_jogo(n["a_cada_dias"])
        elif tipo == "troca_recorrente":
            exigir(len(partes) == 2, "troca_recorrente exige 2 partes", codigo="formato_invalido")
            n.update(a_cada_dias=int(c["a_cada_dias"]), de_a_para_b=_validar_recursos(c["de_a_para_b"]),
                     de_b_para_a=_validar_recursos(c["de_b_para_a"]))
            n["_ms"] = m.params.dias_jogo(n["a_cada_dias"])
        elif tipo == "tregua":
            n["dias"] = int(c["dias"])
            exigir(1 <= n["dias"] <= 120, "trégua de 1 a 120 dias", codigo="formato_invalido")
            n["_ms"] = m.params.dias_jogo(n["dias"])
        elif tipo == "fim_de_guerra":
            exigir(len(partes) == 2 and em_guerra(m.estado, partes[0], partes[1]), "fim_de_guerra exige guerra ativa entre as 2 partes")
        out.append(n)
    return out


def _plano_proposta(m, reino, partes, clausulas, duracao, preambulo):
    exigir(isinstance(partes, list) and 2 <= len(partes) <= 6 and len(set(partes)) == len(partes), "de 2 a 6 partes", codigo="formato_invalido")
    exigir(reino in partes and all(r in m.estado["reinos"] for r in partes), "partes inválidas", codigo="formato_invalido")
    if duracao == "fim_da_era":
        fim_ms = None
    else:
        duracao = int(duracao)
        exigir(1 <= duracao <= 120, "duração de 1 a 120 dias", codigo="formato_invalido")
        fim_ms = m.params.dias_jogo(duracao)
    cls = _validar_clausulas(m, partes, clausulas)
    for r in partes:
        if len(tratados_ativos(m.estado, r)) >= MAX_TRATADOS:
            raise Rejeicao("limite_atingido", f"{r} já tem 12 tratados ativos")
    exigir(preambulo is None or (isinstance(preambulo, str) and len(preambulo) <= 2000), "preâmbulo longo demais", codigo="formato_invalido")
    tid = m.novo_id("tra", "tra")

    def depois(m, ev):
        m.emitir(
            "tratado_proposto",
            {"tratado": tid, "proponente": reino, "partes": sorted(partes), "clausulas": cls, "duracao_dias": duracao,
             "duracao_ms": fim_ms, "preambulo": preambulo, "expira_em": m.agora + m.params.duracao(48)},
            partes, causa=ev["dados"]["acao_id"],
        )

    return Plano(dados={"tratado": tid}, depois=depois)


@acao("propor_tratado", custo=2)
def _v_propor(m, reino, p):
    return _plano_proposta(m, reino, list(p["partes"]), p["clausulas"], p.get("duracao_dias", 30), p.get("preambulo"))


@acao("propor_paz", custo=2)
def _v_paz(m, reino, p):
    alvo = p["alvo"]
    exigir(em_guerra(m.estado, reino, alvo), "não há guerra ativa com o destino")
    cls = [{"tipo": "fim_de_guerra"}] + list(p.get("clausulas_extras", []))
    return _plano_proposta(m, reino, [reino, alvo], cls, p.get("duracao_dias", 7), p.get("preambulo"))


@redutor("tratado_proposto")
def _proposto(estado, ev):
    d = ev["dados"]
    usar_id(estado, "tra", d["tratado"])
    estado["tratados"][d["tratado"]] = {
        "id": d["tratado"], "proponente": d["proponente"], "partes": d["partes"], "clausulas": d["clausulas"],
        "duracao_dias": d["duracao_dias"], "duracao_ms": d["duracao_ms"], "preambulo": d["preambulo"],
        "status": "proposto", "aceites": [d["proponente"]], "proposto_em": ev["ocorrido_em"], "expira_em": d["expira_em"],
        "ativado_em": None, "fim_em": None, "inadimplencias": {}, "pagamentos": 0,
    }
    agendar(estado, ev, d["expira_em"], "expirar_tratado", {"tratado": d["tratado"]})


@tratador_agenda("expirar_tratado")
def _expirar(m, item):
    t = m.estado["tratados"][item["dados"]["tratado"]]
    if t["status"] == "proposto":
        m.emitir("tratado_expirado", {"tratado": t["id"]}, t["partes"])


def _proposta_aberta(m, reino, tid) -> dict:
    t = m.estado["tratados"].get(tid)
    exigir(t is not None and reino in t["partes"], "proposta não encontrada", codigo="sem_permissao")
    exigir(t["status"] == "proposto", "a proposta não está aberta")
    exigir(reino not in t["aceites"], "o reino já aceitou")
    return t


@acao("aceitar_tratado")
def _v_aceitar(m, reino, p):
    t = _proposta_aberta(m, reino, p["tratado"])
    for r in t["partes"]:
        if len(tratados_ativos(m.estado, r)) >= MAX_TRATADOS:
            raise Rejeicao("limite_atingido", f"{r} já tem 12 tratados ativos")
    if any(c["tipo"] == "fim_de_guerra" for c in t["clausulas"]):
        exigir(em_guerra(m.estado, t["partes"][0], t["partes"][1]), "a guerra já acabou")

    def depois(m, ev):
        m.emitir("tratado_aceito_parcial", {"tratado": t["id"], "reino": reino}, t["partes"], causa=ev["dados"]["acao_id"])
        if set(t["aceites"]) | {reino} >= set(t["partes"]):
            ativar(m, t["id"], causa=ev["dados"]["acao_id"])

    return Plano(depois=depois)


@redutor("tratado_aceito_parcial")
def _aceito(estado, ev):
    t = estado["tratados"][ev["dados"]["tratado"]]
    if ev["dados"]["reino"] not in t["aceites"]:
        t["aceites"].append(ev["dados"]["reino"])


@acao("recusar_tratado", custo=0)
def _v_recusar(m, reino, p):
    t = _proposta_aberta(m, reino, p["tratado"])
    return Plano(depois=lambda m, ev: m.emitir("tratado_recusado", {"tratado": t["id"], "por": reino}, t["partes"], causa=ev["dados"]["acao_id"]))


@redutor("tratado_recusado", "tratado_expirado")
def _recusado(estado, ev):
    estado["tratados"][ev["dados"]["tratado"]]["status"] = "recusado" if ev["tipo"] == "tratado_recusado" else "expirado"


def ativar(m, tid, causa=None):
    t = m.estado["tratados"][tid]
    fim = m.agora + t["duracao_ms"] if t["duracao_ms"] else None
    vis = ["publico"]  # tratados ativos são públicos (seção 15), os valores ficam nos eventos privados
    m.emitir("tratado_ativado", {"tratado": tid, "partes": t["partes"], "clausulas": [c["tipo"] for c in t["clausulas"]], "fim_em": fim}, vis, causa=causa)
    for i, c in enumerate(t["clausulas"]):
        if c["tipo"] == "pagamento_unico":
            pagar(m, tid, i)
        elif c["tipo"] == "fim_de_guerra":
            from .militar import encerrar_guerra

            g = guerra_entre(m.estado, t["partes"][0], t["partes"][1], ("ativa",))
            if g:
                encerrar_guerra(m, g, "tratado", causa=tid)


@redutor("tratado_ativado")
def _ativado(estado, ev):
    d = ev["dados"]
    t = estado["tratados"][d["tratado"]]
    t["status"] = "ativo"
    t["ativado_em"] = ev["ocorrido_em"]
    t["fim_em"] = d["fim_em"]
    if d["fim_em"]:
        agendar(estado, ev, d["fim_em"], "fim_tratado", {"tratado": t["id"]})
    for i, c in enumerate(t["clausulas"]):
        if c["tipo"] in ("pagamento_periodico", "troca_recorrente"):
            agendar(estado, ev, ev["ocorrido_em"] + c["_ms"], "pagamento_tratado", {"tratado": t["id"], "clausula": i})


@tratador_agenda("pagamento_tratado")
def _pagamento(m, item):
    t = m.estado["tratados"][item["dados"]["tratado"]]
    if t["status"] != "ativo":
        return
    pagar(m, t["id"], item["dados"]["clausula"])


def _transferencia(m, de, para, recursos):
    est = m.estado["reinos"][de]["estoque"]
    pago = {k: r3(min(v, est[k])) for k, v in recursos.items()}
    falta = {k: r3(v - pago[k]) for k, v in recursos.items() if v - pago[k] > 1e-9}
    return pago, falta


def pagar(m, tid, i):
    t = m.estado["tratados"][tid]
    c = t["clausulas"][i]
    if c["tipo"] == "troca_recorrente":
        a, b = t["partes"][0], t["partes"][1]
        pa, fa = _transferencia(m, a, b, c["de_a_para_b"])
        pb, fb = _transferencia(m, b, a, c["de_b_para_a"])
        pernas = [(a, b, c["de_a_para_b"], fa), (b, a, c["de_b_para_a"], fb)]
        if fa or fb:  # amarrados: se um lado falha, ninguém paga
            for de, para, _, falta in pernas:
                if falta:
                    _inadimplente(m, t, i, de, falta)
                else:
                    m.emitir("tratado_pagamento", _dados_pag(m, t, i, de, para, {}), t["partes"])
        else:
            for de, para, rec, _ in pernas:
                m.emitir("tratado_pagamento", _dados_pag(m, t, i, de, para, rec), t["partes"])
    else:
        pago, falta = _transferencia(m, c["de"], c["para"], c["recursos"])
        m.emitir("tratado_pagamento", _dados_pag(m, t, i, c["de"], c["para"], pago), t["partes"])
        if falta:
            _inadimplente(m, t, i, c["de"], falta)
        elif t["inadimplencias"].get(c["de"]):
            m.emitir("tratado_em_dia", {"tratado": tid, "reino": c["de"]}, t["partes"])
    if c["tipo"] != "pagamento_unico":
        prox = m.agora + c["_ms"]
        if t["fim_em"] is None or prox <= t["fim_em"]:
            m.emitir("pagamento_agendado", {"tratado": tid, "clausula": i, "em": prox}, [])


def _dados_pag(m, t, i, de, para, pago):
    recebido = {k: r3(v * (1 - TAXA_TRANSPORTE)) for k, v in pago.items()}
    return {"tratado": t["id"], "clausula": i, "de": de, "para": para, "pago": pago, "recebido": recebido,
            "capacidade_para": capacidade(m.estado, para, m.params)}


def _inadimplente(m, t, i, devedor, falta):
    n = t["inadimplencias"].get(devedor, 0) + 1
    m.emitir("tratado_inadimplente", {"tratado": t["id"], "clausula": i, "reino": devedor, "falta": falta, "seguidas": n}, t["partes"])
    if n >= 3:
        romper(m, t, devedor, "inadimplencia")


@redutor("tratado_pagamento")
def _pagou(estado, ev):
    d = ev["dados"]
    de = estado["reinos"][d["de"]]["estoque"]
    para = estado["reinos"][d["para"]]["estoque"]
    for k, v in d["pago"].items():
        de[k] = r3(de[k] - v)
    for k, v in d["recebido"].items():
        para[k] = r3(para[k] + v if k == "ouro" else min(d["capacidade_para"][k], para[k] + v))
    estado["tratados"][d["tratado"]]["pagamentos"] += 1


@redutor("tratado_inadimplente")
def _inad(estado, ev):
    d = ev["dados"]
    t = estado["tratados"][d["tratado"]]
    t["inadimplencias"][d["reino"]] = d["seguidas"]
    r = estado["reinos"][d["reino"]]
    r["reputacao"] = max(0.0, r["reputacao"] - 3)


@redutor("tratado_em_dia")
def _em_dia(estado, ev):
    estado["tratados"][ev["dados"]["tratado"]]["inadimplencias"][ev["dados"]["reino"]] = 0


@redutor("pagamento_agendado")
def _pag_agendado(estado, ev):
    d = ev["dados"]
    agendar(estado, ev, d["em"], "pagamento_tratado", {"tratado": d["tratado"], "clausula": d["clausula"]})


@tratador_agenda("fim_tratado")
def _fim(m, item):
    t = m.estado["tratados"][item["dados"]["tratado"]]
    if t["status"] == "ativo":
        m.emitir("tratado_concluido", {"tratado": t["id"], "partes": t["partes"]}, ["publico"])


@redutor("tratado_concluido")
def _concluido(estado, ev):
    t = estado["tratados"][ev["dados"]["tratado"]]
    t["status"] = "concluido"
    for r in t["partes"]:
        estado["reinos"][r]["reputacao"] = min(100.0, estado["reinos"][r]["reputacao"] + 3)


@acao("romper_tratado")
def _v_romper(m, reino, p):
    t = m.estado["tratados"].get(p["tratado"])
    exigir(t is not None and reino in t["partes"] and t["status"] == "ativo", "tratado ativo não encontrado", codigo="sem_permissao")
    if tem_clausula(t, "tregua"):
        raise Rejeicao("proibido_por_tratado", "uma trégua não pode ser rompida")
    return Plano(depois=lambda m, ev: romper(m, t, reino, "rompido", causa=ev["dados"]["acao_id"]))


def romper(m, t, reino, motivo, causa=None):
    grave = tem_clausula(t, "nao_agressao") or tem_clausula(t, "defesa_mutua")
    m.emitir("tratado_rompido", {"tratado": t["id"], "por": reino, "motivo": motivo, "penalidade": 20 if grave else 10}, ["publico"], causa=causa)


@redutor("tratado_rompido")
def _rompido(estado, ev):
    d = ev["dados"]
    estado["tratados"][d["tratado"]]["status"] = "rompido"
    r = estado["reinos"][d["por"]]
    r["reputacao"] = max(0.0, r["reputacao"] - d["penalidade"])
