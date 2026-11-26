# Protótipo do motor do mundo

Versão 0.1, 26/11/2026. Segue as regras de [`regras-do-mundo.md`](regras-do-mundo.md) (versão 0.1).

Este documento explica como rodar o protótipo, como ele está organizado, o que ficou simplificado ou de fora e o que as primeiras simulações mostraram sobre o balanceamento.

## Como rodar

Requisitos: Python 3.11 ou mais novo.

```bash
pip install -e ".[dev,postgres]"

# Simulador acelerado: uma era de teste inteira (28 dias de mundo) em menos de 1 segundo
python -m arena.simulador --dias 28 --semente 42

# Guarda o log em JSON Lines para estudar depois
python -m arena.simulador --dias 28 --log saida/era-42.jsonl

# Testes (o teste de PostgreSQL só roda com ARENA_TEST_PG apontando para um banco descartável)
pytest
ARENA_TEST_PG=postgresql://usuario@localhost:5432/teste pytest tests/test_postgres.py
```

Servidor com API e PostgreSQL, com os 3 reinos governados por bots e o relógio acelerado (1 dia de mundo a cada 4 minutos):

```bash
docker compose up --build
curl localhost:8000/v1/mundo
curl -H "Authorization: Bearer dev-reino_a" localhost:8000/v1/estado
curl -H "Authorization: Bearer dev-admin" localhost:8000/admin/verificar
```

A documentação interativa da API fica em `http://localhost:8000/docs`. Para governar um reino por fora (no lugar do bot), tire-o de `ARENA_BOTS` e use o token dele. As variáveis de ambiente estão no topo de [`arena/api.py`](../arena/api.py).

## Arquitetura

```
ação do reino ──▶ validar (lê o estado) ──▶ evento acao_aceita ──▶ redutor ──▶ estado
relógio ──▶ virada do dia / tick / agenda / combate ──▶ eventos ──▶ redutor ──▶ estado
                                                         │
                                                         └──▶ log (memória, JSON Lines ou PostgreSQL)
```

- **O estado só muda por redutores.** Cada tipo de evento tem um redutor que aplica o fato. O código de decisão (tick, batalha, validação de ações) lê o estado e emite eventos, mas nunca escreve nele. Assim, refazer o log do zero dá o mesmo estado, byte a byte. O teste de era completa e a rota `/admin/verificar` conferem isso pelo hash do estado.
- **Os eventos guardam fatos, não comandos.** O tick econômico grava os valores resultantes (estoque, felicidade, população). O replay não recalcula as fórmulas, então uma mudança de regra não altera o passado. Isso combina com a coluna `versao_regras` do log.
- **A agenda faz parte do estado.** Conclusões de obras, chegadas de exércitos e caravanas, rodadas de combate, vigência de guerras e pagamentos de tratados ficam numa agenda dentro do estado, criada pelos redutores. A ordem dentro de um instante segue a seção 18.2: virada do dia, tick, agenda, combate e, por último, as ações dos reinos.
- **Aleatoriedade sem estado** (seção 18.3): cada sorteio é `sha256(semente, tipo, objeto, instante)`. O replay não precisa guardar os números sorteados.
- **Ids determinísticos** (`acao_0001`, `exe_0004`, `evt_00000123`): o contador avança no redutor do evento que cria o objeto.
- **Relógio separado do motor.** O motor só avança quando alguém pede (`avancar_ate`). O relógio pode ser o real (UTC), acelerado ou manual. O simulador usa um relógio simulado hora a hora.

| Módulo | Conteúdo |
|---|---|
| `arena/regras.py` | Tabelas do documento (biomas, construções, unidades, leis, parâmetros da era) |
| `arena/mapa.py` | Mapa de teste com 3 reinos, 3 terras selvagens e a cidade livre Porto Livre |
| `arena/motor.py` | Relógio, emissão de eventos, agenda e envio de ações |
| `arena/redutor.py` | Registro dos redutores e da agenda |
| `arena/economia.py` | Tick de 1 hora, safras, felicidade, população, virada do dia, migração |
| `arena/acoes.py` | Cota, validação, idempotência, ciclo de vida e ações de governo |
| `arena/militar.py` | Recrutamento, movimento, batalha, cerco, saque, ocupação, anexação, guerra |
| `arena/diplomacia.py` | Mensagens, tratados, pagamentos, inadimplência e reputação |
| `arena/comercio.py` | Caravanas entre reinos e mercado das cidades livres |
| `arena/ranking.py` | Ranking diário e final da era |
| `arena/visao.py` | O que cada reino vê (`/v1/estado`) e os dados públicos (`/v1/mundo`) |
| `arena/armazenamento.py` | Log em memória, em JSON Lines e no PostgreSQL (com índice por reino e gatilho que impede UPDATE e DELETE) |
| `arena/bots.py` | Bots de regras: fazendeiro, mercador e conquistador |
| `arena/simulador.py` | Modo acelerado e verificação de replay |
| `arena/api.py` | API FastAPI da seção 17.2 |

