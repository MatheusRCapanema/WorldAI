"""Redutores: a única forma de mudar o estado do mundo.

Cada tipo de evento tem um redutor `aplicar(estado, evento)`. O motor decide
o que acontece (lendo o estado) e emite eventos; o redutor só aplica o fato.
Assim, refazer o log do zero dá exatamente o mesmo estado (seção 18.1).

Regra de ouro: o código de decisão nunca escreve no estado. Os testes de
replay comparam o estado ao vivo com o estado reconstruído e pegam qualquer
escrita fora de um redutor.
"""

from __future__ import annotations

import json
from typing import Callable

REDUTORES: dict[str, Callable[[dict, dict], None]] = {}

# Eventos que só informam (mensagens, avisos) e não mudam o estado.
INFORMATIVOS: set[str] = set()


def redutor(*tipos: str):
    def registrar(fn):
        for t in tipos:
            if t in REDUTORES:
                raise RuntimeError(f"redutor duplicado: {t}")
            REDUTORES[t] = fn
        return fn

    return registrar


def informativo(*tipos: str) -> None:
    INFORMATIVOS.update(tipos)


def agendar(estado: dict, evento: dict, instante: int, tipo: str, dados: dict, prioridade: int = 3) -> str:
    """Agenda um processo a partir de um redutor.

    `prioridade` segue a seção 18.2: 3 = eventos agendados, 4 = rodadas de combate.
    A ordem entre itens do mesmo instante é a ordem de agendamento.
    """
    k = estado["contadores"].setdefault("_agenda_sub", {})
    sub = k.get(str(evento["seq_global"]), 0)
    k[str(evento["seq_global"])] = sub + 1
    aid = f"ag_{evento['seq_global']}_{sub}"
    estado["agenda"][aid] = {
        "id": aid,
        "instante": instante,
        "prioridade": prioridade,
        "ordem": [evento["seq_global"], sub],
        "tipo": tipo,
        "dados": dados,
    }
    return aid


def desagendar(estado: dict, aid: str | None) -> None:
    if aid:
        estado["agenda"].pop(aid, None)


def aplicar(estado: dict, evento: dict) -> None:
    # Cópia própria: o redutor pode guardar pedaços do evento no estado, e o
    # estado muda depois. Sem a cópia, o evento guardado no log mudaria junto.
    evento = json.loads(json.dumps(evento))
    tipo = evento["tipo"]
    fn = REDUTORES.get(tipo)
    if fn is None and tipo not in INFORMATIVOS:
        raise KeyError(f"evento sem redutor: {tipo}")
    if fn is not None:
        fn(estado, evento)
    concluida = evento.get("agenda_concluida")
    if concluida:
        estado["agenda"].pop(concluida, None)
    # limpa o contador auxiliar de sub-agendamentos deste evento
    estado["contadores"].get("_agenda_sub", {}).pop(str(evento["seq_global"]), None)
    estado["agora"] = max(estado.get("agora", 0), evento["ocorrido_em"])
    estado["seq_global"] = evento["seq_global"]
