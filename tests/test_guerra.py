"""Declaração de guerra, movimento, batalha e ocupação (seção 10)."""

from arena.tempo import HORA
from conftest import INICIO, acao, eventos, ok


def exercito(m, reino):
    return sorted(e for e, x in m.estado["exercitos"].items() if x["reino"] == reino)[0]


def preparar_infantaria(m, reino):
    """Separa as 2 milícias (que não saem do reino) e devolve o exército de infantaria."""
    eid = exercito(m, reino)
    ok(m, reino, acao("dividir_exercito", exercito=eid, companhias=[0, 1]))
    return eid


def test_reino_neutro_e_cidade_livre_bloqueiam_movimento(motor):
    m = motor
    eid = preparar_infantaria(m, "reino_c")
    st, c = m.submeter("reino_c", acao("mover_exercito", exercito=eid, destino="prov_b3"))
    assert st == 422 and c["erro"]["codigo"] == "precondicao_falhou"
    st, c = m.submeter("reino_c", acao("mover_exercito", exercito=eid, destino="cid_portolivre", postura="ofensiva"))
    assert st == 422
    ok(m, "reino_c", acao("mover_exercito", exercito=eid, destino="cid_portolivre", postura="defensiva"))


def test_milicia_nao_sai_do_reino(motor):
    m = motor
    eid = exercito(m, "reino_c")
    st, c = m.submeter("reino_c", acao("mover_exercito", exercito=eid, destino="prov_wb"))
    assert st == 422


def test_guerra_vigora_em_12h_comprimidas_e_permite_ocupar(motor):
    m = motor
    eid = preparar_infantaria(m, "reino_c")
    ok(m, "reino_c", acao("declarar_guerra", alvo="reino_b"))
    assert m.estado["guerras"]["gue_0001"]["estado"] == "declarada"
    m.avancar_ate(INICIO + 3 * HORA)
    assert m.estado["guerras"]["gue_0001"]["estado"] == "ativa"
    r = ok(m, "reino_c", acao("mover_exercito", exercito=eid, destino="prov_b3", postura="ofensiva"))
    # c1 -> c2 (floresta 3 h) -> wb (pântano 4,5 h) -> b3 (colina 3 h)
    assert m.estado["exercitos"][eid]["movimento"]["caminho"] == ["prov_c2", "prov_wb", "prov_b3"]
    assert r["conclusao_prevista"] == "2026-12-01T13:30:00.000Z"
    m.avancar_ate(INICIO + 13 * HORA + 30 * 60_000)
    assert m.estado["exercitos"][eid]["provincia"] == "prov_b3"
    # sem defensores e sem muralha: ocupa depois de 12 h comprimidas (3 h), avaliado no tick
    m.avancar_ate(INICIO + 17 * HORA)
    assert m.estado["provincias"]["prov_b3"]["ocupante"] == "reino_c"
    assert eventos(m, "provincia_ocupada")


def test_batalha_com_perdas_e_fim(motor):
    m = motor
    eid = preparar_infantaria(m, "reino_c")
    ok(m, "reino_c", acao("declarar_guerra", alvo="reino_b"))
    m.avancar_ate(INICIO + 3 * HORA)
    ok(m, "reino_c", acao("mover_exercito", exercito=eid, destino="prov_b3", postura="ofensiva"))
    m.avancar_ate(INICIO + 14 * HORA)
    # B manda a guarnição da capital (2 milícias + 1 infantaria) para b3
    defensor = exercito(m, "reino_b")
    ok(m, "reino_b", acao("mover_exercito", exercito=defensor, destino="prov_b3", postura="ofensiva"))
    m.avancar_ate(INICIO + 40 * HORA)
    iniciadas = eventos(m, "batalha_iniciada")
    assert len(iniciadas) == 1
    rodadas = eventos(m, "batalha_rodada")
    assert rodadas and any(r["dados"]["exercitos"][x]["perdas"] > 0 for r in rodadas for x in r["dados"]["exercitos"])
    assert eventos(m, "batalha_encerrada")
    assert not m.estado["batalhas"]


def test_nao_agressao_bloqueia_declaracao(motor):
    m = motor
    ok(m, "reino_a", acao("propor_tratado", partes=["reino_a", "reino_b"], duracao_dias=30, clausulas=[{"tipo": "nao_agressao"}]))
    ok(m, "reino_b", acao("aceitar_tratado", tratado="tra_0001"))
    assert m.estado["tratados"]["tra_0001"]["status"] == "ativo"
    st, c = m.submeter("reino_a", acao("declarar_guerra", alvo="reino_b"))
    assert c["erro"]["codigo"] == "proibido_por_tratado"
    ok(m, "reino_a", acao("declarar_guerra", alvo="reino_b", romper_tratados=True))
    assert m.estado["tratados"]["tra_0001"]["status"] == "rompido"
    assert m.estado["reinos"]["reino_a"]["reputacao"] == 30


def test_paz_por_tratado_encerra_guerra_e_libera_provincia(motor):
    m = motor
    eid = preparar_infantaria(m, "reino_c")
    ok(m, "reino_c", acao("declarar_guerra", alvo="reino_b"))
    m.avancar_ate(INICIO + 3 * HORA)
    ok(m, "reino_c", acao("mover_exercito", exercito=eid, destino="prov_b3", postura="ofensiva"))
    m.avancar_ate(INICIO + 17 * HORA)
    assert m.estado["provincias"]["prov_b3"]["ocupante"] == "reino_c"
    ok(m, "reino_b", acao("propor_paz", alvo="reino_c"))
    ok(m, "reino_c", acao("aceitar_tratado", tratado="tra_0001"))
    assert m.estado["guerras"]["gue_0001"]["estado"] == "encerrada"
    assert m.estado["provincias"]["prov_b3"]["ocupante"] is None
    assert m.estado["exercitos"][eid]["movimento"] is not None  # volta para casa
