"""Log de eventos só com inserção (seção 18.1).

Três implementações com a mesma interface:
- `MemoriaEventos`: para testes e para o simulador acelerado.
- `ArquivoEventos`: JSON Lines em disco, útil para guardar a saída do simulador.
- `PostgresEventos`: tabela `eventos` + índice por reino, como no documento.

O `seq` por reino (seção 17.4) é derivado de `seq_global` filtrado por
`visivel_para`. Eventos públicos entram no índice de todos os reinos.
"""

from __future__ import annotations

import json
import os
from typing import Iterable, Iterator, Protocol

PUBLICO = "publico"


class ArmazemEventos(Protocol):
    def anexar(self, ev: dict) -> None: ...
    def todos(self) -> Iterator[dict]: ...
    def ultimo_seq(self) -> int: ...
    def eventos_do_reino(self, reino: str, desde: int = 0, limite: int = 500) -> list[dict]: ...
    def ultimo_seq_reino(self, reino: str) -> int: ...


def destinatarios(ev: dict, reinos: Iterable[str]) -> list[str]:
    vis = ev["visivel_para"]
    if PUBLICO in vis:
        return sorted(reinos)
    return [r for r in vis if r in set(reinos)]


def envelope_para_reino(ev: dict, seq_reino: int) -> dict:
    """Formato de entrega da seção 17.4."""
    from .tempo import iso

    vis = ev["visivel_para"]
    return {
        "seq": seq_reino,
        "id": ev["id"],
        "tipo": ev["tipo"],
        "ocorrido_em": iso(ev["ocorrido_em"]),
        "visibilidade": "publico" if PUBLICO in vis else ("privado" if len(vis) == 1 else "parcial"),
        "origem": ev["origem"],
        "causa": ev["causa"],
        "dados": ev["dados"],
    }


def _reinos_do_evento_inicial(ev: dict) -> list[str]:
    return sorted(ev["dados"]["estado_inicial"]["reinos"].keys())


class MemoriaEventos:
    def __init__(self) -> None:
        self._eventos: list[dict] = []
        self._indice: dict[str, list[int]] = {}
        self._reinos: list[str] = []

    def anexar(self, ev: dict) -> None:
        if ev["seq_global"] != len(self._eventos) + 1:
            raise ValueError("seq_global fora de ordem")
        if ev["tipo"] == "era_iniciada":
            self._reinos = _reinos_do_evento_inicial(ev)
            self._indice = {r: [] for r in self._reinos}
        self._eventos.append(ev)
        for r in destinatarios(ev, self._reinos):
            self._indice[r].append(ev["seq_global"])

    def todos(self) -> Iterator[dict]:
        return iter(list(self._eventos))

    def ultimo_seq(self) -> int:
        return len(self._eventos)

    def eventos_do_reino(self, reino: str, desde: int = 0, limite: int = 500) -> list[dict]:
        idx = self._indice.get(reino, [])
        out = []
        for i in range(desde, min(len(idx), desde + limite)):
            out.append(envelope_para_reino(self._eventos[idx[i] - 1], i + 1))
        return out

    def ultimo_seq_reino(self, reino: str) -> int:
        return len(self._indice.get(reino, []))


class ArquivoEventos(MemoriaEventos):
    """Log em JSON Lines. Carrega o arquivo existente e anexa no fim."""

    def __init__(self, caminho: str) -> None:
        super().__init__()
        self.caminho = caminho
        if os.path.exists(caminho):
            with open(caminho, encoding="utf-8") as f:
                for linha in f:
                    if linha.strip():
                        super().anexar(json.loads(linha))
        self._arquivo = open(caminho, "a", encoding="utf-8")

    def anexar(self, ev: dict) -> None:
        super().anexar(ev)
        self._arquivo.write(json.dumps(ev, ensure_ascii=False, sort_keys=True) + "\n")

    def fechar(self) -> None:
        self._arquivo.close()


ESQUEMA_SQL = """
CREATE TABLE IF NOT EXISTS eventos (
    seq_global    BIGINT PRIMARY KEY,
    id            TEXT NOT NULL UNIQUE,
    ocorrido_em   TIMESTAMPTZ NOT NULL,
    ocorrido_ms   BIGINT NOT NULL,
    tipo          TEXT NOT NULL,
    origem        TEXT NOT NULL,
    causa         TEXT,
    dados         JSONB NOT NULL,
    visivel_para  TEXT[] NOT NULL,
    versao_regras TEXT NOT NULL,
    extra         JSONB
);
CREATE TABLE IF NOT EXISTS indice_reino (
    reino       TEXT NOT NULL,
    seq         BIGINT NOT NULL,
    seq_global  BIGINT NOT NULL REFERENCES eventos(seq_global),
    PRIMARY KEY (reino, seq)
);
-- Log imutável: proíbe UPDATE e DELETE na tabela de eventos.
CREATE OR REPLACE FUNCTION eventos_imutaveis() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'o log de eventos é só de inserção';
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS eventos_sem_alteracao ON eventos;
CREATE TRIGGER eventos_sem_alteracao BEFORE UPDATE OR DELETE ON eventos
    FOR EACH ROW EXECUTE FUNCTION eventos_imutaveis();
"""


