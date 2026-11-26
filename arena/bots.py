"""Bots de regras simples, sem LLM, para governar os reinos de teste.

Cada bot só enxerga o retrato do próprio reino (`estado_do_reino`), como uma IA
de empresa enxergaria pela API. Três arquétipos da seção 20.2, item 4:
fazendeiro, mercador e conquistador. Os bots são determinísticos.
"""

from __future__ import annotations

from .regras import CONSTRUCOES, MERCADO_BASE
from .tempo import DIA, HORA

CIDADE = "cid_portolivre"


class Bot:
    arquetipo = "base"
    aliquota = 15
    alocacao_capital = {"agricultura": 65, "madeira": 15, "mineracao": 0, "oficios": 15, "cultura": 5}
    alocacao_floresta = {"agricultura": 50, "madeira": 35, "mineracao": 0, "oficios": 15, "cultura": 0}
    alocacao_colina = {"agricultura": 55, "madeira": 10, "mineracao": 20, "oficios": 15, "cultura": 0}
    fila_obras: list[tuple[str, str]] = []  # (papel da província, construção)

    def __init__(self, reino: str):
        self.reino = reino
        self.n = 0
        self.inicializado = False
        self.feitas: set[str] = set()

    # -------------------------------------------------------------- utilidades

    def acao(self, _tipo: str, _comentario: str | None = None, /, **parametros) -> dict:
        self.n += 1
        a = {"chave_idempotencia": f"{self.reino}-{self.arquetipo}-{self.n}", "tipo": _tipo, "parametros": parametros}
        if _comentario:
            a["comentario"] = _comentario
        return a

    @staticmethod
    def consumo_dia(v: dict, fator: int) -> float:
        pop = sum(p["populacao"] for p in v["provincias"] if p["dono"] == v["reino"]["id"])
        sold = sum(sum(c["soldados"] for c in e["companhias"]) for e in v["exercitos"])
        return (pop + sold) / 10 * fator

    @staticmethod
    def papel(p: dict) -> str:
        return {"planicie": "capital", "floresta": "floresta", "colina": "colina"}.get(p["bioma"], "outra")

    def provincias(self, v):
        return [p for p in v["provincias"] if p["dono"] == self.reino]

    def obras_em_andamento(self, v) -> set[str]:
        return {a["parametros"].get("provincia") for a in v["acoes_em_andamento"] if a["tipo"] in ("construir", "melhorar")}

    def ofertas_abertas(self, v) -> int:
        return sum(1 for c in v["caravanas"] if c["tipo"].startswith("mercado"))

    # -------------------------------------------------------------- decisão

    def decidir(self, v: dict, agora: int, fator: int) -> list[dict]:
        acoes: list[dict] = []
        if not self.inicializado:
            self.inicializado = True
            acoes += self.iniciar(v)
        acoes += self.cuidar_comida(v, fator)
        acoes += self.cuidar_felicidade(v)
        acoes += self.construir(v)
        acoes += self.responder_tratados(v)
        acoes += self.defender(v)
        acoes += self.especifico(v, agora, fator)
        return acoes

    def iniciar(self, v) -> list[dict]:
        out = []
        if v["reino"]["aliquota"] != self.aliquota:
            out.append(self.acao("definir_impostos", aliquota=self.aliquota))
        for p in self.provincias(v):
            aloc = {"capital": self.alocacao_capital, "floresta": self.alocacao_floresta, "colina": self.alocacao_colina}.get(self.papel(p))
            if aloc:
                out.append(self.acao("alocar_trabalho", provincia=p["id"], setores=aloc))
        return out

    def cuidar_comida(self, v, fator) -> list[dict]:
        """Vende excedentes e compra comida no mercado quando o estoque fica curto."""
        est = v["estoque"]
        dias = est["comida"] / max(1.0, self.consumo_dia(v, fator))
        out = []
        abertas = self.ofertas_abertas(v)
        mercado = v["mercados"][CIDADE]
        if est["madeira"] < 20 or est["comida"] < 4:
            return out  # sem madeira e comida nem a caravana sai (seção 8.2)
        if dias < 2 and abertas < 3:
            for r, reserva in (("madeira", 500), ("ferro", 250)):
                if est[r] > reserva + 100:
                    qtd = int(min(500, est[r] - reserva))
                    out.append(self.acao("ofertar_mercado", "vender excedente para comprar comida", cidade=CIDADE, lado="vender",
                                         recurso=r, quantidade=qtd, preco_limite=round(mercado[r]["preco"] * 0.6, 3)))
                    abertas += 1
                    break
        if dias < 1.5 and abertas < 3 and est["ouro"] > 250:
            limite = round(min(4 * MERCADO_BASE["comida"]["P0"], mercado["comida"]["preco"] * 1.3), 3)
            qtd = int(min(500, (est["ouro"] - 100) / max(0.01, limite)))
            if qtd >= 50:
                out.append(self.acao("ofertar_mercado", "estoque de comida baixo", cidade=CIDADE, lado="comprar",
                                     recurso="comida", quantidade=qtd, preco_limite=limite))
        chave = f"aloc_fome:{v['estacao']}"
        if dias < 0.5 and chave not in self.feitas:
            self.feitas.add(chave)
            for p in self.provincias(v):
                out.append(self.acao("alocar_trabalho", "fome: mais gente no campo", provincia=p["id"],
                                     setores={"agricultura": 75, "madeira": 5, "mineracao": 5, "oficios": 15, "cultura": 0}))
        return out

    def cuidar_felicidade(self, v) -> list[dict]:
        provs = self.provincias(v)
        if not provs:
            return []
        media = sum(p["felicidade"] for p in provs) / len(provs)
        out = []
        r = v["reino"]
        if media < 35 and r["aliquota"] > 5 and "imposto_baixo" not in self.feitas:
            self.feitas.add("imposto_baixo")
            out.append(self.acao("definir_impostos", "felicidade baixa", aliquota=max(5, r["aliquota"] - 10)))
        tem = set(r["leis"]) | set(r["leis_pendentes"])
        if media < 40 and "festas_publicas" not in tem and v["estoque"]["ouro"] > 400 and len(tem) < 3:
            out.append(self.acao("promulgar_lei", "felicidade baixa", lei="festas_publicas"))
        if media > 60 and "imposto_baixo" in self.feitas:
            self.feitas.discard("imposto_baixo")
            out.append(self.acao("definir_impostos", "felicidade recuperada", aliquota=self.aliquota))
        return out

    def construir(self, v) -> list[dict]:
        est = v["estoque"]
        ocupadas = self.obras_em_andamento(v)
        for papel, tipo in self.fila_obras:
            chave = f"obra:{papel}:{tipo}"
            if chave in self.feitas:
                continue
            alvo = [p for p in self.provincias(v) if self.papel(p) == papel]
            if not alvo:
                self.feitas.add(chave)
                continue
            p = alvo[0]
            if p["id"] in ocupadas:
                return []
            existentes = [c for c in p["construcoes"].values() if c["tipo"] == tipo]
            custo = CONSTRUCOES[tipo].custo
            if existentes and tipo in ("fazenda", "mercado", "serraria", "mina", "armazem", "moradia"):
                c = existentes[0]
                if c["nivel"] >= 3 or c["obra_ate"]:
                    self.feitas.add(chave)
                    continue
                n = c["nivel"] + 1
                if all(est.get(k, 0) >= q * n + 150 for k, q in custo.items()):
                    self.feitas.add(chave)
                    return [self.acao("melhorar", provincia=p["id"], construcao=c["id"])]
                return []
            if len(p["construcoes"]) >= p["slots"]:
                self.feitas.add(chave)
                continue
            if all(est.get(k, 0) >= q + 150 for k, q in custo.items()):
                self.feitas.add(chave)
                return [self.acao("construir", provincia=p["id"], construcao=tipo)]
            return []
        return []

    def responder_tratados(self, v) -> list[dict]:
        out = []
        for t in v["tratados"]:
            if t["status"] != "proposto" or self.reino in t["aceites"]:
                continue
            chave = f"resp:{t['id']}"
            if chave in self.feitas:
                continue
            self.feitas.add(chave)
            if self.aceita(v, t):
                out.append(self.acao("aceitar_tratado", tratado=t["id"]))
            else:
                out.append(self.acao("recusar_tratado", tratado=t["id"]))
        return out

    def aceita(self, v, t) -> bool:
        tipos = {c["tipo"] for c in t["clausulas"]}
        if "fim_de_guerra" in tipos:
            return True
        if "pagamento_unico" in tipos or "pagamento_periodico" in tipos:
            # só aceita se não for quem paga
            return all(c.get("de") != self.reino for c in t["clausulas"] if c["tipo"] in ("pagamento_unico", "pagamento_periodico"))
        return True

    def defender(self, v) -> list[dict]:
        ameacado = any(g["alvo"] == self.reino for g in v["guerras"]) or any(
            e["provincia"] in {p["id"] for p in self.provincias(v)} for e in v["exercitos_avistados"]
        )
        if not ameacado:
            return []
        out = []
        cap = v["reino"]["capital"]
        meus = sum(sum(c["soldados"] for c in e["companhias"]) for e in v["exercitos"])
        inimigos = sum(e.get("soldados_aprox", sum(c["soldados"] for c in e.get("companhias", []))) for e in v["exercitos_avistados"])
        treinando = sum(1 for a in v["acoes_em_andamento"] if a["tipo"] == "recrutar")
        alvo = max(500, inimigos * 1.2)
        if meus + treinando * 100 < alvo and v["estoque"]["ouro"] > 200 and treinando < 4 and cap:
            tipo = "infantaria" if v["estoque"]["ferro"] >= 40 else "milicia"
            out.append(self.acao("recrutar", "defesa", provincia=cap, tipo=tipo, quantidade=2))
        for e in v["exercitos"]:
            if e["postura"] != "defensiva" and e["batalha"] is None and self.arquetipo != "conquistador":
                out.append(self.acao("definir_postura", exercito=e["id"], postura="defensiva"))
        return out

    def especifico(self, v, agora, fator) -> list[dict]:
        return []


