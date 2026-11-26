"""Mapa de teste com 3 reinos, 1 cidade livre e 3 terras selvagens.

O mapa é simétrico: os três reinos têm os mesmos biomas e jazidas, o que
cumpre a regra de "mesmo valor de terra" da seção 3.6 por construção.

        a1 (capital)                Cada reino k tem:
       /  \\                          k1 capital, planície
     a2 -- a3                         k2 floresta
     |      \\                         k3 colina com ferro 2
    w_c     w_a ---- b2               w_k pântano entre k3 e (k+1)2
      \\     |       /  \\
       \\   cid    b3 -- b1          cid: cidade livre (Porto Livre),
        \\  / \\    |                     ligada às três terras selvagens
         c3   ... w_b
        ...
"""

from __future__ import annotations

import copy

from .regras import ALOCACAO_PADRAO, BIOMAS, MULT_JAZIDA, Parametros

REINOS_TESTE = [
    ("reino_a", "Aurel", "fazendeiro"),
    ("reino_b", "Vel", "mercador"),
    ("reino_c", "Dornas", "conquistador"),
]


def valor_terra(prov: dict) -> float:
    """Valor de terra (seção 3.6): multiplicadores de comida, madeira e ouro do
    bioma mais metade da riqueza de cada jazida (definição do protótipo)."""
    b = BIOMAS[prov["bioma"]]
    v = b["comida"] + b["madeira"] + b["ouro"]
    for _, riqueza in prov.get("jazidas", {}).items():
        v += 0.5 * riqueza
    return round(v, 3)


def _provincia(pid, nome, regiao, bioma, dono, pop, capital=False, jazidas=None, tipo="reino", coord=(0, 0)):
    return {
        "id": pid,
        "nome": nome,
        "regiao": regiao,
        "bioma": bioma,
        "tipo": tipo,  # reino | selvagem | cidade_livre
        "dono": dono,
        "ocupante": None,
        "ocupado_desde": None,
        "capital": capital,
        "populacao": pop,
        "felicidade": 55.0,
        "faixa": "normal",
        "slots": 8 if capital else 6,
        "construcoes": {},
        "jazidas": dict(jazidas or {}),
        "costeira": bioma == "costa",
        "alocacao_origem": dict(ALOCACAO_PADRAO),
        "alocacao_alvo": dict(ALOCACAO_PADRAO),
        "alocacao_desde": None,
        "safra": {"inicio": None, "soma": 0.0, "horas": 0},
        "baixa_desde": None,
        "revolta_desde": None,
        "mods": [],
        "muralha_integridade": 0.0,
        "sitiada_por": None,
        "coordenadas": list(coord),
    }


