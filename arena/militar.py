"""Guerra: recrutamento, movimento, batalha, cerco, ocupação e saque (seção 10)."""

from __future__ import annotations

import heapq

from . import aleatorio
from .acoes import Plano, acao, ao_aplicar, ao_cancelar, ao_concluir, concluir_ok, exigir, falhar, provincia_propria
from .economia import leis_ativas, nivel_ativo, r3
from .mapa import vizinhos
from .motor import Rejeicao, tratador_agenda
from .nucleo import usar_id
from .redutor import agendar, informativo, redutor
from .regras import BIOMAS, SOLDADOS_POR_COMPANHIA, UNIDADES
from .relacoes import em_guerra, guerra_entre, tratados_ativos_entre, tem_clausula, tregua_ativa
from .tempo import HORA

POSTURAS = ("ofensiva", "defensiva", "evitar_combate")


# ---------------------------------------------------------------- leituras


def soldados(ex: dict) -> int:
    return sum(c["soldados"] for c in ex["companhias"])


def parado(ex: dict) -> bool:
    return ex["movimento"] is None


def exercitos_em(estado: dict, pid: str) -> list[dict]:
    return [e for _, e in sorted(estado["exercitos"].items()) if e["provincia"] == pid and parado(e)]


def hostis_em(estado: dict, pid: str, reino: str) -> list[dict]:
    return [e for e in exercitos_em(estado, pid) if em_guerra(estado, e["reino"], reino)]


def muralha_intacta(prov: dict) -> bool:
    return nivel_ativo(prov, "muralha") > 0 and prov["muralha_integridade"] > 0


def pode_entrar(estado: dict, reino: str, pid: str, postura: str, so_no_reino: bool) -> bool:
    p = estado["provincias"][pid]
    if so_no_reino:
        return p["dono"] == reino
    if p["tipo"] == "selvagem":
        return True
    if p["tipo"] == "cidade_livre":
        return postura != "ofensiva"  # seção 20.1: cidades livres protegidas
    if p["dono"] == reino or p["dono"] is None:
        return True
    return em_guerra(estado, reino, p["dono"])


def tempo_trecho(estado: dict, para: str, trecho: dict, params, companhias: list[dict]) -> int:
    p = estado["provincias"][para]
    h = BIOMAS[p["bioma"]]["travessia"]
    if trecho["tipo"] == "estrada":
        h = max(6, h * 0.5)
    if estado["estacao"] == "inverno" and p["bioma"] in ("colina", "montanha", "pantano"):
        h *= 1.5
    if companhias and all(c["tipo"] == "cavalaria" for c in companhias) and p["bioma"] == "planicie":
        h *= 0.7
    return params.duracao(h)


def caminho_mais_rapido(estado, origem, destino, permitido, params, companhias=()) -> list[str] | None:
    """Dijkstra no grafo de províncias. Devolve a lista sem a origem."""
    dist = {origem: 0}
    ant: dict[str, str] = {}
    fila = [(0, origem)]
    while fila:
        d, u = heapq.heappop(fila)
        if u == destino:
            break
        if d > dist[u]:
            continue
        for v, tr in vizinhos(estado, u):
            if not permitido(v):
                continue
            nd = d + tempo_trecho(estado, v, tr, params, list(companhias))
            if nd < dist.get(v, 1 << 62):
                dist[v] = nd
                ant[v] = u
                heapq.heappush(fila, (nd, v))
    if destino not in dist:
        return None
    rota = [destino]
    while rota[-1] != origem:
        rota.append(ant[rota[-1]])
    return list(reversed(rota))[1:]


def trecho_entre(estado, a, b) -> dict | None:
    for v, tr in vizinhos(estado, a):
        if v == b:
            return tr
    return None


def exercito_proprio(m, reino, eid) -> dict:
    e = m.estado["exercitos"].get(eid)
    if e is None or e["reino"] != reino:
        raise Rejeicao("sem_permissao", "exército não encontrado")
    return e


def _so_no_reino(ex) -> bool:
    return any(UNIDADES[c["tipo"]].so_no_reino for c in ex["companhias"])


def visiveis_movimento(estado, pid, *reinos) -> list[str]:
    """Dono do exército, dono da província e donos de províncias vizinhas (visão parcial)."""
    vis = {r for r in reinos if r}
    p = estado["provincias"][pid]
    if p["dono"]:
        vis.add(p["dono"])
    for v, _ in vizinhos(estado, pid):
        d = estado["provincias"][v]["dono"]
        if d in estado["reinos"]:
            vis.add(d)
    return sorted(r for r in vis if r in estado["reinos"])


# ---------------------------------------------------------------- recrutamento


@acao("recrutar", custo=lambda p: int(p.get("quantidade", 1)), cancelavel=True)
def _v_recrutar(m, reino, p):
    prov = provincia_propria(m, reino, p["provincia"])
    tipo = p["tipo"]
    q = int(p.get("quantidade", 1))
    exigir(tipo in UNIDADES, f"tipo desconhecido: {tipo}", codigo="formato_invalido")
    exigir(1 <= q <= 20, "quantidade de 1 a 20 companhias", codigo="formato_invalido")
    exigir(prov["ocupante"] is None and prov["revolta_desde"] is None, "província ocupada ou em revolta")
    u = UNIDADES[tipo]
    quartel = nivel_ativo(prov, "quartel")
    exigir(quartel >= u.quartel, f"exige quartel nível {u.quartel}")
    pessoas = SOLDADOS_POR_COMPANHIA * q
    cedidos = prov.get("cedidos", 0)
    limite = 0.2 * (prov["populacao"] + cedidos)
    exigir(cedidos + pessoas <= limite, "a província só cede até 20% da população", {"limite": int(limite), "cedidos": cedidos})
    custos = {}
    leis = leis_ativas(m.estado["reinos"][reino], m.agora)
    for k, v in u.custo.items():
        if k == "ouro" and "servico_militar" in leis:
            v *= 0.7
        custos[k] = v * q
    horas = u.treino_h * (0.75 if quartel else 1.0)
    return Plano(custos=custos, duracao=m.params.duracao(horas), dados={"pessoas": pessoas})


