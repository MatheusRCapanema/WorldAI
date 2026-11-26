"""Economia e população: tick de 1 hora e virada do dia (seções 4, 5 e 6).

Taxas diárias são multiplicadas pelo fator de compressão (seção 19). No tick
de 1 hora real entra 1/24 da taxa diária comprimida.
"""

from __future__ import annotations

from .mapa import vizinhos
from .redutor import informativo, redutor
from .regras import (
    BIOMAS,
    BONUS_CONSTRUCAO,
    BONUS_MERCADO_IMPOSTO,
    CONSTRUCOES,
    CULTURA_CONSTRUCAO,
    COLHEITA_POR_100_POR_DIA,
    DIAS_SAFRA,
    ESTACOES,
    FELICIDADE_CONSTRUCAO,
    LEIS,
    MERCADO_BASE,
    MULT_COLHEITA_ESTACAO,
    MULT_CRESCIMENTO_ESTACAO,
    MULT_JAZIDA,
    RECURSOS,
    TAXA_BASE,
    UNIDADES,
)
from .tempo import HORA

P0_OURO = {"comida": MERCADO_BASE["comida"]["P0"], "madeira": MERCADO_BASE["madeira"]["P0"],
           "ferro": MERCADO_BASE["ferro"]["P0"], "ouro": 1.0}


def r3(x: float) -> float:
    return round(x, 3)


# ---------------------------------------------------------------- leituras


def provincias_do_reino(estado: dict, reino: str) -> list[dict]:
    return [p for _, p in sorted(estado["provincias"].items()) if p["dono"] == reino]


def nivel_ativo(prov: dict, tipo: str) -> int:
    return sum(c["nivel"] for c in prov["construcoes"].values() if c["tipo"] == tipo and c["ativa"] and c["obra_ate"] is None)


def capacidade(estado: dict, reino: str, params) -> dict:
    """Teto de estoque por recurso (seção 4.2). O celeiro soma 1.000 só para comida (regras 0.2)."""
    provs = provincias_do_reino(estado, reino)
    armazens = sum(nivel_ativo(p, "armazem") for p in provs)
    celeiros = sum(nivel_ativo(p, "celeiro") for p in provs)
    base = params.estoque_base + params.estoque_por_armazem * armazens
    return {"comida": base + params.estoque_por_celeiro * celeiros, "madeira": base, "ferro": base}


def capacidade_moradia(prov: dict, params) -> int:
    return params.capacidade_moradia_base + params.capacidade_por_moradia * nivel_ativo(prov, "moradia")


def alocacao_efetiva(prov: dict, t: int, params) -> dict:
    """Transição linear de 24 h (comprimidas) entre a alocação antiga e a nova."""
    if prov["alocacao_desde"] is None:
        return dict(prov["alocacao_alvo"])
    prazo = params.duracao(24)
    frac = min(1.0, max(0.0, (t - prov["alocacao_desde"]) / prazo))
    o, a = prov["alocacao_origem"], prov["alocacao_alvo"]
    return {s: o[s] + (a[s] - o[s]) * frac for s in a}


def mult_felicidade(f: float) -> float:
    if f > 70:
        return 1.1
    if f < 40:
        return 0.8
    return 1.0


def faixa_felicidade(f: float) -> str:
    if f >= 80:
        return "alta"
    if f >= 40:
        return "normal"
    if f >= 20:
        return "baixa"
    return "critica"


def estado_guerra(estado: dict, reino: str) -> str | None:
    """'ofensiva' se o reino declarou alguma guerra ativa, 'defensiva' se só foi atacado."""
    tipo = None
    for g in estado["guerras"].values():
        if g["estado"] != "ativa" or reino not in (g["agressor"], g["alvo"]):
            continue
        if g["agressor"] == reino:
            return "ofensiva"
        tipo = "defensiva"
    return tipo


def produz(prov: dict) -> bool:
    return prov["ocupante"] is None and prov["revolta_desde"] is None and prov["sitiada_por"] is None


