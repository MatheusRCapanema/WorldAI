"""Tabelas de regras do documento docs/regras-do-mundo.md.

Os números aqui são os da versão 0.1 do documento. Cada tabela cita a seção
de origem. Durações estão em horas da era completa; o motor aplica o fator de
compressão da era (seção 19) por meio de `Parametros`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

VERSAO_REGRAS = "0.2"

RECURSOS = ("comida", "madeira", "ferro", "ouro")  # éter desligado no MVP (seção 11)

# Seção 3.3: multiplicadores por bioma e tempo de travessia (horas).
BIOMAS = {
    "planicie": {"comida": 1.3, "madeira": 0.6, "ferro": 0.5, "ouro": 1.0, "defesa": 1.0, "travessia": 8},
    "floresta": {"comida": 0.8, "madeira": 1.5, "ferro": 0.5, "ouro": 0.8, "defesa": 1.2, "travessia": 12},
    "colina": {"comida": 0.9, "madeira": 0.8, "ferro": 1.3, "ouro": 1.1, "defesa": 1.3, "travessia": 12},
    "montanha": {"comida": 0.4, "madeira": 0.6, "ferro": 1.6, "ouro": 1.3, "defesa": 1.6, "travessia": 24},
    "pantano": {"comida": 0.7, "madeira": 0.9, "ferro": 0.3, "ouro": 0.7, "defesa": 1.4, "travessia": 18},
    "costa": {"comida": 1.1, "madeira": 0.7, "ferro": 0.4, "ouro": 1.2, "defesa": 1.0, "travessia": 8},
}
MULT_JAZIDA = {0: 0.0, 1: 1.0, 2: 1.5, 3: 2.0}

# Seção 2.2: estações.
ESTACOES = ("primavera", "verao", "outono", "inverno")
MULT_COLHEITA_ESTACAO = {"primavera": 1.0, "verao": 1.2, "outono": 1.0, "inverno": 0.7}  # inverno 0,4 -> 0,7 (regras 0.2)
MULT_CRESCIMENTO_ESTACAO = {"primavera": 1.5, "verao": 1.0, "outono": 1.0, "inverno": 1.0}

# Seção 5.2: setores.
SETORES = ("agricultura", "madeira", "mineracao", "oficios", "cultura", "ocioso")
ALOCACAO_PADRAO = {"agricultura": 60, "madeira": 15, "mineracao": 10, "oficios": 15, "cultura": 0, "ocioso": 0}

# Seção 5.3: taxa base por 100 trabalhadores por dia.
TAXA_BASE = {"madeira": 10.0, "ferro": 4.0, "ouro_mina": 3.0, "oficios": 2.0, "cultura": 1.0}
COLHEITA_POR_100_POR_DIA = 15.0
DIAS_SAFRA = 7

# Seção 5.7: leis. custo em ouro, custo diário, efeitos.
LEIS = {
    "servico_militar": {"custo": 50, "diario": 0, "felicidade": -5},
    "festas_publicas": {"custo": 100, "diario": 10, "felicidade": 8, "cultura": 2},
    "rotas_abertas": {"custo": 50, "diario": 0, "felicidade": 0},
    "racionamento": {"custo": 0, "diario": 0, "felicidade": -10},
    "liberdade_de_culto": {"custo": 50, "diario": 0, "felicidade": 4, "cultura": 1},
    "lei_marcial": {"custo": 0, "diario": 0, "felicidade": -15},
    "academias": {"custo": 150, "diario": 15, "felicidade": 0, "cultura": 2},
}
MAX_LEIS = 3


@dataclass(frozen=True)
class Construcao:
    custo: dict
    duracao_h: int
    manutencao: int
    exige_jazida: bool = False
    exige_costa: bool = False
    desligada: bool = False


# Seção 6.
CONSTRUCOES = {
    "fazenda": Construcao({"madeira": 60, "ouro": 20}, 24, 1),
    "serraria": Construcao({"madeira": 40, "ouro": 30}, 24, 1),
    "mina": Construcao({"madeira": 80, "ouro": 40}, 48, 2, exige_jazida=True),
    "mercado": Construcao({"madeira": 80, "ouro": 60}, 48, 2),
    "armazem": Construcao({"madeira": 100, "ouro": 20}, 24, 1),
    "celeiro": Construcao({"madeira": 60, "ouro": 20}, 24, 0),
    "moradia": Construcao({"madeira": 80, "ouro": 20}, 48, 0),
    "templo": Construcao({"madeira": 100, "ferro": 20, "ouro": 80}, 72, 3),
    "teatro": Construcao({"madeira": 120, "ouro": 120}, 72, 4),
    "biblioteca": Construcao({"madeira": 100, "ferro": 30, "ouro": 100}, 72, 3),
    "quartel": Construcao({"madeira": 120, "ferro": 40, "ouro": 60}, 48, 2),
    "muralha": Construcao({"madeira": 150, "ferro": 80, "ouro": 50}, 72, 2),
    "porto": Construcao({"madeira": 150, "ferro": 20, "ouro": 60}, 72, 2, exige_costa=True),
    "torre_de_eter": Construcao({"madeira": 100, "ferro": 100, "ouro": 150}, 96, 5, desligada=True),
}
MAX_NIVEL = 3

# Bônus de produção por nível (seção 6).
BONUS_CONSTRUCAO = {
    "fazenda": ("colheita", 0.20),
    "serraria": ("madeira", 0.25),
    "mina": ("mineracao", 0.30),
    "mercado": ("oficios", 0.20),
}
BONUS_MERCADO_IMPOSTO = 0.15
FELICIDADE_CONSTRUCAO = {"templo": 5, "teatro": 4}
CULTURA_CONSTRUCAO = {"templo": 2, "teatro": 4, "biblioteca": 1}


@dataclass(frozen=True)
class Unidade:
    ataque: float
    defesa: float
    custo: dict
    treino_h: int
    soldo: int
    quartel: int = 0
    so_no_reino: bool = False


# Seção 10.1.
UNIDADES = {
    "milicia": Unidade(2, 3, {"ouro": 20}, 24, 1, so_no_reino=True),
    "infantaria": Unidade(4, 5, {"ouro": 50, "ferro": 20}, 48, 2),
    "arqueiros": Unidade(5, 3, {"ouro": 50, "madeira": 30, "ferro": 10}, 48, 2),
    "cavalaria": Unidade(7, 4, {"ouro": 100, "ferro": 40, "comida": 50}, 96, 4, quartel=2),
    "cerco": Unidade(1, 1, {"ouro": 120, "madeira": 150, "ferro": 40}, 96, 3, quartel=3),
}
SOLDADOS_POR_COMPANHIA = 100

# Seção 9.4: cláusulas suportadas no protótipo.
CLAUSULAS_SUPORTADAS = (
    "pagamento_unico",
    "pagamento_periodico",
    "troca_recorrente",
    "nao_agressao",
    "tregua",
    "fim_de_guerra",
)

# Seção 8.3: mercado.
MERCADO_BASE = {
    "comida": {"P0": 0.5, "E0": 20000.0},
    "madeira": {"P0": 0.8, "E0": 10000.0},
    "ferro": {"P0": 2.0, "E0": 4000.0},
}
TAXA_MERCADO = 0.05
CAPACIDADE_CARAVANA = 500


@dataclass(frozen=True)
class Parametros:
    """Parâmetros da era (seção 19). `fator` é o fator de compressão."""

    fator: int = 4
    duracao_era_dias: int = 28
    dias_por_estacao: int = 7
    ordens_por_dia: int = 200
    mensagens_por_dia: int = 50
    estoque_base: int = 2000
    estoque_por_armazem: int = 1000
    estoque_por_celeiro: int = 1000  # só comida (regras 0.2)
    dias_comida_crescimento: int = 3  # era 7 (regras 0.2)
    ouro_por_trecho_sem_comida: int = 2  # caravana sem comida paga em ouro (regras 0.2)
    capacidade_moradia_base: int = 3000
    capacidade_por_moradia: int = 1500
    inicio_estoque: dict = field(
        default_factory=lambda: {"comida": 2000.0, "madeira": 600.0, "ferro": 150.0, "ouro": 800.0}
    )

    def duracao(self, horas_era_completa: float) -> int:
        """Duração em ms na era corrente: divide pelo fator, mínimo de 1 hora."""
        h = max(1.0, horas_era_completa / self.fator)
        return int(round(h * 3_600_000))

    def dias_jogo(self, dias: float) -> int:
        """Prazo em 'dias de regra' convertido para ms reais comprimidos."""
        return self.duracao(dias * 24)

    @property
    def horas_safra(self) -> int:
        return max(1, round(DIAS_SAFRA * 24 / self.fator))

    def como_dict(self) -> dict:
        return {
            "fator": self.fator,
            "duracao_era_dias": self.duracao_era_dias,
            "dias_por_estacao": self.dias_por_estacao,
            "ordens_por_dia": self.ordens_por_dia,
            "mensagens_por_dia": self.mensagens_por_dia,
            "estoque_base": self.estoque_base,
            "estoque_por_armazem": self.estoque_por_armazem,
            "estoque_por_celeiro": self.estoque_por_celeiro,
            "dias_comida_crescimento": self.dias_comida_crescimento,
            "ouro_por_trecho_sem_comida": self.ouro_por_trecho_sem_comida,
            "capacidade_moradia_base": self.capacidade_moradia_base,
            "capacidade_por_moradia": self.capacidade_por_moradia,
            "inicio_estoque": dict(self.inicio_estoque),
        }

    @classmethod
    def de_dict(cls, d: dict) -> "Parametros":
        return cls(**d)
