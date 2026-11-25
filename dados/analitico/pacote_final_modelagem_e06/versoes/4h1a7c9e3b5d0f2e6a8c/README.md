# Pacote final de modelagem E06

Pacote final da primeira rodada de modelagem, exclusivamente com dados do Transferegov. A versão é `4h1a7c9e3b5d0f2e6a8c`.

Use `data/train.parquet`, `data/validation.parquet` e `data/test.parquet`. Cada arquivo contém os preditores M1+; `data/feature_sets.json` define as colunas M1 (seis) e M1+ (sete). O alvo é `y_1_sem_desembolso_365`. Os 242 censurados estão em `data/censored.parquet` e não entram nas partições supervisionadas.

Valide o pacote executando `python verify_package.py` com Python 3.12 x64, pandas e pyarrow compatíveis. Nenhum modelo foi treinado nesta etapa.