@ao_aplicar("recrutar")
def _a_recrutar(estado, ev):
    d = ev["dados"]
    prov = estado["provincias"][d["parametros"]["provincia"]]
    prov["populacao"] = r3(prov["populacao"] - d["extra"]["pessoas"])
    prov["cedidos"] = prov.get("cedidos", 0) + d["extra"]["pessoas"]


@ao_cancelar("recrutar")
def _x_recrutar(estado, a):
    prov = estado["provincias"][a["parametros"]["provincia"]]
    prov["populacao"] = r3(prov["populacao"] + a["extra"]["pessoas"])
    prov["cedidos"] = prov.get("cedidos", 0) - a["extra"]["pessoas"]


@ao_concluir("recrutar")
def _c_recrutar(m, a):
    pid = a["parametros"]["provincia"]
    alvo = None
    for e in exercitos_em(m.estado, pid):
        if e["reino"] == a["reino"] and e["batalha"] is None:
            alvo = e["id"]
            break
    novo = alvo is None
    eid = alvo or m.novo_id("exe", "exe")
    q = int(a["parametros"].get("quantidade", 1))
    concluir_ok(
        m, a, "companhias_treinadas",
        {"exercito": eid, "novo": novo, "provincia": pid, "reino": a["reino"],
         "companhias": [{"tipo": a["parametros"]["tipo"], "soldados": SOLDADOS_POR_COMPANHIA}] * q},
    )


@redutor("companhias_treinadas")
def _treinadas(estado, ev):
    d = ev["dados"]
    if d["novo"]:
        usar_id(estado, "exe", d["exercito"])
        estado["exercitos"][d["exercito"]] = {
            "id": d["exercito"], "reino": d["reino"], "provincia": d["provincia"], "companhias": [],
            "moral": 100.0, "postura": "defensiva", "movimento": None, "batalha": None, "veio_de": None,
            "chegou_em": ev["ocorrido_em"], "acao": None,
        }
    estado["exercitos"][d["exercito"]]["companhias"].extend(dict(c) for c in d["companhias"])


@acao("dispensar")
def _v_dispensar(m, reino, p):
    e = exercito_proprio(m, reino, p["exercito"])
    prov = m.estado["provincias"][e["provincia"]]
    exigir(prov["dono"] == reino and parado(e) and e["batalha"] is None, "exército precisa estar parado numa província própria")
    return Plano(dados={"pessoas": soldados(e), "provincia": e["provincia"]})


@ao_aplicar("dispensar")
def _a_dispensar(estado, ev):
    d = ev["dados"]
    estado["exercitos"].pop(d["parametros"]["exercito"])
    prov = estado["provincias"][d["extra"]["provincia"]]
    prov["populacao"] = r3(prov["populacao"] + d["extra"]["pessoas"])
    prov["cedidos"] = max(0, prov.get("cedidos", 0) - d["extra"]["pessoas"])


@acao("formar_exercito")
def _v_formar(m, reino, p):
    ids = list(p["exercitos"])
    exigir(len(ids) >= 2, "informe 2 ou mais exércitos", codigo="formato_invalido")
    exs = [exercito_proprio(m, reino, i) for i in ids]
    exigir(len({e["provincia"] for e in exs}) == 1, "exércitos em províncias diferentes")
    exigir(all(parado(e) and e["batalha"] is None for e in exs), "exércitos precisam estar parados e fora de batalha")
    total = sum(soldados(e) for e in exs)
    moral = sum(e["moral"] * soldados(e) for e in exs) / max(1, total)
    return Plano(dados={"moral": r3(moral)})


@ao_aplicar("formar_exercito")
def _a_formar(estado, ev):
    ids = ev["dados"]["parametros"]["exercitos"]
    base = estado["exercitos"][ids[0]]
    for i in ids[1:]:
        base["companhias"].extend(estado["exercitos"].pop(i)["companhias"])
    base["moral"] = ev["dados"]["extra"]["moral"]


@acao("dividir_exercito")
def _v_dividir(m, reino, p):
    e = exercito_proprio(m, reino, p["exercito"])
    idx = sorted({int(i) for i in p["companhias"]})
    exigir(len(e["companhias"]) >= 2 and idx and len(idx) < len(e["companhias"]), "seleção de companhias inválida")
    exigir(all(0 <= i < len(e["companhias"]) for i in idx), "índice de companhia inválido", codigo="formato_invalido")
    exigir(parado(e) and e["batalha"] is None, "exército precisa estar parado e fora de batalha")
    return Plano(dados={"novo": m.novo_id("exe", "exe"), "indices": idx})


@ao_aplicar("dividir_exercito")
def _a_dividir(estado, ev):
    d = ev["dados"]
    e = estado["exercitos"][d["parametros"]["exercito"]]
    idx = set(d["extra"]["indices"])
    novas = [c for i, c in enumerate(e["companhias"]) if i in idx]
    e["companhias"] = [c for i, c in enumerate(e["companhias"]) if i not in idx]
    usar_id(estado, "exe", d["extra"]["novo"])
    estado["exercitos"][d["extra"]["novo"]] = dict(e, id=d["extra"]["novo"], companhias=novas, acao=None)


