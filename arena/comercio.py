"""Caravanas e mercado das cidades livres (seção 8)."""

from __future__ import annotations

from . import aleatorio
from .acoes import Plano, acao, exigir
from .economia import capacidade, r3
from .militar import caminho_mais_rapido, tempo_trecho, trecho_entre
from .motor import tratador_agenda
from .nucleo import usar_id
from .redutor import agendar, informativo, redutor
from .regras import CAPACIDADE_CARAVANA, RECURSOS, TAXA_MERCADO
from .relacoes import em_guerra


def _rota_caravana(m, reino, origem, destino):
    estado = m.estado

    def permitido(pid):
        return not em_guerra(estado, reino, estado["provincias"][pid]["dono"])

    rota = caminho_mais_rapido(estado, origem, destino, permitido, m.params)
    exigir(rota is not None, "sem rota de caravana até o destino")
    total, atual = 0, origem
    for pid in rota:
        total += tempo_trecho(estado, pid, trecho_entre(estado, atual, pid), m.params, [])
        atual = pid
    return rota, total


def _carga(c) -> dict:
    exigir(isinstance(c, dict) and c, "carga vazia", codigo="formato_invalido")
    carga = {}
    for k, v in c.items():
        exigir(k in RECURSOS and float(v) > 0, f"recurso inválido: {k}", codigo="formato_invalido")
        carga[k] = float(v)
    exigir(sum(carga.values()) <= CAPACIDADE_CARAVANA, f"uma caravana leva até {CAPACIDADE_CARAVANA} unidades")
    return carga


