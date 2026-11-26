# Checkpoint — E06

## Estado

- Plano executado, incluindo a aplicação aos instrumentos de 2024. Resultados em `docs/e06/RESULTADOS_E06.md`.
- Código em `src/e06/`, testes em `tests/test_e06.py`, configuração em `config.e06.json`.
- Saídas finais em `dados/modelagem/e06/`, com `manifesto.json` de hashes: registro, aberturas do teste, escolhas, previsões e quadros. Figuras em `docs/e06/figuras/`.
- Pacote `4h1a7c9e3b5d0f2e6a8c`, verificado antes de cada rodada. Depende da correção de hashes do PR #12.
- Ambiente: `requirements-e05-lock.txt` (Python 3.12, pandas 2.3.3, numpy 2.5.4, scikit-learn 1.9.1).

## Pendências

- Revisão da equipe.

## Reprodução

Com o ambiente do lock ativo e `data/silver` disponível:

```bash
python -m unittest tests.test_e06
python -m src.e06 --fase escolha --experimento A0
git add dados/modelagem/e06/escolhas/A0.json && git commit -m "Escolhas A0"
python -m src.e06 --fase teste --experimento A0
python -m src.e06 --fase prospectivo --experimento A0
python -m src.e06 --replicacao A0
python -m src.e06.resumo --publicar
```

Uma rodada nova grava em `output/e06/`. As escolhas versionadas em `dados/modelagem/e06/escolhas/` são as da execução publicada.
