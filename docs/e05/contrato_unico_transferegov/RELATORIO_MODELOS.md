# Benchmark coletivo — contrato Transferegov de 365 dias

## Contexto

Os experimentos anteriores usavam contratos, janelas temporais e amostras diferentes. Por isso, este benchmark fixa um contrato comum, um snapshot único, os mesmos preditores e os mesmos folds para permitir comparação justa entre os candidatos.

## Contrato e execução

- Unidade: instrumento Transferegov.
- Alvo: `risco_atraso_primeiro_desembolso_365d`.
- Classe 0: desembolso positivo até o dia 365, inclusive.
- Classe 1: ausência de desembolso positivo nesse prazo ou primeiro desembolso após o dia 365.
- Treino e seleção de hiperparâmetros: coorte de 2022.
- Validação e escolha do limiar: coorte de 2023.
- Backtest temporal: coorte de 2024, já observada e não um teste externo cego.
- Validação cruzada: cinco folds `StratifiedGroupKFold`, agrupados por município (`codigo_ibge`), seed 42.
- Todos os candidatos usam os mesmos 867 registros, preditores e folds.

O snapshot tem 239 instrumentos em 2022, 386 em 2023 e 242 em 2024. O Gold usado somente para sua preparação foi a versão `65260a170ee18cd79501`, com manifesto SHA-256 `28E24585431DC29B0DA53B10FD0811B91A02BA79BD00484EA6297D9ABB84F5B5`.

## Modelos

Oito modelos candidatos: Regressão Logística, KNN, XGBoost, LightGBM, Random Forest, Árvore de Decisão, SVC e MLP.

Os dois baselines são `Dummy prior` e `Dummy most frequent`. Eles são referências de comparação, não candidatos equivalentes.

## Prevalência

Em 2023, foram 309 positivos em 386 registros, prevalência `0,8005`. Em 2024, foram 212 positivos em 242 registros, prevalência aproximada `0,8760`. Portanto, Average Precision elevado deve ser interpretado em relação ao baseline de prevalência, e não isoladamente.

## Validação de 2023

| Modelo | AP | Ganho AP | Limiar | ROC-AUC | Bal. acc. | Precisão | Recall | Especificidade | F1 | Matriz TN/FP/FN/TP |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| XGBoost | 0,8307 | 0,0302 | 0,9827 | 0,5671 | 0,5719 | 0,8340 | 0,7152 | 0,4286 | 0,7700 | 33/44/88/221 |
| Random Forest | 0,8211 | 0,0206 | 0,8908 | 0,5466 | 0,5701 | 0,8280 | 0,8414 | 0,2987 | 0,8347 | 23/54/49/260 |
| Decision Tree | 0,8195 | 0,0189 | 0,5000 | 0,5552 | 0,5554 | 0,8212 | 0,8770 | 0,2338 | 0,8482 | 18/59/38/271 |
| MLP | 0,8149 | 0,0144 | 0,5321 | 0,5094 | 0,5337 | 0,8462 | 0,2492 | 0,8182 | 0,3850 | 63/14/232/77 |
| Logística | 0,8081 | 0,0076 | 0,9816 | 0,5308 | 0,5460 | 0,8243 | 0,6375 | 0,4545 | 0,7190 | 35/42/112/197 |
| KNN | 0,8016 | 0,0011 | 0,9333 | 0,5052 | 0,5262 | 0,8101 | 0,8835 | 0,1688 | 0,8452 | 13/64/36/273 |
| Dummy prior | 0,8005 | 0,0000 | 0,5000 | 0,5000 | 0,5000 | 0,8005 | 1,0000 | 0,0000 | 0,8892 | 0/77/0/309 |
| Dummy most frequent | 0,8005 | 0,0000 | 0,5000 | 0,5000 | 0,5000 | 0,8005 | 1,0000 | 0,0000 | 0,8892 | 0/77/0/309 |
| SVC | 0,7963 | -0,0043 | 0,9785 | 0,5247 | 0,5589 | 0,8272 | 0,7282 | 0,3896 | 0,7745 | 30/47/84/225 |
| LightGBM | 0,7902 | -0,0103 | 0,9841 | 0,5349 | 0,5571 | 0,8224 | 0,8544 | 0,2597 | 0,8381 | 20/57/45/264 |