@acao("definir_postura")
def _v_postura(m, reino, p):
    exercito_proprio(m, reino, p["exercito"])
    exigir(p["postura"] in POSTURAS, "postura inválida", codigo="formato_invalido")
    return Plano()


@ao_aplicar("definir_postura")
def _a_postura(estado, ev):
    estado["exercitos"][ev["dados"]["parametros"]["exercito"]]["postura"] = ev["dados"]["parametros"]["postura"]


# ---------------------------------------------------------------- movimento


@acao("mover_exercito")
def _v_mover(m, reino, p):
    estado = m.estado
    e = exercito_proprio(m, reino, p["exercito"])
    exigir(e["batalha"] is None, "exército em batalha: use recuar")
    destino = p["destino"]
    exigir(destino in estado["provincias"], "destino desconhecido", codigo="formato_invalido")
    postura = p.get("postura", e["postura"])
    exigir(postura in POSTURAS, "postura inválida", codigo="formato_invalido")
    exigir(parado(e), "exército já em movimento")
    exigir(destino != e["provincia"], "o exército já está no destino")
    so_reino = _so_no_reino(e)

    def permitido(pid):
        return pode_entrar(estado, reino, pid, postura, so_reino)

    if p.get("caminho"):
        rota = list(p["caminho"])
        exigir(rota[-1] == destino, "o caminho precisa terminar no destino", codigo="formato_invalido")
        atual = e["provincia"]
        for pid in rota:
            exigir(pid in estado["provincias"] and trecho_entre(estado, atual, pid) is not None, f"trecho inexistente até {pid}")
            atual = pid
    else:
        rota = caminho_mais_rapido(estado, e["provincia"], destino, permitido, m.params, e["companhias"])
        exigir(rota is not None, "sem caminho válido até o destino")
    for pid in rota:
        if not permitido(pid):
            dono = estado["provincias"][pid]["dono"]
            raise Rejeicao("precondicao_falhou", f"não pode entrar em {pid}", {"provincia": pid, "dono": dono})
    t0 = tempo_trecho(estado, rota[0], trecho_entre(estado, e["provincia"], rota[0]), m.params, e["companhias"])
    total = 0
    atual = e["provincia"]
    for pid in rota:
        total += tempo_trecho(estado, pid, trecho_entre(estado, atual, pid), m.params, e["companhias"])
        atual = pid

    def depois(m, ev):
        partir(m, e["id"], rota, m.agora + t0, postura, causa=ev["dados"]["acao_id"])

    return Plano(duracao=total, dados={"caminho": rota}, depois=depois)


@ao_concluir("mover_exercito")
def _c_mover(m, a):
    # A chegada é tratada pela agenda de movimento; aqui só fechamos a ação.
    m.emitir("acao_concluida", {"acao_id": a["id"], "tipo": a["tipo"]}, [a["reino"]], causa=a["id"])


def partir(m, eid, rota, chegada_em, postura=None, causa=None, motivo="ordem"):
    e = m.estado["exercitos"][eid]
    m.emitir(
        "exercito_partiu",
        {"exercito": eid, "de": e["provincia"], "caminho": rota, "chegada_em": chegada_em, "postura": postura or e["postura"], "motivo": motivo},
        visiveis_movimento(m.estado, e["provincia"], e["reino"]),
        causa=causa,
    )


@redutor("exercito_partiu")
def _partiu(estado, ev):
    d = ev["dados"]
    e = estado["exercitos"][d["exercito"]]
    e["postura"] = d["postura"]
    e["batalha"] = None
    aid = agendar(estado, ev, d["chegada_em"], "chegada_exercito", {"exercito": d["exercito"]})
    e["movimento"] = {"caminho": list(d["caminho"]), "de": d["de"], "chegada_em": d["chegada_em"], "agenda": aid}


@tratador_agenda("chegada_exercito")
def _chegada(m, item):
    estado = m.estado
    eid = item["dados"]["exercito"]
    e = estado["exercitos"].get(eid)
    if e is None or e["movimento"] is None:
        return
    mov = e["movimento"]
    pid = mov["caminho"][0]
    resto = mov["caminho"][1:]
    hostis = [h for h in hostis_em(estado, pid, e["reino"]) if h["id"] != eid]
    batalha = None
    fuga = False
    if hostis:
        todos_evitam = e["postura"] == "evitar_combate" and all(h["postura"] == "evitar_combate" for h in hostis)
        if not todos_evitam:
            if e["postura"] == "evitar_combate" and any(h["postura"] == "ofensiva" for h in hostis):
                fuga = aleatorio.chance(estado["semente"], "fuga", eid, m.agora, 0.5)
            batalha = not fuga
    proxima = None
    if resto and not batalha and not fuga:
        if pode_entrar(estado, e["reino"], resto[0], e["postura"], _so_no_reino(e)):
            proxima = {"caminho": resto, "chegada_em": m.agora + tempo_trecho(estado, resto[0], trecho_entre(estado, pid, resto[0]), m.params, e["companhias"])}
    m.emitir(
        "exercito_chegou",
        {"exercito": eid, "reino": e["reino"], "provincia": pid, "de": mov["de"], "soldados_aprox": round(soldados(e), -2), "proxima": proxima},
        visiveis_movimento(estado, pid, e["reino"]),
    )
    if fuga:
        perdas = {eid: _perdas_proporcionais(e, 0.10)}
        m.emitir("exercito_fugiu", {"exercito": eid, "provincia": pid, "companhias": perdas[eid]}, visiveis_movimento(estado, pid, e["reino"]))
        tr = trecho_entre(estado, pid, mov["de"])
        partir(m, eid, [mov["de"]], m.agora + tempo_trecho(estado, mov["de"], tr, m.params, e["companhias"]), motivo="fuga")
    elif batalha:
        iniciar_ou_entrar_batalha(m, pid, e, hostis)