class Fazendeiro(Bot):
    arquetipo = "fazendeiro"
    aliquota = 12
    fila_obras = [
        ("capital", "armazem"), ("floresta", "serraria"), ("capital", "celeiro"), ("capital", "fazenda"),
        ("colina", "fazenda"), ("floresta", "fazenda"), ("capital", "armazem"), ("capital", "moradia"),
        ("capital", "templo"), ("floresta", "armazem"), ("capital", "teatro"), ("colina", "moradia"),
    ]

    def especifico(self, v, agora, fator):
        out = []
        if "nao_agressao" not in self.feitas and v["dia"] >= 2:
            self.feitas.add("nao_agressao")
            for outro in sorted(v["relacoes"]):
                out.append(self.acao("propor_tratado", "paz para crescer", partes=[self.reino, outro], duracao_dias=60,
                                     preambulo="Pacto de boa vizinhança", clausulas=[{"tipo": "nao_agressao"}]))
        return out


class Mercador(Bot):
    arquetipo = "mercador"
    aliquota = 18
    alocacao_floresta = {"agricultura": 45, "madeira": 40, "mineracao": 0, "oficios": 15, "cultura": 0}
    fila_obras = [
        ("floresta", "serraria"), ("capital", "armazem"), ("colina", "mina"), ("capital", "mercado"),
        ("capital", "celeiro"), ("floresta", "serraria"), ("colina", "mercado"), ("capital", "teatro"),
        ("capital", "moradia"), ("floresta", "armazem"),
    ]

    def especifico(self, v, agora, fator):
        out = []
        est, cap = v["estoque"], v["capacidade"]
        if self.ofertas_abertas(v) < 2 and est["comida"] >= 4:
            for r in ("madeira", "ferro"):
                reserva = 400 if r == "madeira" else 150
                if est[r] > max(reserva + 200, cap[r] * 0.6):
                    qtd = int(min(500, est[r] - reserva))
                    preco = v["mercados"][CIDADE][r]["preco"]
                    out.append(self.acao("ofertar_mercado", "vender excedente", cidade=CIDADE, lado="vender", recurso=r,
                                         quantidade=qtd, preco_limite=round(preco * 0.7, 3)))
                    break
        if "troca" not in self.feitas and v["dia"] >= 3:
            self.feitas.add("troca")
            parceiro = sorted(v["relacoes"])[0]
            out.append(self.acao("propor_tratado", "comércio estável", partes=[self.reino, parceiro], duracao_dias=40,
                                 preambulo="Rota da madeira",
                                 clausulas=[{"tipo": "nao_agressao"},
                                            {"tipo": "troca_recorrente", "a_cada_dias": 4, "de_a_para_b": {"madeira": 150},
                                             "de_b_para_a": {"ouro": 90}}]))
        return out

    def aceita(self, v, t):
        return super().aceita(v, t)


