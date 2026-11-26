"""Tratados, mensagens e mercado (seções 8 e 9)."""

from arena.comercio import executar_ordem, preco
from arena.tempo import HORA
from conftest import INICIO, acao, eventos, ok


def test_pagamento_unico_com_taxa_de_transporte(motor):
    m = motor
    ok(m, "reino_a", acao("propor_tratado", partes=["reino_a", "reino_b"], duracao_dias=10,
                          clausulas=[{"tipo": "pagamento_unico", "de": "reino_a", "para": "reino_b", "recursos": {"ouro": 100}}]))
    ouro_b = m.estado["reinos"]["reino_b"]["estoque"]["ouro"]
    ok(m, "reino_b", acao("aceitar_tratado", tratado="tra_0001"))
    assert m.estado["reinos"]["reino_b"]["estoque"]["ouro"] == ouro_b + 90


def test_proposta_expira_em_48h_comprimidas(motor):
    m = motor
    ok(m, "reino_a", acao("propor_tratado", partes=["reino_a", "reino_c"], clausulas=[{"tipo": "nao_agressao"}]))
    m.avancar_ate(INICIO + 12 * HORA)
    assert m.estado["tratados"]["tra_0001"]["status"] == "expirado"
    st, c = m.submeter("reino_c", acao("aceitar_tratado", tratado="tra_0001"))
    assert st == 422


def test_pagamento_periodico_e_conclusao(motor):
    m = motor
    ok(m, "reino_a", acao("propor_tratado", partes=["reino_a", "reino_b"], duracao_dias=3,
                          clausulas=[{"tipo": "pagamento_periodico", "de": "reino_b", "para": "reino_a", "recursos": {"ouro": 10}, "a_cada_dias": 1}]))
    ok(m, "reino_b", acao("aceitar_tratado", tratado="tra_0001"))
    m.avancar_ate(INICIO + 19 * HORA)
    assert len(eventos(m, "tratado_pagamento")) >= 2
    assert m.estado["tratados"]["tra_0001"]["status"] == "concluido"
    assert m.estado["reinos"]["reino_a"]["reputacao"] > 50


def test_tregua_nao_pode_ser_rompida(motor):
    m = motor
    ok(m, "reino_a", acao("propor_tratado", partes=["reino_a", "reino_b"], clausulas=[{"tipo": "tregua", "dias": 10}]))
    ok(m, "reino_b", acao("aceitar_tratado", tratado="tra_0001"))
    st, c = m.submeter("reino_a", acao("romper_tratado", tratado="tra_0001"))
    assert c["erro"]["codigo"] == "proibido_por_tratado"
    st, c = m.submeter("reino_a", acao("declarar_guerra", alvo="reino_b"))
    assert c["erro"]["codigo"] == "proibido_por_tratado"


def test_mensagem_privada_so_para_destinatarios(motor):
    m = motor
    ok(m, "reino_a", acao("enviar_mensagem", para=["reino_b"], texto="Proponho paz e uma rota comum."))
    ev = eventos(m, "mensagem_recebida")[0]
    assert ev["visivel_para"] == ["reino_a", "reino_b"]
    assert m.estado["reinos"]["reino_a"]["cota"]["mensagens"] == 49
    assert not [e for e in m.armazem.eventos_do_reino("reino_c", 0, 1000) if e["tipo"] == "mensagem_recebida"]


def test_formula_de_preco_do_mercado():
    merc = {"P0": 0.8, "E0": 10000.0, "E": 10000.0}
    assert preco(merc, 10000) == 0.8
    assert preco(merc, 1) == 3.2  # teto de 4 x P0
    un, ouro, novo_e = executar_ordem(merc, "vender", 400, 0.5)
    assert un == 400 and novo_e == 10400 and ouro < 400 * 0.8 * 0.95
    un, ouro, novo_e = executar_ordem(merc, "comprar", 400, 10.0, ouro_disponivel=10_000)
    assert un == 400 and novo_e == 9600 and ouro > 400 * 0.8 * 1.05


def test_venda_no_mercado_ida_e_volta(motor):
    m = motor
    ouro = m.estado["reinos"]["reino_a"]["estoque"]["ouro"]
    ok(m, "reino_a", acao("ofertar_mercado", cidade="cid_portolivre", lado="vender", recurso="madeira", quantidade=300, preco_limite=0.5))
    m.avancar_ate(INICIO + 24 * HORA)
    ex = eventos(m, "oferta_executada")
    assert ex and ex[0]["dados"]["unidades"] == 300
    assert m.estado["mercados"]["cid_portolivre"]["madeira"]["E"] > 10000
    assert eventos(m, "oferta_retornou")
    assert m.estado["reinos"]["reino_a"]["estoque"]["ouro"] > ouro


def test_caravana_sem_comida_paga_em_ouro():
    """Regras 0.2: sem comida para a viagem, a caravana cobra 2 ouro por trecho."""
    from arena.motor import Motor
    from arena.regras import Parametros

    m = Motor.nova_era(7, INICIO, Parametros(inicio_estoque={"comida": 0.0, "madeira": 600.0, "ferro": 150.0, "ouro": 800.0}))
    r = ok(m, "reino_a", acao("ofertar_mercado", cidade="cid_portolivre", lado="comprar", recurso="comida", quantidade=200, preco_limite=1.0))
    # a1 -> a3 -> wa -> Porto Livre: 3 trechos
    assert r["custos"] == {"ouro": 200 + 6, "madeira": 20}


def test_celeiro_aumenta_teto_de_comida(motor_farto):
    from arena.economia import capacidade

    m = motor_farto
    ok(m, "reino_a", acao("construir", provincia="prov_a1", construcao="celeiro"))
    m.avancar_ate(INICIO + 6 * HORA)
    cap = capacidade(m.estado, "reino_a", m.params)
    assert cap["comida"] == cap["madeira"] + 1000