@redutor("exercito_chegou")
def _chegou(estado, ev):
    d = ev["dados"]
    e = estado["exercitos"][d["exercito"]]
    e["provincia"] = d["provincia"]
    e["veio_de"] = d["de"]
    e["chegou_em"] = ev["ocorrido_em"]
    if d["proxima"]:
        aid = agendar(estado, ev, d["proxima"]["chegada_em"], "chegada_exercito", {"exercito": d["exercito"]})
        e["movimento"] = {"caminho": d["proxima"]["caminho"], "de": d["provincia"], "chegada_em": d["proxima"]["chegada_em"], "agenda": aid}
    else:
        e["movimento"] = None


@redutor("exercito_fugiu")
def _fugiu(estado, ev):
    e = estado["exercitos"][ev["dados"]["exercito"]]
    e["companhias"] = [dict(c) for c in ev["dados"]["companhias"] if c["soldados"] > 0]


def _perdas_proporcionais(e: dict, frac: float) -> list[dict]:
    return [{"tipo": c["tipo"], "soldados": int(round(c["soldados"] * (1 - frac)))} for c in e["companhias"]]


# ---------------------------------------------------------------- batalha


def iniciar_ou_entrar_batalha(m, pid, chegando, hostis):
    estado = m.estado
    existente = None
    for _, b in sorted(estado["batalhas"].items()):
        if b["provincia"] == pid:
            existente = b
            break
    if existente:
        lado = None
        for nome, ids in existente["lados"].items():
            outros = [estado["exercitos"][i] for i in ids if i in estado["exercitos"]]
            if any(em_guerra(estado, o["reino"], chegando["reino"]) for o in outros):
                lado = "B" if nome == "A" else "A"
                break
        if lado is None:
            lado = "A"
        m.emitir("batalha_reforco", {"batalha": existente["id"], "lado": lado, "exercito": chegando["id"]},
                 _envolvidos(estado, existente, extra=[chegando["reino"]]))
        return
    bid = m.novo_id("bat", "bat")
    lados = {"A": [chegando["id"]], "B": [h["id"] for h in hostis]}
    # aliados do recém-chegado parados na província entram do lado A
    for x in exercitos_em(estado, pid):
        if x["id"] not in lados["A"] and x["id"] not in lados["B"] and x["reino"] == chegando["reino"]:
            lados["A"].append(x["id"])
    reinos = sorted({estado["exercitos"][i]["reino"] for ids in lados.values() for i in ids})
    m.emitir(
        "batalha_iniciada",
        {"batalha": bid, "provincia": pid, "lados": lados, "reinos": reinos, "primeira_rodada": m.agora + HORA},
        visiveis_movimento(estado, pid, *reinos),
    )


def _envolvidos(estado, b, extra=()):
    reinos = set(extra)
    for ids in b["lados"].values():
        for i in ids:
            if i in estado["exercitos"]:
                reinos.add(estado["exercitos"][i]["reino"])
    return sorted(reinos)


def _marcar_hostilidade(estado, reinos, t):
    for g in estado["guerras"].values():
        if g["estado"] == "ativa" and g["agressor"] in reinos and g["alvo"] in reinos:
            g["ultima_hostilidade"] = t


@redutor("batalha_iniciada")
def _batalha_iniciada(estado, ev):
    d = ev["dados"]
    usar_id(estado, "bat", d["batalha"])
    aid = agendar(estado, ev, d["primeira_rodada"], "rodada_batalha", {"batalha": d["batalha"]}, prioridade=4)
    estado["batalhas"][d["batalha"]] = {"id": d["batalha"], "provincia": d["provincia"], "lados": d["lados"], "rodada": 0, "agenda": aid, "inicio": ev["ocorrido_em"]}
    for ids in d["lados"].values():
        for i in ids:
            e = estado["exercitos"][i]
            e["batalha"] = d["batalha"]
            if e["movimento"]:
                estado["agenda"].pop(e["movimento"]["agenda"], None)
                e["movimento"] = None
    _marcar_hostilidade(estado, d["reinos"], ev["ocorrido_em"])


@redutor("batalha_reforco")
def _reforco(estado, ev):
    d = ev["dados"]
    b = estado["batalhas"][d["batalha"]]
    b["lados"][d["lado"]].append(d["exercito"])
    e = estado["exercitos"][d["exercito"]]
    e["batalha"] = d["batalha"]
    if e["movimento"]:
        estado["agenda"].pop(e["movimento"]["agenda"], None)
        e["movimento"] = None


def _forcas(estado, prov, exs, semente, chave, t):
    """Ataque e defesa de um lado (seção 10.3)."""
    ruido = aleatorio.entre(semente, "ruido_batalha", chave, t, 0.9, 1.1)
    atq = dfs = 0.0
    for e in exs:
        dono = prov["dono"] == e["reino"]
        mult_terreno = BIOMAS[prov["bioma"]]["defesa"] if dono else 1.0
        mural = muralha_intacta(prov) and dono
        mult_muralha = 1.3 ** nivel_ativo(prov, "muralha") if mural else 1.0
        moral = e["moral"] / 100
        for c in e["companhias"]:
            u = UNIDADES[c["tipo"]]
            n = c["soldados"] / SOLDADOS_POR_COMPANHIA
            fator_tipo = 1.0
            if c["tipo"] == "cavalaria" and prov["bioma"] in ("floresta", "montanha", "pantano"):
                fator_tipo = 0.6
            arq = 1.3 if (c["tipo"] == "arqueiros" and mural) else 1.0
            atq += n * u.ataque * moral * fator_tipo
            dfs += n * u.defesa * moral * fator_tipo * mult_terreno * mult_muralha * arq
    return atq * ruido, dfs * ruido


