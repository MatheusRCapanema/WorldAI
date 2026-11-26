"""O log reconstrói o estado e a mesma semente dá o mesmo mundo (seção 18)."""

import pytest

from arena.armazenamento import ArquivoEventos
from arena.motor import Motor, hash_estado
from arena.simulador import simular


def test_era_completa_replay_identico():
    res = simular(28, semente=42)
    assert res["replay_identico"] is True
    assert res["resultado_final"] is not None  # a era chegou ao fim
    m = res["_motor"]
    assert m.estado["encerrada"]


def test_mesma_semente_mesmo_log():
    a = simular(6, semente=11)["_motor"]
    b = simular(6, semente=11)["_motor"]
    assert list(a.armazem.todos()) == list(b.armazem.todos())
    assert hash_estado(a.estado) == hash_estado(b.estado)


def test_replay_a_partir_de_arquivo(tmp_path):
    caminho = tmp_path / "era.jsonl"
    arq = ArquivoEventos(str(caminho))
    res = simular(5, semente=3, armazem=arq)
    arq.fechar()
    recarregado = ArquivoEventos(str(caminho))
    m = Motor.do_log(recarregado)
    assert hash_estado(m.estado) == res["hash_estado"]
    recarregado.fechar()


def test_replay_continua_a_era(tmp_path):
    """Parar no meio, refazer pelo log e continuar dá o mesmo resultado que rodar direto."""
    from arena.tempo import DIA

    direto = simular(4, semente=5, verificar_replay=False)["_motor"]
    caminho = tmp_path / "parcial.jsonl"
    arq = ArquivoEventos(str(caminho))
    parcial = simular(4, semente=5, armazem=arq, verificar_replay=False)["_motor"]
    arq.fechar()
    arq2 = ArquivoEventos(str(caminho))
    retomado = Motor.do_log(arq2)
    alvo = direto.agora + 2 * DIA
    direto.avancar_ate(alvo)
    retomado.avancar_ate(alvo)
    assert hash_estado(direto.estado) == hash_estado(retomado.estado)
    arq2.fechar()


def test_log_imutavel_em_memoria():
    m = simular(1, semente=1, verificar_replay=False)["_motor"]
    with pytest.raises(ValueError):
        m.armazem.anexar(dict(next(m.armazem.todos())))


def test_seq_por_reino_sem_buracos():
    m = simular(3, semente=2, verificar_replay=False)["_motor"]
    for r in m.estado["reinos"]:
        evs = m.armazem.eventos_do_reino(r, 0, 10_000)
        assert [e["seq"] for e in evs] == list(range(1, len(evs) + 1))
        assert all(e["visibilidade"] in ("privado", "parcial", "publico") for e in evs)
        # um reino não recebe eventos privados de outro
        outros = set(m.estado["reinos"]) - {r}
        assert not any(e["tipo"] == "tick_economico" and e["dados"]["reino"] in outros for e in evs)