class PostgresEventos:
    """Log no PostgreSQL. Cada `anexar` é uma transação (evento + índice)."""

    CAMPOS = ("seq_global", "id", "ocorrido_em", "tipo", "origem", "causa", "dados", "visivel_para", "versao_regras")

    def __init__(self, dsn: str) -> None:
        import psycopg

        self._psycopg = psycopg
        self.con = psycopg.connect(dsn, autocommit=False)
        with self.con.cursor() as cur:
            cur.execute(ESQUEMA_SQL)
        self.con.commit()
        self._reinos = self._carregar_reinos()
        self._ultimo = self._consultar_ultimo()
        self._seq_reino = {r: self._consultar_ultimo_reino(r) for r in self._reinos}

    def _carregar_reinos(self) -> list[str]:
        with self.con.cursor() as cur:
            cur.execute("SELECT dados FROM eventos WHERE tipo = 'era_iniciada' ORDER BY seq_global LIMIT 1")
            linha = cur.fetchone()
        self.con.commit()
        return sorted(linha[0]["estado_inicial"]["reinos"].keys()) if linha else []

    def _consultar_ultimo(self) -> int:
        with self.con.cursor() as cur:
            cur.execute("SELECT COALESCE(MAX(seq_global), 0) FROM eventos")
            n = cur.fetchone()[0]
        self.con.commit()
        return n

    def _consultar_ultimo_reino(self, reino: str) -> int:
        with self.con.cursor() as cur:
            cur.execute("SELECT COALESCE(MAX(seq), 0) FROM indice_reino WHERE reino = %s", (reino,))
            n = cur.fetchone()[0]
        self.con.commit()
        return n

    def anexar(self, ev: dict) -> None:
        from psycopg.types.json import Jsonb

        if ev["seq_global"] != self._ultimo + 1:
            raise ValueError("seq_global fora de ordem")
        if ev["tipo"] == "era_iniciada":
            self._reinos = _reinos_do_evento_inicial(ev)
            self._seq_reino = {r: 0 for r in self._reinos}
        extra = {k: v for k, v in ev.items() if k not in self.CAMPOS}
        with self.con.cursor() as cur:
            cur.execute(
                "INSERT INTO eventos (seq_global, id, ocorrido_em, ocorrido_ms, tipo, origem, causa, dados, visivel_para, versao_regras, extra)"
                " VALUES (%s, %s, to_timestamp(%s / 1000.0), %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    ev["seq_global"], ev["id"], ev["ocorrido_em"], ev["ocorrido_em"], ev["tipo"], ev["origem"],
                    ev["causa"], Jsonb(ev["dados"]), ev["visivel_para"], ev["versao_regras"], Jsonb(extra),
                ),
            )
            novos = {}
            for r in destinatarios(ev, self._reinos):
                novos[r] = self._seq_reino[r] + 1
                cur.execute(
                    "INSERT INTO indice_reino (reino, seq, seq_global) VALUES (%s, %s, %s)", (r, novos[r], ev["seq_global"])
                )
        self.con.commit()
        self._ultimo = ev["seq_global"]
        self._seq_reino.update(novos)

    def _linha_para_evento(self, linha) -> dict:
        seq_global, id_, ms, tipo, origem, causa, dados, vis, versao, extra = linha
        ev = {
            "seq_global": seq_global, "id": id_, "ocorrido_em": ms, "tipo": tipo, "origem": origem,
            "causa": causa, "dados": dados, "visivel_para": list(vis), "versao_regras": versao,
        }
        ev.update(extra or {})
        return ev

    def todos(self) -> Iterator[dict]:
        with self.con.cursor() as cur:
            cur.execute(
                "SELECT seq_global, id, ocorrido_ms, tipo, origem, causa, dados, visivel_para, versao_regras, extra"
                " FROM eventos ORDER BY seq_global"
            )
            linhas = cur.fetchall()
        self.con.commit()
        return iter([self._linha_para_evento(l) for l in linhas])

    def ultimo_seq(self) -> int:
        return self._ultimo

    def eventos_do_reino(self, reino: str, desde: int = 0, limite: int = 500) -> list[dict]:
        with self.con.cursor() as cur:
            cur.execute(
                "SELECT i.seq, e.seq_global, e.id, e.ocorrido_ms, e.tipo, e.origem, e.causa, e.dados, e.visivel_para,"
                " e.versao_regras, e.extra FROM indice_reino i JOIN eventos e ON e.seq_global = i.seq_global"
                " WHERE i.reino = %s AND i.seq > %s ORDER BY i.seq LIMIT %s",
                (reino, desde, limite),
            )
            linhas = cur.fetchall()
        self.con.commit()
        return [envelope_para_reino(self._linha_para_evento(l[1:]), l[0]) for l in linhas]

    def ultimo_seq_reino(self, reino: str) -> int:
        return self._seq_reino.get(reino, 0)

    def fechar(self) -> None:
        self.con.close()