def _destino_recuo(estado, e, params):
    """Província de onde veio, se ainda puder entrar; senão a própria vizinha mais próxima."""
    pid = e["provincia"]
    if e["veio_de"] and e["veio_de"] != pid and trecho_entre(estado, pid, e["veio_de"]) and pode_entrar(estado, e["reino"], e["veio_de"], "defensiva", _so_no_reino(e)):
        if not hostis_em(estado, e["veio_de"], e["reino"]):
            return e["veio_de"]
    for v, _ in vizinhos(estado, pid):
        if estado["provincias"][v]["dono"] == e["reino"] and not hostis_em(estado, v, e["reino"]):
            return v
    return None


@tratador_agenda("rodada_batalha")
def _rodada(m, item):
    estado = m.estado
    b = estado["batalhas"].get(item["dados"]["batalha"])
    if b is None:
        return
    prov = estado["provincias"][b["provincia"]]
    rodada = b["rodada"] + 1
    lados = {n: [estado["exercitos"][i] for i in ids if i in estado["exercitos"]] for n, ids in b["lados"].items()}
    forcas = {n: _forcas(estado, prov, exs, estado["semente"], f"{b['id']}:{n}", m.agora) for n, exs in lados.items()}
    resultado = {}
    recuos, rendidos = [], []
    for n, exs in lados.items():
        outro = "B" if n == "A" else "A"
        atq_outro = forcas[outro][0]
        dfs = forcas[n][1]
        frac = 0.25 if dfs <= 0 else min(0.25, 0.06 * atq_outro / dfs)
        for e in exs:
            comps = _perdas_proporcionais(e, frac)
            depois = sum(c["soldados"] for c in comps)
            antes = soldados(e)
            pp = 0 if antes == 0 else (antes - depois) / antes * 100
            moral = max(0.0, e["moral"] - 1.5 * pp)
            resultado[e["id"]] = {"companhias": comps, "moral": r3(moral), "perdas": antes - depois}
    # recuo e rendição: moral abaixo de 30 (seção 10.3)
    for n, exs in lados.items():
        for e in exs:
            res = resultado[e["id"]]
            if sum(c["soldados"] for c in res["companhias"]) == 0:
                continue
            if res["moral"] < 30:
                destino = _destino_recuo(estado, e, m.params)
                if destino is None:
                    rendidos.append(e["id"])
                else:
                    res["companhias"] = [{"tipo": c["tipo"], "soldados": int(round(c["soldados"] * 0.9))} for c in res["companhias"]]
                    tr = trecho_entre(estado, e["provincia"], destino)
                    recuos.append({"exercito": e["id"], "para": destino, "chegada_em": m.agora + tempo_trecho(estado, destino, tr, m.params, e["companhias"])})
    saem = {r["exercito"] for r in recuos} | set(rendidos)
    restantes = {}
    for n, exs in lados.items():
        restantes[n] = [e["id"] for e in exs if e["id"] not in saem and sum(c["soldados"] for c in resultado[e["id"]]["companhias"]) > 0]
    fim = not restantes["A"] or not restantes["B"]
    vencedor = None
    if fim:
        vencedor = "A" if restantes["A"] else ("B" if restantes["B"] else None)
    envolvidos = _envolvidos(estado, b)
    m.emitir(
        "batalha_rodada",
        {"batalha": b["id"], "rodada": rodada, "exercitos": resultado, "recuos": recuos, "rendidos": rendidos,
         "proxima_rodada": None if fim else m.agora + HORA},
        envolvidos,
    )
    if fim:
        reinos_venc = sorted({estado["exercitos"][i]["reino"] for i in restantes[vencedor]}) if vencedor else []
        m.emitir("batalha_encerrada", {"batalha": b["id"], "provincia": b["provincia"], "vencedor": reinos_venc, "rodadas": rodada},
                 visiveis_movimento(estado, b["provincia"], *envolvidos))


@redutor("batalha_rodada")
def _batalha_rodada(estado, ev):
    d = ev["dados"]
    b = estado["batalhas"][d["batalha"]]
    b["rodada"] = d["rodada"]
    for eid, res in d["exercitos"].items():
        e = estado["exercitos"].get(eid)
        if e is None:
            continue
        e["companhias"] = [dict(c) for c in res["companhias"] if c["soldados"] > 0]
        e["moral"] = res["moral"]
        if not e["companhias"]:
            del estado["exercitos"][eid]
    for eid in d["rendidos"]:
        estado["exercitos"].pop(eid, None)
    for r in d["recuos"]:
        e = estado["exercitos"].get(r["exercito"])
        if e is None:
            continue
        e["batalha"] = None
        aid = agendar(estado, ev, r["chegada_em"], "chegada_exercito", {"exercito": r["exercito"]})
        e["movimento"] = {"caminho": [r["para"]], "de": e["provincia"], "chegada_em": r["chegada_em"], "agenda": aid}
    for n in b["lados"]:
        b["lados"][n] = [i for i in b["lados"][n] if i in estado["exercitos"] and estado["exercitos"][i]["batalha"] == b["id"]]
    if d["proxima_rodada"]:
        b["agenda"] = agendar(estado, ev, d["proxima_rodada"], "rodada_batalha", {"batalha": b["id"]}, prioridade=4)
    reinos = {estado["exercitos"][i]["reino"] for ids in b["lados"].values() for i in ids}
    _marcar_hostilidade(estado, reinos | set(ev["visivel_para"]), ev["ocorrido_em"])


