"""Ranking diário e final da era (seção 16)."""

from __future__ import annotations

import math

from .economia import provincias_do_reino, r3, valor_ouro
from .redutor import redutor
from .relacoes import tratados_ativos

DIMENSOES = ("prosperidade", "bem_estar", "cooperacao", "cultura", "territorio")


def valores_brutos(estado: dict, params) -> dict:
    f = params.fator
    janela = max(1, math.ceil(14 / f))  # 14 dias de regra em dias reais
    brutos = {}
    for rid, r in sorted(estado["reinos"].items()):
        provs = provincias_do_reino(estado, rid)
        hist = r["producao_hist"] or [0.0]
        prosperidade = sum(hist) / len(hist) + 0.1 * valor_ouro(r["estoque"])
        pop = sum(p["populacao"] for p in provs)
        fel = sum(p["felicidade"] * p["populacao"] for p in provs) / pop if pop else 0.0
        bem_estar = fel * math.sqrt(pop / r["populacao_inicial"]) if pop else 0.0
        dias_tratado = (r["dias_tratado"] + [len(tratados_ativos(estado, rid))])[-janela:]
        cooperacao = 0.5 * r["reputacao"] + 2 * sum(dias_tratado) * f
        territorio = sum(p["valor_terra"] for p in provs if p["ocupante"] is None)
        brutos[rid] = {
            "prosperidade": r3(prosperidade), "bem_estar": r3(bem_estar), "cooperacao": r3(cooperacao),
            "cultura": r3(r["cultura"]), "territorio": r3(territorio), "_dias_tratado": dias_tratado,
        }
    return brutos


def normalizar(brutos: dict) -> dict:
    out = {rid: {} for rid in brutos}
    for d in DIMENSOES:
        topo = max(v[d] for v in brutos.values())
        for rid, v in brutos.items():
            out[rid][d] = r3(max(0.0, 100 * v[d] / topo)) if topo > 0 else 0.0
    for rid in out:
        out[rid]["geral"] = r3(sum(0.2 * out[rid][d] for d in DIMENSOES))
    return out


def ranking_diario(m) -> None:
    brutos = valores_brutos(m.estado, m.params)
    norm = normalizar(brutos)
    m.emitir(
        "ranking_diario",
        {"dia": m.estado["dia"], "ranking": norm, "brutos": {r: {k: v for k, v in b.items() if not k.startswith("_")} for r, b in brutos.items()},
         "dias_tratado": {r: b["_dias_tratado"] for r, b in brutos.items()}},
        ["publico"],
    )


@redutor("ranking_diario")
def _ranking(estado, ev):
    d = ev["dados"]
    estado["ranking"] = d["ranking"]
    for rid, v in d["ranking"].items():
        estado["ranking_hist"][rid].append(v["geral"])
        estado["reinos"][rid]["dias_tratado"] = d["dias_tratado"][rid]


def encerrar_era(m) -> None:
    ranking_diario(m)
    final = {}
    for rid, hist in sorted(m.estado["ranking_hist"].items()):
        media = sum(hist) / len(hist) if hist else 0.0
        ultimo = hist[-1] if hist else 0.0
        final[rid] = r3(0.5 * media + 0.5 * ultimo)
    ordem = sorted(final, key=lambda r: (-final[r], r))
    m.emitir("era_encerrada", {"final": final, "classificacao": ordem, "ranking_ultimo_dia": m.estado["ranking"],
                               "semente": m.estado["semente"]}, ["publico"])


@redutor("era_encerrada")
def _fim(estado, ev):
    estado["encerrada"] = True
    estado["resultado_final"] = ev["dados"]["final"]
