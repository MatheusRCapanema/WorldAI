"""API mínima em modo de relógio manual."""

import pytest
from fastapi.testclient import TestClient

from arena.api import Relogio, Servidor, criar_app
from arena.motor import Motor
from conftest import INICIO

ADMIN = {"Authorization": "Bearer dev-admin"}
A = {"Authorization": "Bearer dev-reino_a"}


@pytest.fixture
def cliente():
    m = Motor.nova_era(9, INICIO)
    srv = Servidor(m, Relogio("manual", INICIO), {f"dev-{r}": r for r in m.estado["reinos"]}, "dev-admin", ["reino_b", "reino_c"])
    with TestClient(criar_app(srv)) as c:
        yield c


def test_autenticacao(cliente):
    assert cliente.get("/v1/estado").status_code == 401
    assert cliente.get("/v1/estado", headers={"Authorization": "Bearer errado"}).status_code == 401


def test_enviar_acao_e_ler_eventos(cliente):
    corpo = {"chave_idempotencia": "x1", "tipo": "construir", "parametros": {"provincia": "prov_a1", "construcao": "armazem"}}
    r = cliente.post("/v1/acoes", headers=A, json=corpo)
    assert r.status_code == 202 and r.json()["status"] == "aceita"
    acao_id = r.json()["acao_id"]
    assert cliente.post("/v1/acoes", headers=A, json=corpo).json()["acao_id"] == acao_id
    r = cliente.post("/v1/acoes", headers=A, json={"tipo": "construir", "parametros": {"provincia": "prov_b1", "construcao": "fazenda"}})
    assert r.status_code == 422 and r.json()["erro"]["codigo"] == "sem_permissao"
    assert cliente.get(f"/v1/acoes/{acao_id}", headers=A).json()["status"] == "em_andamento"
    cliente.post("/admin/avancar?horas=8", headers=ADMIN)
    assert cliente.get(f"/v1/acoes/{acao_id}", headers=A).json()["status"] == "concluida"
    evs = cliente.get("/v1/eventos?desde=0", headers=A).json()["eventos"]
    tipos = [e["tipo"] for e in evs]
    assert "construcao_concluida" in tipos and tipos[0] == "era_iniciada"
    seqs = [e["seq"] for e in evs]
    assert seqs == list(range(1, len(seqs) + 1))
    depois = cliente.get(f"/v1/eventos?desde={seqs[-3]}", headers=A).json()["eventos"]
    assert [e["seq"] for e in depois] == seqs[-2:]


def test_lote_de_acoes(cliente):
    lote = {"acoes": [
        {"tipo": "definir_impostos", "parametros": {"aliquota": 20}},
        {"tipo": "definir_impostos", "parametros": {"aliquota": 25}},
    ]}
    res = cliente.post("/v1/acoes", headers=A, json=lote).json()["resultados"]
    assert res[0]["http"] == 202 and res[1]["http"] == 422  # 1 mudança a cada 24 h


def test_estado_mundo_regras_cota(cliente):
    e = cliente.get("/v1/estado", headers=A).json()
    assert e["reino"]["id"] == "reino_a" and len(e["provincias"]) == 3
    assert all(p["dono"] != "reino_a" for p in e["visiveis"])
    assert cliente.get("/v1/cota", headers=A).json()["ordens"] == 200
    mundo = cliente.get("/v1/mundo").json()
    assert len(mundo["reinos"]) == 3
    assert cliente.get("/v1/regras").json()["versao"] == "0.2"


def test_bots_e_verificacao_do_log(cliente):
    cliente.post("/admin/avancar?horas=72", headers=ADMIN)
    mundo = cliente.get("/v1/mundo").json()
    assert mundo["dia"] == 4
    v = cliente.get("/admin/verificar", headers=ADMIN).json()
    assert v["identico"] is True


def test_limite_de_taxa(cliente):
    codigos = [cliente.get("/v1/cota", headers=A).status_code for _ in range(15)]
    assert 429 in codigos