@redutor("batalha_encerrada")
def _batalha_encerrada(estado, ev):
    b = estado["batalhas"].pop(ev["dados"]["batalha"], None)
    if b:
        estado["agenda"].pop(b.get("agenda"), None)
    for e in estado["exercitos"].values():
        if e["batalha"] == ev["dados"]["batalha"]:
            e["batalha"] = None
            e["chegou_em"] = ev["ocorrido_em"]


@acao("recuar")
def _v_recuar(m, reino, p):
    e = exercito_proprio(m, reino, p["exercito"])
    exigir(e["batalha"] is not None, "o exército não está em batalha")
    destino = _destino_recuo(m.estado, e, m.params)
    exigir(destino is not None, "sem rota de recuo")
    tr = trecho_entre(m.estado, e["provincia"], destino)
    chegada = m.agora + tempo_trecho(m.estado, destino, tr, m.params, e["companhias"])
    b = m.estado["batalhas"][e["batalha"]]

    def depois(m, ev):
        m.emitir("exercito_recuou", {"exercito": e["id"], "batalha": b["id"], "para": destino, "chegada_em": chegada},
                 _envolvidos(m.estado, b), causa=ev["dados"]["acao_id"])
        lados = {n: [i for i in ids if i in m.estado["exercitos"] and m.estado["exercitos"][i]["batalha"] == b["id"]] for n, ids in b["lados"].items()}
        if not lados["A"] or not lados["B"]:
            venc = sorted({m.estado["exercitos"][i]["reino"] for ids in lados.values() for i in ids})
            m.emitir("batalha_encerrada", {"batalha": b["id"], "provincia": b["provincia"], "vencedor": venc, "rodadas": b["rodada"]},
                     visiveis_movimento(m.estado, b["provincia"], *_envolvidos(m.estado, b, extra=[reino])))

    return Plano(depois=depois)


@redutor("exercito_recuou")
def _recuou(estado, ev):
    d = ev["dados"]
    e = estado["exercitos"][d["exercito"]]
    e["batalha"] = None
    e["companhias"] = [{"tipo": c["tipo"], "soldados": int(round(c["soldados"] * 0.9))} for c in e["companhias"]]
    aid = agendar(estado, ev, d["chegada_em"], "chegada_exercito", {"exercito": d["exercito"]})
    e["movimento"] = {"caminho": [d["para"]], "de": e["provincia"], "chegada_em": d["chegada_em"], "agenda": aid}
    b = estado["batalhas"].get(d["batalha"])
    if b:
        for n in b["lados"]:
            b["lados"][n] = [i for i in b["lados"][n] if i != d["exercito"]]


# ---------------------------------------------------------------- cerco, saque, ocupação


@acao("sitiar")
def _v_sitiar(m, reino, p):
    e = exercito_proprio(m, reino, p["exercito"])
    prov = m.estado["provincias"][e["provincia"]]
    exigir(parado(e) and e["batalha"] is None, "exército precisa estar parado e fora de batalha")
    exigir(em_guerra(m.estado, reino, prov["dono"]), "a província não é de um reino em guerra com você")
    exigir(muralha_intacta(prov), "a província não tem muralha intacta")
    exigir(not hostis_em(m.estado, prov["id"], reino), "vença os defensores antes de sitiar")
    exigir(prov["sitiada_por"] is None, "a província já está sitiada")
    return Plano(dados={"provincia": prov["id"], "dono": prov["dono"]},
                 depois=lambda m, ev: m.emitir("cerco_iniciado", {"provincia": prov["id"], "exercito": e["id"], "reino": reino},
                                                visiveis_movimento(m.estado, prov["id"], reino), causa=ev["dados"]["acao_id"]))


@redutor("cerco_iniciado")
def _cerco(estado, ev):
    estado["provincias"][ev["dados"]["provincia"]]["sitiada_por"] = ev["dados"]["exercito"]


@redutor("cerco_progresso")
def _cerco_prog(estado, ev):
    estado["provincias"][ev["dados"]["provincia"]]["muralha_integridade"] = ev["dados"]["integridade"]


@redutor("cerco_encerrado", "muralha_caiu")
def _cerco_fim(estado, ev):
    p = estado["provincias"][ev["dados"]["provincia"]]
    p["sitiada_por"] = None
    if ev["tipo"] == "muralha_caiu":
        p["muralha_integridade"] = 0.0


@acao("saquear")
def _v_saquear(m, reino, p):
    e = exercito_proprio(m, reino, p["exercito"])
    prov = m.estado["provincias"][e["provincia"]]
    exigir(parado(e) and e["batalha"] is None, "exército precisa estar parado e fora de batalha")
    exigir(prov["tipo"] == "reino" and em_guerra(m.estado, reino, prov["dono"]), "a província não é de um reino em guerra com você")
    exigir(not hostis_em(m.estado, prov["id"], reino), "a província tem defensores")
    exigir(not muralha_intacta(prov), "a muralha está intacta")
    return Plano(duracao=m.params.duracao(12), dados={"provincia": prov["id"]})


@ao_concluir("saquear")
def _c_saquear(m, a):
    estado = m.estado
    e = estado["exercitos"].get(a["parametros"]["exercito"])
    pid = a["extra"]["provincia"]
    prov = estado["provincias"][pid]
    if e is None or e["provincia"] != pid or not parado(e) or e["batalha"] is not None:
        return falhar(m, a, "o exército saiu da província")
    if not em_guerra(estado, a["reino"], prov["dono"]) or hostis_em(estado, pid, a["reino"]):
        return falhar(m, a, "condições do saque não valem mais")
    vitima = estado["reinos"][prov["dono"]]
    levado = {r: r3(min(300.0, vitima["estoque"][r] * 0.10)) for r in ("comida", "madeira", "ferro", "ouro")}
    concluir_ok(
        m, a, "provincia_saqueada",
        {"provincia": pid, "saqueador": a["reino"], "vitima": prov["dono"], "levado": levado,
         "felicidade_ate": m.agora + m.params.dias_jogo(14)},
        visiveis_movimento(estado, pid, a["reino"]),
    )