def criar_estado_inicial(semente: int, inicio: int, params: Parametros) -> dict:
    """Estado do instante zero da era. Vai inteiro no evento `era_iniciada`."""
    provincias: dict[str, dict] = {}
    trechos: list[dict] = []
    reinos: dict[str, dict] = {}
    exercitos: dict[str, dict] = {}
    contadores = {"acao": 0, "exe": 0, "car": 0, "tra": 0, "bat": 0, "con": 0, "ofe": 0}

    def novo_id(prefixo, chave):
        contadores[chave] += 1
        return f"{prefixo}_{contadores[chave]:04d}"

    letras = [r[0][-1] for r in REINOS_TESTE]
    angulos = [(500, 100), (850, 700), (150, 700)]
    for i, (rid, nome, arquetipo) in enumerate(REINOS_TESTE):
        k = letras[i]
        x, y = angulos[i]
        regiao = f"terras_de_{nome.lower()}"
        cap = f"prov_{k}1"
        provincias[cap] = _provincia(cap, f"{nome} Capital", regiao, "planicie", rid, 2500, capital=True, coord=(x, y))
        provincias[f"prov_{k}2"] = _provincia(f"prov_{k}2", f"Bosque de {nome}", regiao, "floresta", rid, 2000, coord=(x - 60, y + 60))
        provincias[f"prov_{k}3"] = _provincia(
            f"prov_{k}3", f"Colinas de {nome}", regiao, "colina", rid, 2000, jazidas={"ferro": 2}, coord=(x + 60, y + 60)
        )
        for a, b in ((cap, f"prov_{k}2"), (cap, f"prov_{k}3"), (f"prov_{k}2", f"prov_{k}3")):
            trechos.append({"a": a, "b": b, "tipo": "trilha"})
        reinos[rid] = {
            "id": rid,
            "nome": nome,
            "arquetipo_bot": arquetipo,
            "capital": cap,
            "estoque": dict(params.inicio_estoque),
            "cota": {"ordens": params.ordens_por_dia, "mensagens": params.mensagens_por_dia},
            "aliquota": 15,
            "aliquota_mudou_em": None,
            "leis": {},
            "leis_espera": {},
            "reputacao": 50.0,
            "cultura": 0.0,
            "fome_hist": [],
            "frio_hist": [],
            "fome_alta_desde": None,
            "producao_dia": 0.0,
            "producao_hist": [],
            "populacao_inicial": 6500,
            "pedagio": 0,
            "dias_tratado": [],
        }
        # Construções iniciais (seção 19)
        for pid, tipos in ((cap, ("fazenda", "mercado")), (f"prov_{k}2", ("fazenda",)), (f"prov_{k}3", ("fazenda",))):
            for t in tipos:
                cid = novo_id("con", "con")
                provincias[pid]["construcoes"][cid] = {"id": cid, "tipo": t, "nivel": 1, "ativa": True, "obra_ate": None}
        # Exército inicial: 2 milícias e 1 infantaria na capital
        eid = novo_id("exe", "exe")
        exercitos[eid] = {
            "id": eid,
            "reino": rid,
            "provincia": cap,
            "companhias": [
                {"tipo": "milicia", "soldados": 100},
                {"tipo": "milicia", "soldados": 100},
                {"tipo": "infantaria", "soldados": 100},
            ],
            "moral": 100.0,
            "postura": "defensiva",
            "movimento": None,
            "batalha": None,
            "veio_de": None,
            "chegou_em": inicio,
            "acao": None,
        }

    # Terras selvagens entre reinos vizinhos e a cidade livre no centro
    cid = "cid_portolivre"
    provincias[cid] = _provincia(cid, "Porto Livre", "mar_interior", "costa", None, 5000, tipo="cidade_livre", coord=(500, 500))
    for i in range(3):
        k, prox = letras[i], letras[(i + 1) % 3]
        wid = f"prov_w{k}"
        provincias[wid] = _provincia(wid, f"Charco de {k.upper()}{prox.upper()}", "charcos", "pantano", None, 0, tipo="selvagem")
        trechos.append({"a": f"prov_{k}3", "b": wid, "tipo": "trilha"})
        trechos.append({"a": wid, "b": f"prov_{prox}2", "tipo": "trilha"})
        trechos.append({"a": wid, "b": cid, "tipo": "trilha"})

    for p in provincias.values():
        p["valor_terra"] = valor_terra(p) if p["tipo"] == "reino" else 0.0
        if p["tipo"] != "reino":
            p["felicidade"] = 50.0

    mercados = {cid: {r: {"E": v["E0"], "E0": v["E0"], "P0": v["P0"]} for r, v in _mercado_base().items()}}

    return {
        "era": 1,
        "semente": semente,
        "inicio": inicio,
        "fim": inicio + params.duracao_era_dias * 86_400_000,
        "parametros": params.como_dict(),
        "agora": inicio,
        "seq_global": 0,
        "ultimo_tick": inicio,
        "dia": 1,
        "estacao": "primavera",
        "encerrada": False,
        "provincias": provincias,
        "trechos": trechos,
        "reinos": reinos,
        "exercitos": exercitos,
        "guerras": {},
        "tratados": {},
        "mercados": mercados,
        "caravanas": {},
        "acoes": {},
        "batalhas": {},
        "agenda": {},
        "idempotencia": {},
        "ranking": {},
        "ranking_hist": {rid: [] for rid in reinos},
        "contadores": contadores,
    }


def _mercado_base():
    from .regras import MERCADO_BASE

    return copy.deepcopy(MERCADO_BASE)


def vizinhos(estado: dict, pid: str) -> list[tuple[str, dict]]:
    out = []
    for t in estado["trechos"]:
        if t["a"] == pid:
            out.append((t["b"], t))
        elif t["b"] == pid:
            out.append((t["a"], t))
    return sorted(out, key=lambda x: x[0])