def leis_ativas(reino: dict, t: int) -> list[str]:
    return sorted(n for n, l in reino["leis"].items() if l["vale_em"] <= t)


def soldados_do_reino(estado: dict, reino: str) -> list[tuple[dict, int]]:
    out = []
    for _, e in sorted(estado["exercitos"].items()):
        if e["reino"] == reino:
            out.append((e, sum(c["soldados"] for c in e["companhias"])))
    return out


def fora_de_casa(estado: dict, exercito: dict) -> bool:
    p = estado["provincias"].get(exercito["provincia"])
    return p is None or p["dono"] != exercito["reino"]


def valor_ouro(recursos: dict) -> float:
    return sum(P0_OURO.get(r, 0) * q for r, q in recursos.items())


def bonus(prov: dict, alvo: str) -> float:
    b = 0.0
    for tipo, (efeito, por_nivel) in BONUS_CONSTRUCAO.items():
        if efeito == alvo:
            b += por_nivel * nivel_ativo(prov, tipo)
    return b


def alvo_felicidade(estado: dict, prov: dict, reino: dict, t: int, fome: float, frio: float, params) -> float:
    alvo = 55.0 - reino["aliquota"] * 0.8 - 40 * fome
    if estado["estacao"] == "inverno":
        alvo -= 15 * frio
    g = estado_guerra(estado, reino["id"])
    alvo -= {"ofensiva": 10, "defensiva": 5}.get(g, 0)
    if prov["ocupante"] is not None or prov["sitiada_por"] is not None:
        alvo -= 15
    cult = sum(v * nivel_ativo(prov, k) for k, v in FELICIDADE_CONSTRUCAO.items())
    alvo += min(20, cult)
    for lei in leis_ativas(reino, t):
        alvo += LEIS[lei]["felicidade"]
    for m in prov["mods"]:
        if m["ate"] > t:
            alvo += m["delta"]
    if prov["populacao"] > capacidade_moradia(prov, params):
        alvo -= 10
    return max(0.0, min(100.0, alvo))


# ---------------------------------------------------------------- tick


