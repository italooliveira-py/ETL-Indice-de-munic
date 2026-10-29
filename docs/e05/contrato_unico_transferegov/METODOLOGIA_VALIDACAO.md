# Metodologia de validação

O snapshot comum contém 867 instrumentos Transferegov: treino temporal de 2022, validação temporal de 2023 e backtest temporal de 2024. O ano de 2024 já havia sido observado em experimentos anteriores e não é tratado como teste externo cego.

Os folds são construídos uma única vez no treino de 2022 com `StratifiedGroupKFold`, `codigo_ibge` como grupo, seed 42 e cinco folds. Cada fold contém as duas classes e municípios disjuntos. A busca usa Average Precision e grades pequenas, declaradas no código.

Cada modelo usa `Pipeline` e `ColumnTransformer`. Imputação, codificação e escalonamento são ajustados dentro de cada fold. Logística, KNN, SVC e MLP são escalados; árvores e boosting não recebem escala, mas recebem exatamente as mesmas colunas brutas.

Depois da seleção pela CV de 2022, o modelo é ajustado em todo 2022. O limiar é escolhido somente em 2023 por balanced accuracy, com desempate por especificidade e F1. O modelo e o limiar são congelados antes do backtest de 2024.

A incerteza usa bootstrap pareado por município com as mesmas reamostragens para todos os modelos. A permutação do alvo é executada com hiperparâmetros congelados. MAE e RMSE são diagnósticos das probabilidades e não critérios de seleção.