class Conquistador(Bot):
    arquetipo = "conquistador"
    aliquota = 22
    alocacao_colina = {"agricultura": 50, "madeira": 10, "mineracao": 25, "oficios": 15, "cultura": 0}
    fila_obras = [("capital", "quartel"), ("colina", "mina"), ("capital", "armazem"), ("capital", "celeiro"), ("floresta", "serraria")]

    def __init__(self, reino):
        super().__init__(reino)
        self.alvo_guerra: str | None = None

    def aceita(self, v, t):
        tipos = {c["tipo"] for c in t["clausulas"]}
        if "fim_de_guerra" in tipos:
            meus = sum(sum(c["soldados"] for c in e["companhias"]) for e in v["exercitos"])
            return meus < 300 or v["dia"] >= 20
        return "nao_agressao" not in tipos and super().aceita(v, t)

    def especifico(self, v, agora, fator):
        out = []
        est = v["estoque"]
        dia = v["dia"]
        treinando = sum(1 for a in v["acoes_em_andamento"] if a["tipo"] == "recrutar")
        tem_quartel = any(c["tipo"] == "quartel" and c["nivel"] >= 1 for p in self.provincias(v) for c in p["construcoes"].values())
        meus = sum(sum(c["soldados"] for c in e["companhias"]) for e in v["exercitos"])
        cap = v["reino"]["capital"]
        if tem_quartel and dia <= 16 and treinando < 2 and meus < 1200 and est["ouro"] > 300 and est["ferro"] >= 60 and cap:
            out.append(self.acao("recrutar", "preparar campanha", provincia=cap, tipo="infantaria", quantidade=2))
        # junta os exércitos parados na capital
        parados = [e for e in v["exercitos"] if e["provincia"] == cap and e["movimento"] is None and e["batalha"] is None]
        if len(parados) >= 2:
            out.append(self.acao("formar_exercito", exercitos=[e["id"] for e in parados]))
        guerras = v["guerras"]
        if dia >= 6 and not guerras and self.alvo_guerra is None and meus >= 700:
            alvo = sorted(v["relacoes"])[-1] if v["relacoes"] else None
            if alvo:
                self.alvo_guerra = alvo
                out.append(self.acao("declarar_guerra", "expandir para o oeste", alvo=alvo, romper_tratados=True))
        ativa = [g for g in guerras if g["estado"] == "ativa"]
        if ativa:
            inimigo = ativa[0]["alvo"] if ativa[0]["agressor"] == self.reino else ativa[0]["agressor"]
            for e in v["exercitos"]:
                if e["movimento"] is not None or e["batalha"] is not None:
                    continue
                soldados = sum(c["soldados"] for c in e["companhias"])
                so_milicia = all(c["tipo"] == "milicia" for c in e["companhias"])
                local = next((p for p in v["provincias"] if p["id"] == e["provincia"]), None)
                if local and local["dono"] == inimigo:
                    em_saque = any(a["tipo"] == "saquear" for a in v["acoes_em_andamento"])
                    if not em_saque and f"saque:{local['id']}:{dia}" not in self.feitas:
                        self.feitas.add(f"saque:{local['id']}:{dia}")
                        out.append(self.acao("saquear", exercito=e["id"]))
                    continue
                if so_milicia and len(e["companhias"]) <= 2:
                    continue
                if soldados >= 500 and e["provincia"] == cap and f"marcha:{e['id']}:{dia}" not in self.feitas:
                    self.feitas.add(f"marcha:{e['id']}:{dia}")
                    alvos = [p["id"] for p in v["visiveis"] if p["dono"] == inimigo]
                    destino = sorted(alvos)[0] if alvos else f"prov_{inimigo[-1]}2"
                    milicias = [i for i, c in enumerate(e["companhias"]) if c["tipo"] == "milicia"]
                    if milicias and len(milicias) < len(e["companhias"]):
                        out.append(self.acao("dividir_exercito", "milícia fica em casa", exercito=e["id"], companhias=milicias))
                    out.append(self.acao("mover_exercito", "avançar", exercito=e["id"], destino=destino, postura="ofensiva"))
            if dia >= 20 and f"paz:{dia}" not in self.feitas:
                self.feitas.add(f"paz:{dia}")
                out.append(self.acao("propor_paz", "guerra longa demais", alvo=inimigo))
        return out


ARQUETIPOS = {"fazendeiro": Fazendeiro, "mercador": Mercador, "conquistador": Conquistador}


def criar_bots(estado: dict) -> dict[str, Bot]:
    return {rid: ARQUETIPOS[r["arquetipo_bot"]](rid) for rid, r in sorted(estado["reinos"].items())}


__all__ = ["Bot", "Fazendeiro", "Mercador", "Conquistador", "criar_bots", "HORA", "DIA"]
