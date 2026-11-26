"""Simulador acelerado: roda dias de mundo em segundos, sem API (seção 20.2, item 4).

Uso:
    python -m arena.simulador --dias 28 --semente 42 --log saida/era.jsonl

O relógio é simulado: o motor avança hora a hora e, a cada `--bots-cada` horas,
cada bot lê o retrato do próprio reino e envia ações pelo mesmo caminho da API
(`Motor.submeter`). No fim, o simulador refaz o log do zero e confere se o
estado reconstruído é idêntico ao estado ao vivo.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
import time

from .armazenamento import ArquivoEventos, MemoriaEventos
from .bots import criar_bots
from .motor import Motor, hash_estado
from .regras import Parametros
from .tempo import DIA, HORA, de_iso, iso
from .visao import estado_do_reino

INICIO_PADRAO = "2026-12-01T00:00:00Z"


def simular(dias: float = 28, semente: int = 42, inicio: str = INICIO_PADRAO, bots_cada_h: int = 3,
            armazem=None, params: Parametros | None = None, verificar_replay: bool = True, ao_dia=None) -> dict:
    t0 = de_iso(inicio)
    m = Motor.nova_era(semente, t0, params or Parametros(), armazem or MemoriaEventos())
    bots = criar_bots(m.estado)
    stats = collections.Counter()
    rejeicoes = collections.Counter()
    fim = min(t0 + int(dias * DIA), m.estado["fim"])
    t = t0
    inicio_real = time.perf_counter()
    while t < fim and not m.estado["encerrada"]:
        t += HORA
        m.avancar_ate(t)
        if m.estado["encerrada"]:
            break
        if (t - t0) // HORA % bots_cada_h == 0:
            for rid, bot in bots.items():
                visao = estado_do_reino(m, rid)
                for a in bot.decidir(visao, t, m.params.fator):
                    status, corpo = m.submeter(rid, a)
                    if status == 202:
                        stats[f"aceitas:{rid}"] += 1
                    else:
                        rejeicoes[f"{a['tipo']}:{corpo['erro']['codigo']}"] += 1
        if ao_dia and t % DIA == 0:
            ao_dia(m)
    if t >= m.estado["fim"] and not m.estado["encerrada"]:
        m.avancar_ate(m.estado["fim"])
    duracao = time.perf_counter() - inicio_real

    contagem = collections.Counter()
    for ev in m.armazem.todos():
        contagem[ev["tipo"]] += 1
    resumo = {
        "semente": semente,
        "dias_simulados": round((m.agora - t0) / DIA, 2),
        "segundos_reais": round(duracao, 2),
        "eventos": m.armazem.ultimo_seq(),
        "hash_estado": hash_estado(m.estado),
        "ranking": m.estado["ranking"],
        "resultado_final": m.estado.get("resultado_final"),
        "reinos": {
            rid: {
                "arquetipo": r["arquetipo_bot"],
                "estoque": r["estoque"],
                "reputacao": r["reputacao"],
                "cultura": r["cultura"],
                "populacao": round(sum(p["populacao"] for p in m.estado["provincias"].values() if p["dono"] == rid)),
                "provincias": sorted(p["id"] for p in m.estado["provincias"].values() if p["dono"] == rid),
                "felicidade_media": round(
                    sum(p["felicidade"] for p in m.estado["provincias"].values() if p["dono"] == rid)
                    / max(1, sum(1 for p in m.estado["provincias"].values() if p["dono"] == rid)), 1),
                "acoes_aceitas": stats[f"aceitas:{rid}"],
            }
            for rid, r in sorted(m.estado["reinos"].items())
        },
        "eventos_por_tipo": dict(sorted(contagem.items())),
        "rejeicoes": dict(sorted(rejeicoes.items())),
    }
    if verificar_replay:
        m2 = Motor.do_log(m.armazem)
        resumo["replay_identico"] = hash_estado(m2.estado) == resumo["hash_estado"]
    resumo["_motor"] = m
    return resumo


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Simulador acelerado da Arena de Reinos")
    ap.add_argument("--dias", type=float, default=28)
    ap.add_argument("--semente", type=int, default=42)
    ap.add_argument("--inicio", default=INICIO_PADRAO)
    ap.add_argument("--bots-cada", type=int, default=3, help="horas de mundo entre decisões dos bots")
    ap.add_argument("--log", help="grava o log em JSON Lines neste arquivo (precisa não existir)")
    ap.add_argument("--json", action="store_true", help="imprime o resumo em JSON")
    args = ap.parse_args(argv)

    armazem = None
    if args.log:
        import os

        if os.path.exists(args.log):
            print(f"o arquivo {args.log} já existe", file=sys.stderr)
            return 2
        os.makedirs(os.path.dirname(args.log) or ".", exist_ok=True)
        armazem = ArquivoEventos(args.log)

    def progresso(m):
        if not args.json:
            r = m.estado["ranking"]
            linha = "  ".join(f"{k}={v['geral']:.1f}" for k, v in sorted(r.items()))
            print(f"dia {m.estado['dia']:>2} ({m.estado['estacao']}): {linha}")

    res = simular(args.dias, args.semente, args.inicio, args.bots_cada, armazem=armazem, ao_dia=progresso)
    res.pop("_motor")
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print()
        print(f"{res['dias_simulados']} dias de mundo em {res['segundos_reais']} s, {res['eventos']} eventos")
        print(f"replay idêntico ao estado ao vivo: {res.get('replay_identico')}")
        for rid, r in res["reinos"].items():
            print(f"- {rid} ({r['arquetipo']}): pop {r['populacao']}, felicidade {r['felicidade_media']}, "
                  f"províncias {len(r['provincias'])}, cultura {r['cultura']:.0f}, reputação {r['reputacao']:.0f}, "
                  f"ações {r['acoes_aceitas']}")
        if res["resultado_final"]:
            print("resultado final:", res["resultado_final"])
        print("rejeições:", res["rejeicoes"])
    if armazem:
        armazem.fechar()
    return 0 if res.get("replay_identico", True) else 1


if __name__ == "__main__":
    sys.exit(main())