## O mapa de teste

Três reinos simétricos, cada um com capital de planície (2.500 pessoas), floresta e colina com ferro (2.000 cada). Entre cada par de reinos há um pântano selvagem, e os três pântanos se ligam a Porto Livre, no centro. Cada capital fica a 4 trechos da outra, e Porto Livre a 3 trechos de cada capital.

| Reino | Bot | Estilo |
|---|---|---|
| Aurel (`reino_a`) | fazendeiro | Fazendas, armazéns, templo e teatro. Propõe não agressão a todos |
| Vel (`reino_b`) | mercador | Serraria e mina, vende excedente no mercado, propõe troca recorrente |
| Dornas (`reino_c`) | conquistador | Quartel e infantaria, declara guerra no dia 6, saqueia e ocupa |

## Interpretações adotadas

Onde o documento deixa margem, o protótipo seguiu estas leituras. Todas estão abertas a revisão.

- **Compressão (fator 4).** Valem comprimidas todas as durações de processo: obras, treino, movimento, leis (24 h viram 6 h), propostas de tratado (48 h viram 12 h), declaração de guerra (12 h viram 3 h), ocupação e saque (12 h viram 3 h), anexação, duração de tratados, tréguas e prazos de inatividade de guerra. O que não é comprimido: o tick de 1 hora, a virada do dia às 00:00 UTC, a cota diária e o ranking diário.
- **Taxas diárias** (produção, consumo, soldo, manutenção, deterioração, crescimento, migração, recuperação do mercado, volta da reputação) são multiplicadas por 4. A fórmula da colheita já é por ciclo e fica igual.
- **Felicidade** anda 20% da distância até o alvo por tick (5% × fator).
- **Impostos e ofícios** entram a cada tick (1/24 da receita diária). Ofícios usam o multiplicador de ouro do bioma.
- **Valor de terra** = multiplicadores de comida, madeira e ouro do bioma + metade da riqueza de cada jazida.
- **Província ocupada** não produz, não paga impostos e não consome do estoque do dono.
- **Saque** leva 10% do estoque de cada recurso, até 300 por recurso, como na seção 20.1.

## Simplificações e o que ficou de fora

### Simplificado

| Tema | Como está no protótipo |
|---|---|
| Mapa | Fixo e simétrico, com 3 reinos. Não há gerador com semente nem estradas prontas |
| Caravanas | O risco de bandidos é sorteado na chegada, uma vez por terra selvagem do caminho, e não trecho a trecho. Não há escolta, pedágio, captura por exército inimigo nem o evento `caravana_entrou_em_provincia` |
| Mercado | A ordem executa na chegada até onde o limite de preço permite e o resto volta na hora. Não há espera de 72 horas, nem `cancelar_oferta`. A integral do preço é aproximada unidade a unidade. Só há uma cidade livre |
| Presentes | `presentear` transfere na hora com a taxa de 10%, mesmo entre reinos não vizinhos |
| Batalha | Recuo e rendição por exército, não por lado. Sem generais (`mult_general` = 1). A fuga de `evitar_combate` só vale para o exército que chega |
| Recrutamento | O limite de 20% conta os soldados cedidos pela província e só volta com `dispensar` |
| Perda da capital | A nova capital é escolhida automaticamente (primeira província em ordem de id). Não há `mudar_capital` nem o período de −10 de felicidade |
| Ranking | Cooperação conta tratados ativos por dia, sem checar se foram cumpridos. Não conta missões de cidades livres nem povos integrados |
| `cancelar_acao` | Funciona para obras, melhorias, recrutamento e leis. Não para movimento e caravanas |
| Reputação | Faltam o +1 por 7 dias de tratado cumprido, o −10 extra por declarar guerra a quem tinha tratado e o +2 por ajudar reino atingido por evento |
| Visibilidade | Visão completa e parcial por província, mas sem a soma de visão entre aliados e sem o atraso de 24 h para o público |