def tick_economico(m) -> None:
    estado, params, t = m.estado, m.params, m.agora
    f = params.fator
    por_tick = f / 24.0
    estacao = estado["estacao"]
    for rid in sorted(estado["reinos"]):
        reino = estado["reinos"][rid]
        provs = provincias_do_reino(estado, rid)
        est = dict(reino["estoque"])
        prod = {r: 0.0 for r in RECURSOS}
        cultura = 0.0
        leis = leis_ativas(reino, t)
        mult_leis = 0.85 if "lei_marcial" in leis else 1.0
        atualiza: dict[str, dict] = {}
        colheitas: dict[str, float] = {}
        pop_total = sum(p["populacao"] for p in provs)

        for p in provs:
            b = BIOMAS[p["bioma"]]
            aloc = alocacao_efetiva(p, t, params)
            pop = p["populacao"]
            w = {s: pop * aloc.get(s, 0) / 100.0 for s in aloc}
            mf = mult_felicidade(p["felicidade"]) * mult_leis
            safra = dict(p["safra"])
            if safra["inicio"] is None:
                safra = {"inicio": t - HORA, "soma": 0.0, "horas": 0}
            safra["horas"] += 1
            if produz(p):
                safra["soma"] += w["agricultura"]
                prod["madeira"] += w["madeira"] / 100 * TAXA_BASE["madeira"] * b["madeira"] * (1 + bonus(p, "madeira")) * mf * por_tick
                jaz = p["jazidas"]
                minas = [r for r in ("ferro", "ouro") if jaz.get(r)]
                for r in minas:
                    trab = w["mineracao"] / len(minas)
                    taxa = TAXA_BASE["ferro"] if r == "ferro" else TAXA_BASE["ouro_mina"]
                    prod[r] += trab / 100 * taxa * b[r] * MULT_JAZIDA[jaz[r]] * (1 + bonus(p, "mineracao")) * mf * por_tick
                prod["ouro"] += w["oficios"] / 100 * TAXA_BASE["oficios"] * b["ouro"] * (1 + bonus(p, "oficios")) * mf * por_tick
                imposto = pop * 0.05 * (reino["aliquota"] / 100) * (1 + BONUS_MERCADO_IMPOSTO * nivel_ativo(p, "mercado"))
                prod["ouro"] += imposto * por_tick
                if nivel_ativo(p, "porto"):
                    prod["comida"] += w["agricultura"] / 100 * 3 * por_tick
                c = w["cultura"] / 100 * TAXA_BASE["cultura"] * mf
                c += sum(v * nivel_ativo(p, k) for k, v in CULTURA_CONSTRUCAO.items())
                if p["felicidade"] >= 80:
                    c += 0.5 * pop / 1000
                cultura += c * por_tick
            if safra["horas"] >= params.horas_safra:
                medios = safra["soma"] / safra["horas"]
                colheita = (
                    medios / 100 * COLHEITA_POR_100_POR_DIA * DIAS_SAFRA * b["comida"] * MULT_COLHEITA_ESTACAO[estacao]
                    * (1 + 0.20 * nivel_ativo(p, "fazenda")) * mf
                )
                colheitas[p["id"]] = r3(colheita)
                prod["comida"] += colheita
                safra = {"inicio": t, "soma": 0.0, "horas": 0}
            atualiza[p["id"]] = {"safra": {"inicio": safra["inicio"], "soma": r3(safra["soma"]), "horas": safra["horas"]}}

        # Leis com cultura
        for lei in leis:
            cultura += LEIS[lei].get("cultura", 0) * por_tick

        for r in RECURSOS:
            est[r] += prod[r]

        # Consumo (seção 4.3)
        exercitos = soldados_do_reino(estado, rid)
        soldados_comida = sum(n * (1.5 if fora_de_casa(estado, e) else 1.0) for e, n in exercitos)
        civis = sum(p["populacao"] for p in provs if p["ocupante"] is None)
        mult_rac = 0.8 if "racionamento" in leis else 1.0
        deficits = {}
        precisa = {
            "comida": (civis + soldados_comida) / 10 * por_tick * mult_rac,
            "madeira": (civis / 50 * por_tick) if estacao == "inverno" else 0.0,
            "ouro": sum(
                UNIDADES[c["tipo"]].soldo * c["soldados"] / 100 for e, _ in exercitos for c in e["companhias"]
            ) * por_tick,
        }
        for r, q in precisa.items():
            if q <= 0:
                deficits[r] = 0.0
                continue
            pago = min(q, max(0.0, est[r]))
            est[r] -= pago
            deficits[r] = (q - pago) / q

        cap = capacidade(estado, rid, params)
        transbordou = {}
        for r in ("comida", "madeira", "ferro"):
            if est[r] > cap[r]:
                transbordou[r] = r3(est[r] - cap[r])
                est[r] = cap[r]
        est = {r: r3(max(0.0, v)) for r, v in est.items()}

        fome_hist = (reino["fome_hist"] + [r3(deficits["comida"])])[-24:]
        frio_hist = (reino["frio_hist"] + [r3(deficits["madeira"])])[-24:]
        fome = sum(fome_hist) / len(fome_hist)
        frio = sum(frio_hist) / len(frio_hist)
        fome_alta_desde = reino["fome_alta_desde"]
        if fome > 0.5:
            fome_alta_desde = fome_alta_desde if fome_alta_desde is not None else t
        else:
            fome_alta_desde = None
        fome_prolongada = fome_alta_desde is not None and t - fome_alta_desde >= params.duracao(48)

        # Felicidade e população por província
        passo = min(1.0, 0.05 * f)
        estoque_comida_dias = est["comida"] / max(1.0, pop_total / 10)
        eventos_prov = []
        for p in provs:
            alvo = alvo_felicidade(estado, p, reino, t, fome, frio, params)
            nova = r3(p["felicidade"] + (alvo - p["felicidade"]) * passo)
            faixa = faixa_felicidade(nova)
            pop = p["populacao"]
            if fome_prolongada:
                pop *= 1 - 0.01 * por_tick
            elif nova >= 40 and estoque_comida_dias >= params.dias_comida_crescimento and fome < 0.05 and pop < capacidade_moradia(p, params):
                mult = MULT_CRESCIMENTO_ESTACAO[estacao] * (1.5 if nova >= 80 else 1.0)
                pop = min(capacidade_moradia(p, params), pop * (1 + 0.004 * por_tick * mult))
            baixa = p["baixa_desde"]
            baixa = (baixa if baixa is not None else t) if nova < 20 else None
            atualiza[p["id"]].update({"felicidade": nova, "faixa": faixa, "populacao": r3(pop), "baixa_desde": baixa})
            if faixa != p["faixa"]:
                eventos_prov.append(("felicidade_faixa_mudou", {"provincia": p["id"], "de": p["faixa"], "para": faixa, "felicidade": nova}))
            if p["revolta_desde"] is None and baixa is not None and t - baixa >= params.duracao(72) and "lei_marcial" not in leis:
                eventos_prov.append(("revolta_iniciada", {"provincia": p["id"]}))
            elif p["revolta_desde"] is not None and nova > 35:
                eventos_prov.append(("revolta_encerrada", {"provincia": p["id"], "motivo": "felicidade"}))

        # Moral dos exércitos (seção 10.3): repouso em casa, soldo, fome
        morais = {}
        for e, _ in exercitos:
            moral = e["moral"]
            if e["movimento"] is None and e["batalha"] is None and not fora_de_casa(estado, e):
                moral += 5 * por_tick
            moral -= 10 * por_tick * deficits["ouro"]
            moral -= 10 * por_tick * deficits["comida"]
            morais[e["id"]] = r3(max(0.0, min(100.0, moral)))

        deficit_ant = dict(reino.get("deficit_ant", {}))
        transbordando_ant = list(reino.get("transbordando", []))
        m.emitir(
            "tick_economico",
            {
                "reino": rid,
                "estoque": est,
                "producao": {r: r3(v) for r, v in prod.items()},
                "producao_ouro": r3(valor_ouro(prod)),
                "cultura": r3(reino["cultura"] + cultura),
                "deficit": {r: r3(v) for r, v in deficits.items()},
                "fome_hist": fome_hist,
                "frio_hist": frio_hist,
                "fome_alta_desde": fome_alta_desde,
                "provincias": atualiza,
                "exercitos": morais,
                "colheitas": colheitas,
                "transbordando": sorted(transbordou),
            },
            [rid],
        )
        for pid, q in colheitas.items():
            m.emitir("safra_colhida", {"provincia": pid, "comida": q}, [rid])
        # Avisos só na transição, para não repetir o mesmo aviso a cada hora.
        for r, q in transbordou.items():
            if r not in transbordando_ant:
                m.emitir("estoque_transbordou", {"recurso": r, "perdido": q}, [rid])
        for r, v in deficits.items():
            if v > 0 and not deficit_ant.get(r):
                m.emitir("deficit", {"recurso": r, "fracao": r3(v)}, [rid])
        for tipo, dados in eventos_prov:
            m.emitir(tipo, dados, [rid] if tipo == "felicidade_faixa_mudou" else ["publico"])

    from .militar import tick_militar

    tick_militar(m)