def _somar(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in b.items():
        out[k] = out.get(k, 0) + v
    return out


# ---------------------------------------------------------------- caravana entre reinos


@acao("enviar_caravana")
def _v_caravana(m, reino, p):
    estado = m.estado
    origem = p.get("origem") or estado["reinos"][reino]["capital"]
    exigir(origem in estado["provincias"] and estado["provincias"][origem]["dono"] == reino, "origem precisa ser província própria", codigo="sem_permissao")
    destino = p["destino"]
    prov = estado["provincias"].get(destino)
    exigir(prov is not None and prov["dono"] in estado["reinos"] and prov["dono"] != reino, "destino precisa ser província de outro reino")
    carga = _carga(p["carga"])
    rota, total = _rota_caravana(m, reino, origem, destino)
    custos = _somar(carga, {"madeira": 20, "comida": len(rota)})
    car = m.novo_id("car", "car")

    def depois(m, ev):
        m.emitir("caravana_partiu", {"caravana": car, "reino": reino, "para": prov["dono"], "destino": destino, "caminho": rota,
                                     "carga": carga, "chegada_em": m.agora + total}, [reino, prov["dono"]], causa=ev["dados"]["acao_id"])

    return Plano(custos=custos, dados={"caravana": car}, depois=depois)


@redutor("caravana_partiu")
def _partiu(estado, ev):
    d = ev["dados"]
    usar_id(estado, "car", d["caravana"])
    estado["caravanas"][d["caravana"]] = {
        "id": d["caravana"], "reino": d["reino"], "tipo": "entrega", "para": d["para"], "destino": d["destino"],
        "caminho": d["caminho"], "carga": d["carga"], "chegada_em": d["chegada_em"], "oferta": None,
    }
    agendar(estado, ev, d["chegada_em"], "chegada_caravana", {"caravana": d["caravana"]})


@tratador_agenda("chegada_caravana")
def _chegada(m, item):
    estado = m.estado
    c = estado["caravanas"].get(item["dados"]["caravana"])
    if c is None:
        return
    carga = dict(c["carga"])
    for pid in c["caminho"]:
        p = estado["provincias"][pid]
        if p["tipo"] != "selvagem":
            continue
        if aleatorio.chance(estado["semente"], "bandidos", f"{c['id']}:{pid}", m.agora, 0.08):
            levado = {k: r3(v * 0.5) for k, v in carga.items()}
            carga = {k: r3(v - levado[k]) for k, v in carga.items()}
            m.emitir("caravana_atacada", {"caravana": c["id"], "provincia": pid, "levado": levado}, [c["reino"], c["para"]])
    if c["tipo"] == "entrega":
        m.emitir("caravana_chegou", {"caravana": c["id"], "reino": c["reino"], "para": c["para"], "destino": c["destino"], "carga": carga,
                                     "capacidade": capacidade(estado, c["para"], m.params)}, [c["reino"], c["para"]])
    else:
        m.emitir("oferta_retornou", {"caravana": c["id"], "oferta": c["oferta"], "reino": c["reino"], "carga": carga,
                                     "capacidade": capacidade(estado, c["reino"], m.params)}, [c["reino"]])


@redutor("caravana_atacada")
def _atacada(estado, ev):
    c = estado["caravanas"][ev["dados"]["caravana"]]
    for k, v in ev["dados"]["levado"].items():
        c["carga"][k] = r3(c["carga"][k] - v)


@redutor("caravana_chegou", "oferta_retornou")
def _chegou(estado, ev):
    d = ev["dados"]
    estado["caravanas"].pop(d["caravana"], None)
    para = d["para"] if ev["tipo"] == "caravana_chegou" else d["reino"]
    est = estado["reinos"][para]["estoque"]
    for k, v in d["carga"].items():
        est[k] = r3(est[k] + v if k == "ouro" else min(d["capacidade"], est[k] + v))


# ---------------------------------------------------------------- mercado


def preco(merc: dict, e: float) -> float:
    p = merc["P0"] * (merc["E0"] / max(1.0, e)) ** 0.7
    return min(4 * merc["P0"], max(0.25 * merc["P0"], p))


def executar_ordem(merc: dict, lado: str, quantidade: float, limite: float, ouro_disponivel: float = 0.0):
    """Executa unidade a unidade pelo preço marginal (aproxima a integral da seção 8.3).
    Devolve (unidades, ouro, novo_E)."""
    e = merc["E"]
    unidades = 0
    ouro = 0.0
    for _ in range(int(quantidade)):
        if lado == "vender":
            liquido = preco(merc, e + 0.5) * (1 - TAXA_MERCADO)
            if liquido < limite:
                break
            ouro += liquido
            e += 1
        else:
            bruto = preco(merc, e - 0.5) * (1 + TAXA_MERCADO)
            if bruto > limite or ouro + bruto > ouro_disponivel + 1e-9 or e <= 1:
                break
            ouro += bruto
            e -= 1
        unidades += 1
    return unidades, r3(ouro), r3(e)


@acao("ofertar_mercado")
def _v_ofertar(m, reino, p):
    estado = m.estado
    cidade = p["cidade"]
    exigir(cidade in estado["mercados"], "cidade livre desconhecida", codigo="formato_invalido")
    lado = p["lado"]
    exigir(lado in ("comprar", "vender"), "lado é 'comprar' ou 'vender'", codigo="formato_invalido")
    recurso = p["recurso"]
    exigir(recurso in estado["mercados"][cidade], f"o mercado não negocia {recurso}", codigo="formato_invalido")
    q = int(p["quantidade"])
    exigir(1 <= q <= CAPACIDADE_CARAVANA, f"quantidade de 1 a {CAPACIDADE_CARAVANA}", codigo="formato_invalido")
    limite = float(p["preco_limite"])
    exigir(limite > 0, "preco_limite precisa ser positivo", codigo="formato_invalido")
    origem = estado["reinos"][reino]["capital"]
    rota, total = _rota_caravana(m, reino, origem, cidade)
    if lado == "vender":
        carga = {recurso: float(q)}
    else:
        carga = {"ouro": r3(q * limite)}
    custos = _somar(carga, {"madeira": 20, "comida": len(rota)})
    car = m.novo_id("car", "car")
    ofe = m.novo_id("ofe", "ofe")

    def depois(m, ev):
        m.emitir("oferta_partiu", {"caravana": car, "oferta": ofe, "reino": reino, "cidade": cidade, "lado": lado, "recurso": recurso,
                                   "quantidade": q, "preco_limite": limite, "carga": carga, "caminho": rota, "chegada_em": m.agora + total,
                                   "volta_em_ms": total}, [reino], causa=ev["dados"]["acao_id"])

    return Plano(custos=custos, dados={"caravana": car, "oferta": ofe}, depois=depois)


@redutor("oferta_partiu")
def _oferta_partiu(estado, ev):
    d = ev["dados"]
    usar_id(estado, "car", d["caravana"])
    usar_id(estado, "ofe", d["oferta"])
    estado["caravanas"][d["caravana"]] = {
        "id": d["caravana"], "reino": d["reino"], "tipo": "mercado_ida", "para": None, "destino": d["cidade"],
        "caminho": d["caminho"], "carga": d["carga"], "chegada_em": d["chegada_em"], "oferta": d["oferta"],
        "ordem": {k: d[k] for k in ("lado", "recurso", "quantidade", "preco_limite", "volta_em_ms")},
    }
    agendar(estado, ev, d["chegada_em"], "oferta_no_mercado", {"caravana": d["caravana"]})


@tratador_agenda("oferta_no_mercado")
def _no_mercado(m, item):
    c = m.estado["caravanas"][item["dados"]["caravana"]]
    o = c["ordem"]
    merc = m.estado["mercados"][c["destino"]][o["recurso"]]
    if o["lado"] == "vender":
        disponivel = c["carga"].get(o["recurso"], 0)
        un, ouro, novo_e = executar_ordem(merc, "vender", min(o["quantidade"], disponivel), o["preco_limite"])
        volta = {"ouro": ouro}
        sobra = r3(disponivel - un)
        if sobra > 0:
            volta[o["recurso"]] = sobra
    else:
        ouro_levado = c["carga"].get("ouro", 0)
        un, ouro, novo_e = executar_ordem(merc, "comprar", o["quantidade"], o["preco_limite"], ouro_levado)
        volta = {o["recurso"]: float(un)}
        sobra = r3(ouro_levado - ouro)
        if sobra > 0:
            volta["ouro"] = sobra
    tipo = "oferta_executada" if un > 0 else "oferta_expirada"
    m.emitir(tipo, {"oferta": c["oferta"], "caravana": c["id"], "cidade": c["destino"], "lado": o["lado"], "recurso": o["recurso"],
                    "unidades": un, "ouro": ouro, "preco_medio": r3(ouro / un) if un else None, "E": novo_e, "volta": volta,
                    "chegada_volta": m.agora + o["volta_em_ms"]}, [c["reino"]])


@redutor("oferta_executada", "oferta_expirada")
def _executada(estado, ev):
    d = ev["dados"]
    estado["mercados"][d["cidade"]][d["recurso"]]["E"] = d["E"]
    c = estado["caravanas"][d["caravana"]]
    c["tipo"] = "mercado_volta"
    c["carga"] = d["volta"]
    c["caminho"] = list(reversed(c["caminho"][:-1])) + [estado["reinos"][c["reino"]]["capital"]]
    c["chegada_em"] = d["chegada_volta"]
    agendar(estado, ev, d["chegada_volta"], "chegada_caravana", {"caravana": c["id"]})


informativo()
