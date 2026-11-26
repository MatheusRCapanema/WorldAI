"""Cota, validação, idempotência e ciclo de vida das ações (seção 7)."""

from arena.tempo import HORA
from conftest import INICIO, acao, eventos, ok


def test_cota_e_rejeicao_nao_gasta(motor):
    m = motor
    st, corpo = m.submeter("reino_a", acao("construir", provincia="prov_b1", construcao="fazenda"))
    assert st == 422 and corpo["erro"]["codigo"] == "sem_permissao"
    assert corpo["cota_restante"]["ordens"] == 200
    ok(m, "reino_a", acao("construir", provincia="prov_a1", construcao="armazem"))
    assert m.estado["reinos"]["reino_a"]["cota"]["ordens"] == 199


def test_cota_esgotada(motor):
    m = motor
    m.estado["reinos"]["reino_a"]["cota"]["ordens"] = 0  # atalho de teste
    st, corpo = m.submeter("reino_a", acao("definir_impostos", aliquota=10))
    assert st == 422 and corpo["erro"]["codigo"] == "cota_esgotada"


def test_idempotencia(motor):
    m = motor
    a = acao("construir", "abc", provincia="prov_a1", construcao="armazem")
    r1 = ok(m, "reino_a", a)
    r2 = ok(m, "reino_a", a)
    assert r1 == r2
    assert m.estado["reinos"]["reino_a"]["cota"]["ordens"] == 199
    assert len(eventos(m, "acao_aceita")) == 1


def test_recursos_insuficientes_tem_detalhes(motor):
    st, corpo = motor.submeter("reino_a", acao("construir", provincia="prov_a1", construcao="torre_de_eter"))
    assert corpo["erro"]["codigo"] == "acao_desconhecida"
    for _ in range(5):
        motor.submeter("reino_a", acao("construir", provincia="prov_a2", construcao="armazem"))
    st, corpo = motor.submeter("reino_a", acao("construir", provincia="prov_a3", construcao="muralha"))
    assert st == 422 and corpo["erro"]["codigo"] == "recursos_insuficientes"
    assert "madeira" in corpo["erro"]["detalhes"]


def test_construcao_conclui_no_prazo_e_aumenta_capacidade(motor):
    m = motor
    from arena.economia import capacidade

    r = ok(m, "reino_a", acao("construir", provincia="prov_a1", construcao="armazem"))
    assert r["conclusao_prevista"] == "2026-12-01T06:00:00.000Z"  # 1 dia / fator 4
    m.avancar_ate(INICIO + 6 * HORA - 1)
    assert capacidade(m.estado, "reino_a", m.params) == 2000
    m.avancar_ate(INICIO + 6 * HORA)
    assert capacidade(m.estado, "reino_a", m.params) == 3000
    assert eventos(m, "construcao_concluida")


def test_melhorar_custa_n_vezes(motor_farto):
    m = motor_farto
    fazenda = [c for c in m.estado["provincias"]["prov_a2"]["construcoes"].values() if c["tipo"] == "fazenda"][0]
    r = ok(m, "reino_a", acao("melhorar", provincia="prov_a2", construcao=fazenda["id"]))
    assert r["custos"] == {"madeira": 120, "ouro": 40}
    m.avancar_ate(INICIO + 12 * HORA)
    assert m.estado["provincias"]["prov_a2"]["construcoes"][fazenda["id"]]["nivel"] == 2


def test_cancelar_devolve_metade(motor):
    m = motor
    r = ok(m, "reino_a", acao("construir", provincia="prov_a1", construcao="armazem"))
    madeira = m.estado["reinos"]["reino_a"]["estoque"]["madeira"]
    ok(m, "reino_a", acao("cancelar_acao", acao=r["acao_id"]))
    assert m.estado["reinos"]["reino_a"]["estoque"]["madeira"] == madeira + 50
    m.avancar_ate(INICIO + 7 * HORA)
    assert not eventos(m, "construcao_concluida")
    assert len(m.estado["provincias"]["prov_a1"]["construcoes"]) == 2


def test_formatos_invalidos(motor):
    st, c = motor.submeter("reino_a", acao("alocar_trabalho", provincia="prov_a1", setores={"agricultura": 90, "madeira": 20}))
    assert c["erro"]["codigo"] == "formato_invalido"
    st, c = motor.submeter("reino_a", {"parametros": {}})
    assert c["erro"]["codigo"] == "formato_invalido"
    st, c = motor.submeter("reino_a", acao("colonizar", provincia="prov_wa"))
    assert c["erro"]["codigo"] == "acao_desconhecida"
    st, c = motor.submeter("reino_a", acao("definir_impostos", aliquota=80))
    assert c["erro"]["codigo"] == "formato_invalido"


def test_lei_vale_depois_de_24h_comprimidas(motor):
    m = motor
    ok(m, "reino_a", acao("promulgar_lei", lei="festas_publicas"))
    from arena.economia import leis_ativas

    assert leis_ativas(m.estado["reinos"]["reino_a"], m.agora) == []
    m.avancar_ate(INICIO + 6 * HORA)
    assert leis_ativas(m.estado["reinos"]["reino_a"], m.agora) == ["festas_publicas"]
    st, c = m.submeter("reino_a", acao("promulgar_lei", lei="festas_publicas"))
    assert c["erro"]["codigo"] == "precondicao_falhou"


def test_recrutamento_tira_populacao_e_cria_companhia(motor):
    m = motor
    pop = m.estado["provincias"]["prov_a1"]["populacao"]
    r = ok(m, "reino_a", acao("recrutar", provincia="prov_a1", tipo="infantaria", quantidade=2))
    assert r["cota_restante"]["ordens"] == 198
    assert m.estado["provincias"]["prov_a1"]["populacao"] == pop - 200
    m.avancar_ate(INICIO + 12 * HORA)
    exe = [e for e in m.estado["exercitos"].values() if e["reino"] == "reino_a"]
    assert sum(len(e["companhias"]) for e in exe) == 5
    st, c = m.submeter("reino_a", acao("recrutar", provincia="prov_a1", tipo="cavalaria"))
    assert c["erro"]["codigo"] == "precondicao_falhou"  # exige quartel 2
