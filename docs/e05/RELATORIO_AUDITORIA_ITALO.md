# Relatório de auditoria — contribuição de Ítalo na E05

## 1. Objetivo

Avaliar a prova de conceito de classificação do atraso do primeiro desembolso
em instrumentos discricionários do Transferegov. O estudo não prevê conclusão
física, qualidade ou sucesso geral do projeto.

## 2. Fonte e versão

Foi utilizada exclusivamente a versão Gold `65260a170ee18cd79501`, carregada
em `17/07/2026 06:30:47`. O manifesto validado tem SHA-256
`28E24585431DC29B0DA53B10FD0811B91A02BA79BD00484EA6297D9ABB84F5B5`.

## 3. Unidade e alvo

A unidade é um instrumento. O alvo
`risco_atraso_primeiro_desembolso_365d` recebe 0 quando há primeiro desembolso
válido até o dia 365, 1 quando não há, e ausente quando o instrumento ainda
não amadureceu. O dia 365 é inclusivo; o dia 366 é atraso.

## 4. Auditoria da conciliação

Foram encontrados 6.182 instrumentos e 9.411 desembolsos. Não houve
duplicidade de `id_desembolso`, desembolso sem instrumento, desembolso anterior
à assinatura, data inválida ou valor não positivo. Houve 547 instrumentos
censurados e 1.590 sem primeiro desembolso; estes últimos são classificados
como atraso apenas quando a janela está madura.

## 5. Preditores point-in-time

Foram usados 11 preditores explícitos: valores pactuados, duração original,
intervalo proposta-assinatura, modalidade, órgãos e indicadores de emenda.
Desembolsos, resultados administrativos, situação atual, CNPJ, identificadores
e fontes externas ficaram fora de X. O veredito point-in-time é PASS
condicional, pois não existem snapshots históricos individualizados que
comprovem materialmente cada valor na data da assinatura.

## 6. Coortes temporais

| Ano | Eventos | Positivos | Negativos | Prevalência |
|---:|---:|---:|---:|---:|
| 2022 | 239 | 211 | 28 | 0,8828 |
| 2023 | 386 | 309 | 77 | 0,8005 |
| 2024 | 242 | 212 | 30 | 0,8760 |

O treino usa 2022, a validação 2023 e o teste 2024. A separação temporal evita
usar o futuro para decidir o modelo; os folds também são agrupados por
município para evitar sobreposição de grupos.

## 7. Modelos e baselines

Foram avaliados XGBoost e LightGBM. Dummy prior, Dummy most frequent e
regressão logística regularizada funcionam como referências mínimas. Average
Precision é relevante porque a classe é desbalanceada; Brier e Log Loss medem
calibração, não superioridade isoladamente.

## 8. Validação cruzada

`StratifiedGroupKFold` com três folds, seed 42, grupos por município e
pré-processamento ajustado dentro do pipeline. AP médio por fold:

| Modelo | Fold 0 | Fold 1 | Fold 2 |
|---|---:|---:|---:|
| XGBoost | 0,9960 | 0,9931 | 0,9736 |
| LightGBM | 0,9928 | 0,9928 | 0,9755 |

Em 20 permutações do alvo, ROC-AUC média foi 0,4965 para XGBoost e 0,4984
para LightGBM, sem sinal persistente de vazamento.

## 9. Limiar

O limiar principal foi escolhido somente na validação de 2023 pela maior
balanced accuracy:

| Modelo | Limiar | Balanced accuracy | Especificidade | Matriz |
|---|---:|---:|---:|---|
| XGBoost | 0,9891 | 0,5818 | 0,5714 | `[[44,33],[126,183]]` |
| LightGBM | 0,3001 | 0,5293 | 0,1039 | `[[8,69],[14,295]]` |

Youden e recall mínimo de 0,90 foram registrados como sensibilidades, sem
alterar o limiar principal.

## 10. Resultados

| Modelo | Partição | AP | ROC-AUC | B.Acc. | Precisão | Recall | Especificidade | F1 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| XGBoost | Validação | 0,8107 | 0,5489 | 0,5818 | 0,8472 | 0,5922 | 0,5714 | 0,6971 |
| XGBoost | Teste | 0,9010 | 0,5932 | 0,5313 | 0,8922 | 0,4292 | 0,6333 | 0,5796 |
| LightGBM | Validação | 0,7936 | 0,5228 | 0,5293 | 0,8104 | 0,9547 | 0,1039 | 0,8767 |
| LightGBM | Teste | 0,9019 | 0,6464 | 0,5167 | 0,8797 | 1,0000 | 0,0333 | 0,9360 |

O Dummy tem AP igual à prevalência: 0,8005 na validação e 0,8760 no teste.
A regressão logística obteve AP 0,8057 na validação e 0,8689 no teste. Os
ganhos de AP sobre a prevalência na validação foram +0,0101 para XGBoost,
-0,0069 para LightGBM e +0,0051 para logística.

## 11. Calibração e diagnóstico

Na validação, Brier/Log Loss foram 0,1975/0,9007 para XGBoost e
0,2132/1,8532 para LightGBM. Curvas de calibração, Precision-Recall, ROC,
lift e diagnósticos de falsos positivos/negativos estão em
`.local/e05_italo/auditoria/`. Probabilidades extremas não são chamadas de
“confiança” sem evidência de calibração.

## 12. Limitações

O horizonte de 365 dias é uma convenção operacional da prova de conceito, não
um prazo legal geral. O alvo não expressa causalidade, risco municipal,
paralisação física, qualidade, conclusão ou sucesso geral. A fonte cobre apenas
instrumentos observáveis do Transferegov.

## 13. Vereditos

| Verificação | Veredito |
|---|---|
| Alvo e conciliação | PASS |
| Point-in-time | PASS condicional |
| Vazamento | PASS |
| Validação cruzada | PASS técnico |
| Reprodutibilidade | PASS |
| Superioridade preditiva consolidada | FAIL |

## 14. Conclusão

XGBoost e LightGBM foram avaliados na previsão do risco de o primeiro
desembolso não ocorrer em até 365 dias após a assinatura. Embora os modelos
apresentem algum poder de ordenação, os ganhos de Average Precision sobre a
prevalência foram pequenos e instáveis. O XGBoost apresentou o melhor resultado
na validação temporal entre os dois, mas sem superioridade suficiente para sua
adoção como modelo consolidado. O LightGBM ficou abaixo do baseline de
prevalência na validação, apesar do resultado melhor no teste. Portanto,
**nenhum dos modelos demonstrou superioridade preditiva consolidada**. Os
resultados são uma prova de conceito e não autorizam uso decisório ou em
produção.

## 15. Reprodutibilidade

O ambiente x64 validado executou 194 testes, `py_compile`, `pip check`, o
notebook integral e `nbformat.validate`. Não houve alteração no Gold, no
CURRENT ou chamadas externas durante a execução controlada.
