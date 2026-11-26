import pytest

from arena.motor import Motor
from arena.regras import Parametros
from arena.tempo import de_iso

INICIO = de_iso("2026-12-01T00:00:00Z")


@pytest.fixture
def motor():
    return Motor.nova_era(7, INICIO)


@pytest.fixture
def motor_farto():
    """Era com estoque grande e sem limite prático, para medir fórmulas sem fome."""
    p = Parametros(estoque_base=10**7, inicio_estoque={"comida": 10**6, "madeira": 10**5, "ferro": 10**5, "ouro": 10**5})
    return Motor.nova_era(7, INICIO, p)


def acao(_tipo, chave=None, /, **parametros):
    a = {"tipo": _tipo, "parametros": parametros}
    if chave:
        a["chave_idempotencia"] = chave
    return a


def ok(m, reino, a, instante=None):
    status, corpo = m.submeter(reino, a, instante=instante)
    assert status == 202, corpo
    return corpo


def eventos(m, tipo=None):
    return [e for e in m.armazem.todos() if tipo is None or e["tipo"] == tipo]
