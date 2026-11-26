"""Log no PostgreSQL. Roda só com ARENA_TEST_PG=<dsn> (o banco é limpo no início)."""

import os

import pytest

from arena.motor import Motor, hash_estado
from arena.simulador import simular

DSN = os.environ.get("ARENA_TEST_PG")
pytestmark = pytest.mark.skipif(not DSN, reason="defina ARENA_TEST_PG para testar com PostgreSQL")


@pytest.fixture
def armazem():
    import psycopg

    from arena.armazenamento import PostgresEventos

    with psycopg.connect(DSN, autocommit=True) as con:
        con.execute("DROP TABLE IF EXISTS indice_reino, eventos CASCADE")
    a = PostgresEventos(DSN)
    yield a
    a.fechar()


def test_replay_pelo_postgres(armazem):
    from arena.armazenamento import PostgresEventos

    res = simular(3, semente=21, armazem=armazem)
    assert res["replay_identico"]
    novo = PostgresEventos(DSN)
    m = Motor.do_log(novo)
    assert hash_estado(m.estado) == res["hash_estado"]
    evs = novo.eventos_do_reino("reino_a", 0, 50)
    assert [e["seq"] for e in evs] == list(range(1, 51))
    novo.fechar()


def test_log_so_aceita_insercao(armazem):
    import psycopg

    simular(0.2, semente=1, armazem=armazem, verificar_replay=False)
    with psycopg.connect(DSN, autocommit=True) as con:
        with pytest.raises(psycopg.errors.RaiseException):
            con.execute("UPDATE eventos SET tipo = 'x' WHERE seq_global = 1")
        with pytest.raises(psycopg.errors.RaiseException):
            con.execute("DELETE FROM eventos WHERE seq_global = 1")