@redutor("provincia_saqueada")
def _saqueada(estado, ev):
    d = ev["dados"]
    v = estado["reinos"][d["vitima"]]
    s = estado["reinos"][d["saqueador"]]
    for r, q in d["levado"].items():
        v["estoque"][r] = r3(v["estoque"][r] - q)
        s["estoque"][r] = r3(s["estoque"][r] + q)
    prov = estado["provincias"][d["provincia"]]
    prov["safra"] = {"inicio": ev["ocorrido_em"], "soma": 0.0, "horas": 0}
    prov["mods"].append({"delta": -15, "ate": d["felicidade_ate"], "motivo": "saque"})
    s["reputacao"] = max(0.0, s["reputacao"] - 2)
    _marcar_hostilidade(estado, {d["saqueador"], d["vitima"]}, ev["ocorrido_em"])


def tick_militar(m) -> None:
    """Cerco, ocupação, libertação e anexação, avaliados a cada tick."""
    estado, params, t = m.estado, m.params, m.agora
    por_tick = params.fator / 24
    for pid, prov in sorted(estado["provincias"].items()):
        if prov["tipo"] != "reino":
            continue
        # Cerco
        sid = prov["sitiada_por"]
        if sid:
            e = estado["exercitos"].get(sid)
            if e is None or e["provincia"] != pid or not parado(e) or e["batalha"] is not None or not em_guerra(estado, e["reino"], prov["dono"]):
                m.emitir("cerco_encerrado", {"provincia": pid, "motivo": "sitiante saiu"}, visiveis_movimento(estado, pid))
            else:
                inf = sum(c["soldados"] for c in e["companhias"] if c["tipo"] == "infantaria") / 100
                cer = sum(c["soldados"] for c in e["companhias"] if c["tipo"] == "cerco") / 100
                integ = r3(max(0.0, prov["muralha_integridade"] - (4 * inf + 25 * cer) * por_tick))
                if integ <= 0:
                    m.emitir("muralha_caiu", {"provincia": pid, "exercito": sid}, visiveis_movimento(estado, pid, e["reino"]))
                else:
                    m.emitir("cerco_progresso", {"provincia": pid, "integridade": integ}, sorted({e["reino"], prov["dono"]}))
        # Libertação
        ocup = prov["ocupante"]
        if ocup:
            presentes = [x for x in exercitos_em(estado, pid) if x["reino"] == ocup and x["batalha"] is None]
            if not presentes or not em_guerra(estado, ocup, prov["dono"]):
                m.emitir("provincia_libertada", {"provincia": pid, "dono": prov["dono"], "ocupante": ocup}, ["publico"])
                continue
            prazo = params.dias_jogo(14 if prov["capital"] else 7)
            if t - prov["ocupado_desde"] >= prazo:
                anexar(m, pid, ocup)
                continue
        # Ocupação
        if prov["ocupante"] is None and not muralha_intacta(prov):
            for e in exercitos_em(estado, pid):
                if e["batalha"] is not None or not em_guerra(estado, e["reino"], prov["dono"]):
                    continue
                if hostis_em(estado, pid, e["reino"]):
                    continue
                if t - e["chegou_em"] >= params.duracao(12):
                    m.emitir("provincia_ocupada", {"provincia": pid, "ocupante": e["reino"], "dono": prov["dono"]}, ["publico"])
                    break


def anexar(m, pid, para):
    estado = m.estado
    prov = estado["provincias"][pid]
    de = prov["dono"]
    nova_capital = None
    if prov["capital"]:
        restantes = [p["id"] for _, p in sorted(estado["provincias"].items()) if p["dono"] == de and p["id"] != pid]
        nova_capital = restantes[0] if restantes else None
    m.emitir("provincia_anexada", {"provincia": pid, "de": de, "para": para, "nova_capital_de": nova_capital}, ["publico"])
    if prov["capital"]:
        m.emitir("capital_perdida", {"reino": de, "provincia": pid, "nova_capital": nova_capital}, ["publico"])


@redutor("provincia_ocupada")
def _ocupada(estado, ev):
    d = ev["dados"]
    p = estado["provincias"][d["provincia"]]
    p["ocupante"] = d["ocupante"]
    p["ocupado_desde"] = ev["ocorrido_em"]
    p["safra"] = {"inicio": ev["ocorrido_em"], "soma": 0.0, "horas": 0}
    _marcar_hostilidade(estado, {d["ocupante"], d["dono"]}, ev["ocorrido_em"])


@redutor("provincia_libertada")
def _libertada(estado, ev):
    p = estado["provincias"][ev["dados"]["provincia"]]
    p["ocupante"] = None
    p["ocupado_desde"] = None


@redutor("provincia_anexada")
def _anexada(estado, ev):
    d = ev["dados"]
    p = estado["provincias"][d["provincia"]]
    p["dono"] = d["para"]
    p["ocupante"] = None
    p["ocupado_desde"] = None
    p["capital"] = False
    p["cedidos"] = 0
    p["alocacao_desde"] = None
    if d["nova_capital_de"]:
        estado["provincias"][d["nova_capital_de"]]["capital"] = True
        estado["reinos"][d["de"]]["capital"] = d["nova_capital_de"]
    elif estado["reinos"][d["de"]]["capital"] == d["provincia"]:
        estado["reinos"][d["de"]]["capital"] = None


