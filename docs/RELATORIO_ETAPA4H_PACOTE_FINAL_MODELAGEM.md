# Etapa 4H — pacote final Transferegov para modelagem E06

## A. Pacote

Versão `4h1a7c9e3b5d0f2e6a8c`, em `dados/analitico/pacote_final_modelagem_e06/versoes/4h1a7c9e3b5d0f2e6a8c/`. Contém `data/`, `docs/`, `audit/` e `verify_package.py`. Requer Python 3.12 x64, pandas e pyarrow compatíveis com o lock E05. Não contém treinamento.

## B–C. População e partições

São 5.359 instrumentos maduros, 242 censurados, 223 municípios, 4.315 Y=1 e 1.044 Y=0.

| Partição | Período | Instrumentos | Y=1 | Y=0 | Prevalência Y=1 | Municípios |
|---|---|---:|---:|---:|---:|---:|
| train | 2008–2019 | 3.711 | 2.840 | 871 | 76,5% | 223 |
| validation | 2020–2021 | 1.023 | 955 | 68 | 93,4% | 217 |
| test | 2022–2023 | 625 | 520 | 105 | 83,2% | 196 |

## D. Preditores

M1 contém: `ano_origem`, `modalidade`, `historico_instrumentos_maduros`, `historico_atrasados`, `historico_eventos_financeiros` e `historico_valor_desembolsado`.

M1+ acrescenta `valor_global_assinatura`, valor monetário originalmente registrado na assinatura. Todos os sete campos têm 0 nulos na população final. `modalidade` requer codificação categórica; campos monetários podem exigir análise de assimetria, sem alterar os valores originais.

O valor possui mínimo de R$ 88.192, mediana de R$ 334.572, p99 de R$ 6.007.000, máximo de R$ 71.532.046,50, zero valores nulos, zero zeros e zero negativos. Outliers foram preservados.

## E. M1 versus M1+

As duas matrizes usam exatamente os mesmos 5.359 instrumentos, rótulos, exclusões e partições. A única diferença é `valor_global_assinatura`. Portanto, a equipe pode comparar os contratos sem alterar a população ou consultar o teste para selecionar a especificação.

## F–G. Qualidade e validade temporal

Não há duplicidades, nulos no alvo ou sobreposição entre partições. O desfecho segue a janela de 365 dias desde a assinatura: Y=1 sem primeiro desembolso positivo na janela; Y=0 com primeiro desembolso positivo. Censurados permanecem separados.

Os históricos são congelados na origem e o resultado usa o último snapshot observável até 31/12/2024. Não foram encontrados campos futuros nos preditores. A validade do valor original decorre do campo de origem `valor_global_assinatura`; a equipe deve preservar essa interpretação e não substituí-lo por valores atualizados.

As prevalências variam entre as coortes e não foram ajustadas. Não foi aplicado reamostramento, SMOTE ou transformação global.

## H. Guia da equipe

`docs/GUIA_EQUIPE_MODELAGEM.md` documenta carregamento, hashes, M1/M1+, pré-processamento em pipeline, baseline, regressão logística, árvore, ensemble, validação temporal, métricas, calibração, limiar, custos/benefícios/capacidade e análise de equidade. Nenhum parâmetro operacional foi inventado.

## I–J. Reprodutibilidade e testes

O comando `python verify_package.py` retornou `status=OK`, 5.359 linhas, 223 municípios, zero nulos no alvo e zero divergências de hash. Testes direcionados do contrato final: 3/3 aprovados. Testes de regressão 4G/4E/4D: 14/14 aprovados na execução conjunta anterior da consolidação. A suíte completa do repositório não foi classificada como aprovada sem resumo confiável.

## K. Publicação futura

Incluir somente o namespace final 4H, o relatório, o checkpoint, o módulo/teste da consolidação e o plano correspondente, após revisão. Não incluir arquivos temporários, segredos ou bases externas não relacionadas. Nenhum arquivo foi colocado em staging nesta execução.

## Desfecho obrigatório

**POPULAÇÃO FINAL:** 5.359 instrumentos maduros.

**MUNICÍPIOS:** 223.

**VARIÁVEL-ALVO:** `y_1_sem_desembolso_365`; ausência de primeiro desembolso positivo em 365 dias após assinatura.

**PREDITORES M1:** 6 — `ano_origem`, `modalidade`, `historico_instrumentos_maduros`, `historico_atrasados`, `historico_eventos_financeiros`, `historico_valor_desembolsado`.

**PREDITORES M1+:** 7 — M1 + `valor_global_assinatura`.

**VALOR GLOBAL NA ASSINATURA:** VALIDADO.

**TREINO:** 3.711 registros, 76,5% Y=1.

**VALIDAÇÃO:** 1.023 registros, 93,4% Y=1.

**TESTE:** 625 registros, 83,2% Y=1.

**CENSURA:** VALIDADA.

**VAZAMENTO TEMPORAL:** NÃO IDENTIFICADO.

**PARTIÇÕES:** VALIDADAS.

**REPRODUTIBILIDADE:** CONFIRMADA para o pacote; ETL integral desde bruto permanece não reproduzido neste artefato.

**TESTES:** 3/3 finais aprovados; 14/14 regressões direcionadas aprovadas; suíte total não classificada.

**PACOTE PRONTO PARA ESTIMAÇÃO:** SIM, condicionado à revisão da equipe.

**PACOTE PRONTO PARA PUBLICAÇÃO:** CONDICIONADO.

**LIMITAÇÕES REMANESCENTES:** fontes multibase permanecem fora da matriz; prevalência muda entre coortes; a interpretação operacional de risco não deve ser ampliada além do desfecho.

**PRÓXIMA AÇÃO RECOMENDADA:** revisão final da equipe e autorização explícita para publicação do namespace 4H; depois, execução dos modelos pela equipe responsável.