### De fora (ficam para as próximas etapas)

- World AI e eventos de mundo (seção 12), incluindo o calendário mínimo e o fim de era temático. A era termina com `era_encerrada` e o ranking final.
- Povos neutros, NPCs, monstros, covis, ruínas e mercenários (seção 13). As ações `colonizar`, `explorar_ruina`, `contratar_mercenarios` e `enviar_emissario` respondem `acao_desconhecida`.
- Personagens notáveis (governante, general, conselheiro).
- Regente padrão (seção 14). O `ack` é registrado, mas não liga a regência.
- Magia, éter e pesquisa (já desligados no MVP pelo documento).
- Cláusulas `passagem_livre`, `defesa_mutua`, `cessao_territorio`, `visao_compartilhada` e `exclusividade_comercial`. Com isso, não há alianças nem passagem de exércitos por reino neutro.
- Revolta que vira independência depois de 7 dias, e repressão por exército. A revolta para a produção e acaba quando a felicidade passa de 35.
- Corte no exílio e reino extinto.
- Bônus de outono, bônus de conselheiro e efeito de `rotas_abertas` e `academias` (a lei existe, mas sem efeito além da cultura).
- `definir_pedagio`, moderação de mensagens públicas e categoria assistida.
- WebSocket (`/v1/stream`), webhook, `POST /v1/regencia` e retratos diários para acelerar o replay. O replay de uma era inteira leva menos de 1 segundo, então os retratos ainda não fazem falta.
- **Redis.** O documento já diz que o Redis não é fonte de verdade. No protótipo, a agenda vive no estado, a cota é contada pelo motor e o limite de taxa fica em memória. O Redis entra junto com o WebSocket e com mais de um processo de API.
- Os bots guardam a própria memória em processo. Ao reiniciar o servidor, o mundo volta igual pelo log, mas os bots recomeçam do zero e podem repetir propostas.

## O que as primeiras simulações mostraram

Rodei a era de teste completa (28 dias, fator 4) com as sementes 1, 2, 3 e 42. O replay deu idêntico em todas. Os números abaixo são horas de tick com mais de 50% de fome (de 168 horas por estação):

| Reino | Primavera | Verão | Outono | Inverno |
|---|---|---|---|---|
| Aurel (fazendeiro) | 48 a 49 | 40 a 47 | 9 a 11 | 70 a 73 |
| Vel (mercador) | 50 a 58 | 5 a 28 | 3 a 12 | 90 a 106 |
| Dornas (conquistador) | 49 a 53 | 42 a 43 | 7 a 41 | 105 a 108 |

Houve 6 ou 7 revoltas por era, e o conquistador anexou 1 província de Vel em todas as sementes. O fazendeiro ficou em primeiro nas quatro, mas com um mapa fixo e só três bots isso ainda não diz nada sobre equilíbrio de arquétipos.

Os bots são simples, mas a fome aparece para todos e por causas que estão nas regras, não nos bots:

1. **Fome na largada.** A primeira colheita só chega com 42 horas, e o estoque inicial de 2.000 comida cobre umas 18 horas de consumo (6.800 bocas, cerca de 2.700 comida por dia com o fator 4). Todo reino passa umas 24 horas com fome antes da primeira safra. Uma saída simples é desencontrar o início das safras (cada província começa num ponto diferente do ciclo) ou começar com mais comida.
2. **O inverno é inviável.** Com colheita a 40%, a produção cai para cerca de 1.150 comida por dia contra 2.700 de consumo. Seriam uns 10.000 de comida guardados para atravessar a estação, mas o teto do estoque é 2.000 mais 1.000 por armazém. Opções: colheita de inverno maior (por exemplo 70%), celeiro que também aumente o teto de comida, ou um consumo menor no inverno.
3. **O crescimento quase nunca acontece.** A regra pede comida para 7 dias em estoque, ou seja, umas 4.550 comida para 6.500 pessoas, acima do teto de 2.000. Sem 3 armazéns, nenhum reino cresce.
4. **Impasse da caravana.** Comprar comida no mercado exige caravana, e a caravana custa 1 comida por trecho. Com o estoque de comida zerado, o reino não consegue comprar comida. Vale isentar a caravana de compra de comida ou cobrar esse custo em ouro.

Esses quatro pontos são de balanceamento, não de motor. Ficam como proposta para a próxima revisão do documento de regras, e o simulador já serve para testar cada ajuste.
