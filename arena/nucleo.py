"""Redutores de base: início da era e itens de agenda descartados."""

from __future__ import annotations

import copy

from .redutor import redutor


def usar_id(estado: dict, chave: str, ident: str) -> None:
    """Avança o contador de ids até o número de `ident` (ex.: exe_0007 -> 7)."""
    n = int(ident.rsplit("_", 1)[1])
    c = estado["contadores"]
    c[chave] = max(c.get(chave, 0), n)


@redutor("era_iniciada")
def _era_iniciada(estado, ev):
    inicial = copy.deepcopy(ev["dados"]["estado_inicial"])
    estado.clear()
    estado.update(inicial)


@redutor("agenda_descartada")
def _descartada(estado, ev):
    pass  # a remoção do item é feita pelo campo agenda_concluida
