"""O que cada reino vê (seção 15) e o retrato do estado (seção 17.5)."""

from __future__ import annotations

from .economia import alocacao_efetiva, capacidade, leis_ativas, r3
from .mapa import vizinhos
from .relacoes import relacao
from .tempo import DIA, iso


def _publico_provincia(p: dict) -> dict:
    return {k: p[k] for k in ("id", "nome", "regiao", "bioma", "tipo", "dono", "ocupante", "capital", "coordenadas")}


def _resumo_exercito(e: dict, exato: bool) -> dict:
    total = sum(c["soldados"] for c in e["companhias"])
    tipos: dict[str, int] = {}
    for c in e["companhias"]:
        tipos[c["tipo"]] = tipos.get(c["tipo"], 0) + c["soldados"]
    base = {"id": e["id"], "reino": e["reino"], "provincia": e["provincia"]}
    if exato:
        return dict(base, companhias=e["companhias"], moral=e["moral"], postura=e["postura"], movimento=e["movimento"], batalha=e["batalha"])
    return dict(base, soldados_aprox=int(round(total, -2)), tipo_predominante=max(tipos, key=tipos.get) if tipos else None)


def estado_do_reino(m, reino: str) -> dict:
    estado, t = m.estado, m.agora
    r = estado["reinos"][reino]
    proprias = {pid for pid, p in estado["provincias"].items() if p["dono"] == reino}
    com_exercito = {e["provincia"] for e in estado["exercitos"].values() if e["reino"] == reino}
    completas = proprias | com_exercito
    parciais = set()
    for pid in proprias:
        for v, _ in vizinhos(estado, pid):
            if v not in completas:
                parciais.add(v)
    provs = []
    for pid in sorted(completas):
        p = dict(estado["provincias"][pid])
        p["alocacao_efetiva"] = {k: r3(v) for k, v in alocacao_efetiva(p, t, m.params).items()}
        provs.append(p)
    visiveis = []
    for pid in sorted(parciais):
        p = estado["provincias"][pid]
        visiveis.append(dict(_publico_provincia(p), construcoes=[{"tipo": c["tipo"], "nivel": c["nivel"]} for c in p["construcoes"].values()]))
    exercitos = [_resumo_exercito(e, True) for _, e in sorted(estado["exercitos"].items()) if e["reino"] == reino]
    avistados = [
        _resumo_exercito(e, e["provincia"] in completas)
        for _, e in sorted(estado["exercitos"].items())
        if e["reino"] != reino and (e["provincia"] in completas or e["provincia"] in parciais)
    ]
    tratados = [t_ for _, t_ in sorted(estado["tratados"].items()) if reino in t_["partes"] and t_["status"] in ("ativo", "proposto")]
    acoes = [
        {k: a[k] for k in ("id", "tipo", "parametros", "status", "conclusao_em")}
        for _, a in sorted(estado["acoes"].items())
        if a["reino"] == reino and a["status"] == "em_andamento"
    ]
    return {
        "seq": m.armazem.ultimo_seq_reino(reino),
        "agora": iso(t),
        "dia": estado["dia"],
        "estacao": estado["estacao"],
        "reino": {
            "id": reino, "nome": r["nome"], "capital": r["capital"], "reputacao": r["reputacao"], "aliquota": r["aliquota"],
            "leis": leis_ativas(r, t), "leis_pendentes": sorted(n for n, l in r["leis"].items() if l["vale_em"] > t),
            "cultura": r["cultura"], "regencia": False,
        },
        "estoque": r["estoque"],
        "capacidade": capacidade(estado, reino, m.params),
        "cota": dict(r["cota"], renova_em=iso((t // DIA + 1) * DIA)),
        "provincias": provs,
        "visiveis": visiveis,
        "exercitos": exercitos,
        "exercitos_avistados": avistados,
        "caravanas": [c for _, c in sorted(estado["caravanas"].items()) if c["reino"] == reino],
        "acoes_em_andamento": acoes,
        "tratados": tratados,
        "relacoes": {o: relacao(estado, reino, o) for o in sorted(estado["reinos"]) if o != reino},
        "guerras": [g for _, g in sorted(estado["guerras"].items()) if reino in (g["agressor"], g["alvo"]) and g["estado"] != "encerrada"],
        "mercados": _mercados_publicos(estado),
        "ranking": estado["ranking"].get(reino, {}),
    }


def _mercados_publicos(estado):
    from .comercio import preco

    return {
        cid: {r: {"preco": r3(preco(v, v["E"])), "estoque": v["E"]} for r, v in merc.items()}
        for cid, merc in sorted(estado["mercados"].items())
    }


def mundo_publico(m) -> dict:
    estado = m.estado
    return {
        "agora": iso(m.agora),
        "era": estado["era"],
        "dia": estado["dia"],
        "estacao": estado["estacao"],
        "inicio": iso(estado["inicio"]),
        "fim": iso(estado["fim"]),
        "encerrada": estado["encerrada"],
        "provincias": [_publico_provincia(p) for _, p in sorted(estado["provincias"].items())],
        "trechos": estado["trechos"],
        "reinos": [
            {"id": rid, "nome": r["nome"], "capital": r["capital"], "reputacao": r["reputacao"]}
            for rid, r in sorted(estado["reinos"].items())
        ],
        "relacoes": {
            f"{a}|{b}": relacao(estado, a, b)
            for a in sorted(estado["reinos"]) for b in sorted(estado["reinos"]) if a < b
        },
        "guerras": [g for _, g in sorted(estado["guerras"].items())],
        "tratados_ativos": [
            {"id": t["id"], "partes": t["partes"], "clausulas": [c["tipo"] for c in t["clausulas"]]}
            for _, t in sorted(estado["tratados"].items()) if t["status"] == "ativo"
        ],
        "mercados": _mercados_publicos(estado),
        "ranking": estado["ranking"],
        "resultado_final": estado.get("resultado_final"),
    }