@redutor("tick_economico")
def _tick(estado, ev):
    d = ev["dados"]
    reino = estado["reinos"][d["reino"]]
    reino["estoque"] = d["estoque"]
    reino["cultura"] = d["cultura"]
    reino["fome_hist"] = d["fome_hist"]
    reino["frio_hist"] = d["frio_hist"]
    reino["fome_alta_desde"] = d["fome_alta_desde"]
    reino["deficit_ant"] = {r: v > 0 for r, v in d["deficit"].items()}
    reino["transbordando"] = d["transbordando"]
    reino["producao_dia"] = round(reino["producao_dia"] + d["producao_ouro"], 3)
    for pid, campos in d["provincias"].items():
        estado["provincias"][pid].update(campos)
    for eid, moral in d["exercitos"].items():
        if eid in estado["exercitos"]:
            estado["exercitos"][eid]["moral"] = moral
    estado["ultimo_tick"] = ev["ocorrido_em"]


informativo("safra_colhida", "estoque_transbordou", "deficit", "felicidade_faixa_mudou")


@redutor("revolta_iniciada")
def _revolta(estado, ev):
    estado["provincias"][ev["dados"]["provincia"]]["revolta_desde"] = ev["ocorrido_em"]


@redutor("revolta_encerrada")
def _revolta_fim(estado, ev):
    estado["provincias"][ev["dados"]["provincia"]]["revolta_desde"] = None


