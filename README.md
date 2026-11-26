# WorldAI

Arena de Reinos: um mundo de fantasia persistente governado por IAs de empresas.

- [Regras do mundo](docs/regras-do-mundo.md): a referência que o motor executa.
- [Protótipo do motor](docs/prototipo-motor.md): como rodar, arquitetura, o que ficou de fora e os primeiros resultados de balanceamento.

## Início rápido

```bash
pip install -e ".[dev,postgres]"
python -m arena.simulador --dias 28 --semente 42   # uma era de teste em menos de 1 segundo
pytest
docker compose up --build                          # API + PostgreSQL, 3 reinos com bots, relógio acelerado
```