O XGBoost teve o maior AP pontual: `0,8307`, contra `0,8005` do Dummy, ganho absoluto `0,0302`. Seu ROC-AUC foi `0,5671`, balanced accuracy `0,5719` e especificidade `0,4286`, o que indica poder discriminativo limitado.

## Backtest temporal de 2024

| Modelo | AP | Ganho AP | ROC-AUC | Bal. acc. | Precisão | Recall | Especificidade | F1 | Matriz TN/FP/FN/TP | Limiar 2023 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|
| KNN | 0,9074 | 0,0314 | 0,6336 | 0,6217 | 0,9050 | 0,9434 | 0,3000 | 0,9238 | 9/21/12/200 | 0,9333 |
| LightGBM | 0,8943 | 0,0182 | 0,6097 | 0,5816 | 0,8971 | 0,8632 | 0,3000 | 0,8798 | 9/21/29/183 | 0,9841 |
| Logística | 0,8826 | 0,0066 | 0,5775 | 0,5542 | 0,8958 | 0,6085 | 0,5000 | 0,7247 | 15/15/83/129 | 0,9816 |
| XGBoost | 0,8800 | 0,0040 | 0,5426 | 0,4646 | 0,8585 | 0,4292 | 0,5000 | 0,5723 | 15/15/121/91 | 0,9827 |
| SVC | 0,8773 | 0,0013 | 0,5477 | 0,5987 | 0,9050 | 0,7642 | 0,4333 | 0,8286 | 13/17/50/162 | 0,9785 |
| Dummy prior | 0,8760 | 0,0000 | 0,5000 | 0,5000 | 0,8760 | 1,0000 | 0,0000 | 0,9360 | 0/30/0/212 | 0,5000 |
| Dummy most frequent | 0,8760 | 0,0000 | 0,5000 | 0,5000 | 0,8760 | 1,0000 | 0,0000 | 0,9360 | 0/30/0/212 | 0,5000 |
| Random Forest | 0,8752 | -0,0009 | 0,5447 | 0,6171 | 0,9052 | 0,9009 | 0,3333 | 0,9031 | 10/20/21/191 | 0,8908 |
| Decision Tree | 0,8551 | -0,0209 | 0,4024 | 0,3813 | 0,8198 | 0,4292 | 0,3333 | 0,5635 | 10/20/121/91 | 0,5000 |
| MLP | 0,8383 | -0,0378 | 0,3844 | 0,4686 | 0,8148 | 0,1038 | 0,8333 | 0,1841 | 25/5/190/22 | 0,5321 |

Este backtest é uma avaliação temporal já observada; não deve ser tratado como teste externo cego. A ordem muda de 2023 para 2024: KNN lidera o AP em 2024, enquanto XGBoost deixa de liderar.

## Incerteza e estabilidade

O bootstrap municipal pareado usa 100 reamostragens e compara cada candidato com o `Dummy prior`. Os intervalos estão em `dados/modelagem/e05_transferegov_365/resultados/bootstrap_pareado.csv`. Alguns intervalos de AP e balanced accuracy excluem zero em uma partição específica, enquanto outros incluem zero; isso não equivale a evidência de superioridade consolidada entre anos e métricas. A comparação entre XGBoost, Random Forest e Decision Tree deve ser lida como diferença pontual, sem generalizar significância.

O teste de permutação de 10 sementes não mostrou comportamento anômalo após embaralhamento: os ROC-AUC permutados permaneceram próximos de 0,5. A prevalência elevada explica APs altos e reduz o valor de uma leitura isolada do ranking.

## Conclusão

O XGBoost apresentou o maior Average Precision na validação de 2023 (`0,8307`), superando o baseline de prevalência em `0,0302`. Entretanto, o baixo poder discriminativo, a mudança de ordenação no backtest de 2024 e a incerteza observada nas comparações pareadas não sustentam uma vantagem estatisticamente estável. Assim, nenhum dos oito modelos demonstrou superioridade preditiva consolidada sob o contrato Transferegov de 365 dias. O XGBoost é descrito somente como o melhor resultado pontual da validação, sem recomendação para uso em produção.

Os resultados compactos versionáveis estão em `dados/modelagem/e05_transferegov_365/resultados/`. Os artefatos detalhados, incluindo probabilidades, curvas, erros e bootstrap completo, permanecem em `.local/e05_contrato_unico/` e não são versionados.