informativo("capital_perdida")


# ---------------------------------------------------------------- declaração e fim de guerra


@acao("declarar_guerra")
def _v_declarar(m, reino, p):
    estado = m.estado
    alvo = p["alvo"]
    exigir(alvo in estado["reinos"] and alvo != reino, "alvo inválido", codigo="formato_invalido")
    exigir(guerra_entre(estado, reino, alvo) is None, "já há guerra declarada ou ativa")
    if tregua_ativa(estado, reino, alvo, m.agora):
        raise Rejeicao("proibido_por_tratado", "há trégua ativa entre os reinos")
    bloqueiam = [t for t in tratados_ativos_entre(estado, reino, alvo) if tem_clausula(t, "nao_agressao")]
    romper = bool(p.get("romper_tratados"))
    if bloqueiam and not romper:
        raise Rejeicao("proibido_por_tratado", "há tratado de não agressão ativo; use romper_tratados", {"tratados": [t["id"] for t in bloqueiam]})
    gid = m.novo_id("gue", "gue")

    def depois(m, ev):
        from .diplomacia import romper

        for t in bloqueiam:
            romper(m, t, reino, "declaracao_de_guerra", causa=ev["dados"]["acao_id"])
        m.emitir("guerra_declarada", {"guerra": gid, "agressor": reino, "alvo": alvo, "vigencia": m.agora + m.params.duracao(12)},
                 ["publico"], causa=ev["dados"]["acao_id"])

    return Plano(depois=depois)


@redutor("guerra_declarada")
def _declarada(estado, ev):
    d = ev["dados"]
    usar_id(estado, "gue", d["guerra"])
    estado["guerras"][d["guerra"]] = {
        "id": d["guerra"], "agressor": d["agressor"], "alvo": d["alvo"], "estado": "declarada",
        "declarada_em": ev["ocorrido_em"], "vigencia": d["vigencia"], "ultima_hostilidade": d["vigencia"],
        "encerrada_em": None, "tregua_ate": None,
    }
    agendar(estado, ev, d["vigencia"], "guerra_vigencia", {"guerra": d["guerra"]})


@tratador_agenda("guerra_vigencia")
def _vigencia(m, item):
    g = m.estado["guerras"][item["dados"]["guerra"]]
    if g["estado"] != "declarada":
        return
    m.emitir("guerra_iniciada", {"guerra": g["id"], "agressor": g["agressor"], "alvo": g["alvo"]}, ["publico"])


@redutor("guerra_iniciada")
def _iniciada(estado, ev):
    g = estado["guerras"][ev["dados"]["guerra"]]
    g["estado"] = "ativa"
    g["ultima_hostilidade"] = ev["ocorrido_em"]


def encerrar_guerra(m, g: dict, motivo: str, tregua_dias: float | None = None, causa=None):
    estado = m.estado
    a, b = g["agressor"], g["alvo"]
    m.emitir(
        "guerra_encerrada_por_inatividade" if motivo == "inatividade" else "guerra_encerrada",
        {"guerra": g["id"], "agressor": a, "alvo": b, "motivo": motivo,
         "tregua_ate": m.agora + m.params.dias_jogo(tregua_dias) if tregua_dias else None},
        ["publico"], causa=causa,
    )
    # batalhas entre os dois terminam sem vencedor
    for _, bt in sorted(estado["batalhas"].items()):
        reinos = set(_envolvidos(estado, bt))
        if {a, b} <= reinos:
            m.emitir("batalha_encerrada", {"batalha": bt["id"], "provincia": bt["provincia"], "vencedor": [], "rodadas": bt["rodada"], "motivo": "paz"},
                     sorted(reinos))
    for pid, p in sorted(estado["provincias"].items()):
        if p["ocupante"] in (a, b) and p["dono"] in (a, b):
            m.emitir("provincia_libertada", {"provincia": pid, "dono": p["dono"], "ocupante": p["ocupante"]}, ["publico"])
        if p["sitiada_por"]:
            e = estado["exercitos"].get(p["sitiada_por"])
            if e and {e["reino"], p["dono"]} == {a, b}:
                m.emitir("cerco_encerrado", {"provincia": pid, "motivo": "paz"}, sorted({a, b}))
    # exércitos em território do outro voltam para casa
    for _, e in sorted(estado["exercitos"].items()):
        if e["reino"] not in (a, b):
            continue
        outro = b if e["reino"] == a else a
        prov = estado["provincias"][e["provincia"]]
        if prov["dono"] == outro and parado(e):
            casa = estado["reinos"][e["reino"]]["capital"]
            if casa is None:
                continue
            rota = caminho_mais_rapido(estado, e["provincia"], casa, lambda pid: True, m.params, e["companhias"])
            if rota:
                tr = trecho_entre(estado, e["provincia"], rota[0])
                partir(m, e["id"], rota, m.agora + tempo_trecho(estado, rota[0], tr, m.params, e["companhias"]), motivo="volta_para_casa")


@redutor("guerra_encerrada", "guerra_encerrada_por_inatividade")
def _encerrada(estado, ev):
    g = estado["guerras"][ev["dados"]["guerra"]]
    g["estado"] = "encerrada"
    g["encerrada_em"] = ev["ocorrido_em"]
    g["tregua_ate"] = ev["dados"]["tregua_ate"]


def checar_inatividade_guerras(m) -> None:
    for _, g in sorted(m.estado["guerras"].items()):
        if g["estado"] == "ativa" and m.agora - g["ultima_hostilidade"] >= m.params.dias_jogo(21):
            encerrar_guerra(m, g, "inatividade", tregua_dias=7)