# ---------------------------------------------------------------- virada do dia


def virada_do_dia(m) -> None:
    estado, params, t = m.estado, m.params, m.agora
    f = params.fator
    dia = estado["dia"] + 1
    idx = min(len(ESTACOES) - 1, (dia - 1) // params.dias_por_estacao)
    estacao = ESTACOES[idx]
    m.emitir(
        "dia_iniciado",
        {"dia": dia, "estacao": estacao, "cota": {"ordens": params.ordens_por_dia, "mensagens": params.mensagens_por_dia}},
        ["publico"],
    )
    if estacao != estado["estacao"]:
        m.emitir("estacao_iniciada", {"estacao": estacao}, ["publico"])

    for rid in sorted(estado["reinos"]):
        reino = estado["reinos"][rid]
        provs = provincias_do_reino(estado, rid)
        est = dict(reino["estoque"])
        # Deterioração da comida (seção 4.2)
        tem_celeiro = any(nivel_ativo(p, "celeiro") for p in provs)
        taxa = (0.005 if tem_celeiro else 0.01) * f
        perda = est["comida"] * taxa
        est["comida"] -= perda
        # Leis com custo diário
        custo_leis = sum(LEIS[l]["diario"] for l in leis_ativas(reino, t)) * f
        est["ouro"] = max(0.0, est["ouro"] - custo_leis)
        # Manutenção (seção 6): paga tudo ou desativa as de maior manutenção primeiro
        todas = []
        for p in provs:
            for c in p["construcoes"].values():
                if c["obra_ate"] is None:
                    todas.append((CONSTRUCOES[c["tipo"]].manutencao * c["nivel"] * f, p["id"], c["id"]))
        todas.sort(key=lambda x: (-x[0], x[1], x[2]))
        total = sum(x[0] for x in todas)
        ativas = {}
        if est["ouro"] >= total:
            est["ouro"] -= total
            for _, pid, cid in todas:
                ativas.setdefault(pid, {})[cid] = True
            pago, inativas = total, []
        else:
            restante = total
            inativas = []
            for custo, pid, cid in todas:
                if restante > est["ouro"] and custo > 0:
                    restante -= custo
                    ativas.setdefault(pid, {})[cid] = False
                    inativas.append(cid)
                else:
                    ativas.setdefault(pid, {})[cid] = True
            est["ouro"] -= restante
            pago = restante
        # Reputação volta 1 ponto por semana (de regra) em direção a 50
        rep = reino["reputacao"]
        passo = f / 7
        rep = rep + max(-passo, min(passo, 50 - rep))
        m.emitir(
            "virada_reino",
            {
                "reino": rid,
                "estoque": {r: r3(max(0.0, v)) for r, v in est.items()},
                "comida_deteriorada": r3(perda),
                "manutencao_paga": r3(pago),
                "custo_leis": r3(custo_leis),
                "construcoes_ativas": ativas,
                "reputacao": r3(rep),
            },
            [rid],
        )
        if inativas:
            m.emitir("manutencao_atrasada", {"construcoes_inativas": inativas}, [rid])

    # Migração (seção 5.5): felicidade < 40 perde 0,5%/dia para a vizinha mais feliz
    migracoes = []
    for pid, p in sorted(estado["provincias"].items()):
        if p["tipo"] != "reino" or p["dono"] is None or p["felicidade"] >= 40:
            continue
        candidatos = []
        for vid, _ in vizinhos(estado, pid):
            v = estado["provincias"][vid]
            if v["tipo"] != "reino" or v["dono"] is None or v["felicidade"] <= p["felicidade"]:
                continue
            if v["dono"] != p["dono"] and _em_guerra_par(estado, v["dono"], p["dono"]):
                continue
            candidatos.append((v["felicidade"], vid))
        if candidatos:
            _, destino = max(candidatos)
            pessoas = r3(p["populacao"] * 0.005 * f)
            migracoes.append({"de": pid, "para": destino, "pessoas": pessoas})
    for mig in migracoes:
        de, para = estado["provincias"][mig["de"]], estado["provincias"][mig["para"]]
        m.emitir("migracao", mig, sorted({de["dono"], para["dono"]}))

    # Mercados voltam para E0 em 5% da diferença por dia
    novos = {}
    for cid, merc in sorted(estado["mercados"].items()):
        novos[cid] = {}
        for r, v in merc.items():
            novos[cid][r] = r3(v["E"] + (v["E0"] - v["E"]) * min(1.0, 0.05 * f))
    m.emitir("mercados_recuperados", {"mercados": novos}, [])

    from .militar import checar_inatividade_guerras
    from .ranking import ranking_diario

    checar_inatividade_guerras(m)
    ranking_diario(m)


def _em_guerra_par(estado, a, b) -> bool:
    for g in estado["guerras"].values():
        if g["estado"] == "ativa" and {g["agressor"], g["alvo"]} == {a, b}:
            return True
    return False


@redutor("dia_iniciado")
def _dia(estado, ev):
    d = ev["dados"]
    estado["dia"] = d["dia"]
    estado["estacao"] = d["estacao"]
    for r in estado["reinos"].values():
        r["cota"] = dict(d["cota"])
        r["producao_hist"] = (r["producao_hist"] + [r["producao_dia"]])[-7:]
        r["producao_dia"] = 0.0
    # Expira chaves de idempotência com mais de 24 h
    limite = ev["ocorrido_em"] - 86_400_000
    for k in [k for k, v in estado["idempotencia"].items() if v["em"] < limite]:
        del estado["idempotencia"][k]
    for p in estado["provincias"].values():
        p["mods"] = [m for m in p["mods"] if m["ate"] > ev["ocorrido_em"]]


informativo("estacao_iniciada", "manutencao_atrasada")


@redutor("virada_reino")
def _virada_reino(estado, ev):
    d = ev["dados"]
    reino = estado["reinos"][d["reino"]]
    reino["estoque"] = d["estoque"]
    reino["reputacao"] = d["reputacao"]
    for pid, cs in d["construcoes_ativas"].items():
        for cid, ativa in cs.items():
            estado["provincias"][pid]["construcoes"][cid]["ativa"] = ativa


@redutor("migracao")
def _migracao(estado, ev):
    d = ev["dados"]
    estado["provincias"][d["de"]]["populacao"] = r3(estado["provincias"][d["de"]]["populacao"] - d["pessoas"])
    estado["provincias"][d["para"]]["populacao"] = r3(estado["provincias"][d["para"]]["populacao"] + d["pessoas"])


@redutor("mercados_recuperados")
def _mercados(estado, ev):
    for cid, rs in ev["dados"]["mercados"].items():
        for r, e in rs.items():
            estado["mercados"][cid][r]["E"] = e
