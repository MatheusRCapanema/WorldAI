"""Fórmulas de produção, consumo, safra e felicidade (seções 4 e 5)."""

from arena.economia import faixa_felicidade, mult_felicidade
from arena.tempo import DIA, HORA
from conftest import INICIO, acao, eventos, ok


def test_primeira_colheita_bate_com_a_formula(motor_farto):
    m = motor_farto
    m.avancar_ate(INICIO + m.params.horas_safra * HORA)
    colheitas = {e["dados"]["provincia"]: e["dados"]["comida"] for e in eventos(m, "safra_colhida")}
    # capital de planície: 2.500 pessoas, 60% no campo, 1 fazenda: 15 * 1,5 * 7 * 1,3 * 1,2 = 2.457
    # a população cresce um pouco ao longo do ciclo, por isso a faixa de 5%
    assert 2457 <= colheitas["prov_a1"] <= 2457 * 1.05
    # floresta: 2.000 pessoas, 60%, fazenda: 12 * 105 * 0,8 * 1,2 = 1.209,6
    assert 1209.6 <= colheitas["prov_a2"] <= 1209.6 * 1.05


def test_safra_dura_42_horas_na_era_de_teste(motor_farto):
    assert motor_farto.params.horas_safra == 42
    motor_farto.avancar_ate(INICIO + 41 * HORA)
    assert not eventos(motor_farto, "safra_colhida")
    motor_farto.avancar_ate(INICIO + 42 * HORA)
    assert len(eventos(motor_farto, "safra_colhida")) == 9


def test_consumo_de_comida_por_hora(motor):
    m = motor
    m.avancar_ate(INICIO + HORA)
    tick = [e for e in eventos(m, "tick_economico") if e["dados"]["reino"] == "reino_a"][0]
    # 6.500 civis + 300 soldados, 1 comida por 10 por dia, fator 4, 1/24 por tick
    consumo = (6500 + 300) / 10 * 4 / 24
    esperado = 2000 + tick["dados"]["producao"]["comida"] - consumo
    assert abs(tick["dados"]["estoque"]["comida"] - esperado) < 0.01


def test_fome_derruba_felicidade(motor):
    m = motor
    m.avancar_ate(INICIO + 36 * HORA)
    p = m.estado["provincias"]["prov_a1"]
    assert m.estado["reinos"]["reino_a"]["estoque"]["comida"] == 0
    assert p["felicidade"] < 40
    assert eventos(m, "deficit")


def test_faixas_de_felicidade():
    assert mult_felicidade(75) == 1.1 and mult_felicidade(50) == 1.0 and mult_felicidade(30) == 0.8
    assert faixa_felicidade(85) == "alta" and faixa_felicidade(10) == "critica"


def test_impostos_entram_no_ouro(motor_farto):
    m = motor_farto
    ok(m, "reino_a", acao("definir_impostos", aliquota=40))
    antes = m.estado["reinos"]["reino_a"]["estoque"]["ouro"]
    m.avancar_ate(INICIO + HORA)
    t = [e for e in eventos(m, "tick_economico") if e["dados"]["reino"] == "reino_a"][-1]
    # imposto por tick = pop * 0,05 * 0,40 * (1 + 0,15 * mercados) * 4/24
    imposto = (2500 * 0.05 * 0.4 * 1.15 + 4000 * 0.05 * 0.4) * 4 / 24
    assert t["dados"]["producao"]["ouro"] > imposto  # imposto mais ofícios
    assert m.estado["reinos"]["reino_a"]["estoque"]["ouro"] > antes


def test_virada_do_dia_renova_cota_e_aplica_deterioracao(motor_farto):
    m = motor_farto
    ok(m, "reino_a", acao("definir_impostos", aliquota=10))
    assert m.estado["reinos"]["reino_a"]["cota"]["ordens"] == 199
    m.avancar_ate(INICIO + DIA)
    assert m.estado["reinos"]["reino_a"]["cota"]["ordens"] == 200
    v = [e for e in eventos(m, "virada_reino") if e["dados"]["reino"] == "reino_a"][0]
    assert v["dados"]["comida_deteriorada"] > 0
    assert v["dados"]["manutencao_paga"] == (1 + 2 + 1 + 1) * 4  # fazendas e mercado, fator 4


def test_transicao_de_alocacao_e_linear(motor):
    m = motor
    from arena.economia import alocacao_efetiva

    ok(m, "reino_a", acao("alocar_trabalho", provincia="prov_a1", setores={"agricultura": 40, "madeira": 35, "oficios": 15, "mineracao": 10}))
    p = m.estado["provincias"]["prov_a1"]
    meio = alocacao_efetiva(p, INICIO + 3 * HORA, m.params)  # 24 h comprimidas = 6 h
    assert abs(meio["agricultura"] - 50) < 1e-9 and abs(meio["madeira"] - 25) < 1e-9
    assert alocacao_efetiva(p, INICIO + 6 * HORA, m.params)["agricultura"] == 40
