"""Sorteios determinísticos (seção 18.3).

Cada sorteio usa hash(semente_mestre, tipo_do_sorteio, id_do_objeto, instante).
Não há estado de gerador: o replay chega ao mesmo número sem guardá-lo.
"""

from __future__ import annotations

import hashlib


def uniforme(semente: int, tipo: str, objeto: str, instante: int) -> float:
    """Número em [0, 1) derivado só dos argumentos."""
    chave = f"{semente}|{tipo}|{objeto}|{instante}".encode()
    h = hashlib.sha256(chave).digest()
    return int.from_bytes(h[:8], "big") / 2**64


def entre(semente: int, tipo: str, objeto: str, instante: int, a: float, b: float) -> float:
    return a + (b - a) * uniforme(semente, tipo, objeto, instante)


def chance(semente: int, tipo: str, objeto: str, instante: int, p: float) -> bool:
    return uniforme(semente, tipo, objeto, instante) < p
