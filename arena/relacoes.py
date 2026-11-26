"""Leituras sobre relações entre reinos (seção 9.2). Só leitura, sem efeitos."""

from __future__ import annotations


def guerra_entre(estado: dict, a: str, b: str, estados=("declarada", "ativa")) -> dict | None:
    for _, g in sorted(estado["guerras"].items()):
        if g["estado"] in estados and {g["agressor"], g["alvo"]} == {a, b}:
            return g
    return None


def em_guerra(estado: dict, a: str | None, b: str | None) -> bool:
    if a is None or b is None or a == b:
        return False
    return guerra_entre(estado, a, b, ("ativa",)) is not None


def tratados_ativos(estado: dict, reino: str) -> list[dict]:
    return [t for _, t in sorted(estado["tratados"].items()) if t["status"] == "ativo" and reino in t["partes"]]


def tratados_ativos_entre(estado: dict, a: str, b: str) -> list[dict]:
    return [t for t in tratados_ativos(estado, a) if b in t["partes"]]


def tem_clausula(tratado: dict, tipo: str) -> bool:
    return any(c["tipo"] == tipo for c in tratado["clausulas"])


def tregua_ativa(estado: dict, a: str, b: str, t: int) -> bool:
    for tr in tratados_ativos_entre(estado, a, b):
        for c in tr["clausulas"]:
            if c["tipo"] == "tregua" and tr["ativado_em"] + c["_ms"] > t:
                return True
    for g in estado["guerras"].values():
        if {g["agressor"], g["alvo"]} == {a, b} and g.get("tregua_ate") and g["tregua_ate"] > t:
            return True
    return False


def relacao(estado: dict, a: str, b: str) -> str:
    if em_guerra(estado, a, b):
        return "guerra"
    tratados = tratados_ativos_entre(estado, a, b)
    if any(tem_clausula(t, "defesa_mutua") for t in tratados):
        return "alianca"
    if any(tem_clausula(t, "nao_agressao") for t in tratados):
        return "nao_agressao"
    return "neutro"
