"""Tempo do mundo: instantes são inteiros em milissegundos UTC desde a época Unix."""

from __future__ import annotations

from datetime import datetime, timezone

HORA = 3_600_000
DIA = 24 * HORA


def iso(ms: int) -> str:
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms % 1000:03d}Z"


def de_iso(texto: str) -> int:
    dt = datetime.fromisoformat(texto.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(round(dt.timestamp() * 1000))


def agora_real() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp() * 1000)


def proxima_hora(ms: int) -> int:
    """Primeira virada de hora estritamente depois de `ms`."""
    return (ms // HORA + 1) * HORA


def inicio_do_dia(ms: int) -> int:
    return ms - ms % DIA
