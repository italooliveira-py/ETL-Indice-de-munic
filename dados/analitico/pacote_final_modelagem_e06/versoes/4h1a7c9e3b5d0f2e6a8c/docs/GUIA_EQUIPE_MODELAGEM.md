# Guia da equipe de modelagem

## Carregamento

Use Python 3.12 x64 com pandas, pyarrow e scikit-learn compatíveis. A partir deste diretório, execute `python verify_package.py` e depois leia `data/train.parquet`, `data/validation.parquet` e `data/test.parquet` com `pandas.read_parquet`.

## Contratos

O alvo é `y_1_sem_desembolso_365`. M1 usa seis preditores; M1+ acrescenta `valor_global_assinatura`. `modalidade` é categórica; os demais preditores são numéricos. IDs e datas são metadados.

Use pipelines do scikit-learn. Ajuste imputadores, encoders, escaladores e transformações somente no treino. Use `handle_unknown` para categorias novas e considere assimetria dos valores sem alterar os Parquets finais.

## Modelos e validação

A Entrega 6 deve recalcular um baseline operacional, regressão logística regularizada, árvore de decisão e Random Forest ou Gradient Boosting. A validação cruzada deve respeitar o tempo e a dependência municipal; `TimeSeriesSplit` não substitui a auditoria de observabilidade. O teste 2022–2023 só deve ser aberto após decisões de pré-processamento e hiperparâmetros.

Avalie PR-AUC, ROC-AUC, Brier, Log Loss, precisão, recall, F1, matriz de confusão e calibração. A métrica principal deve ser justificada com benefícios, custos e capacidade definidos pela equipe; não há valores B, C ou k neste pacote. Não use IDs como atributos.

## Uso responsável

O resultado é experimental e serve para priorização preventiva de acompanhamento. Ausência de desembolso em 365 dias não prova irregularidade, impacto social ou risco fiscal. Examine erros por ano, modalidade, município e perfil histórico antes de qualquer conclusão.
