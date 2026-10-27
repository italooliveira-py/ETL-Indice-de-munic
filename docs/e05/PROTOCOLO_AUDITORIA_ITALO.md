# Protocolo de auditoria — E05 Ítalo

## Pergunta e congelamento

Pergunta preditiva: entre instrumentos assinados em uma coorte temporal, quais
apresentam maior probabilidade de não realizar o primeiro desembolso em até
365 dias?

Unidade analítica: um instrumento discricionário do Transferegov, identificado
internamente por `nr_convenio` e sem uso desse identificador como preditor.

- Gold: `65260a170ee18cd79501`
- Data de carga: `17/07/2026 06:30:47`
- Alvo: `risco_atraso_primeiro_desembolso_365d`
- Horizonte: 365 dias após `data_assinatura`, inclusivo no dia 365.
- População: instrumentos discricionários do Transferegov com coorte de assinatura em 2022, 2023 ou 2024.
- Censura: menos de 365 dias completos observáveis na data de carga; censurados ficam fora do treino e da avaliação.
- Divisão: treino 2022, validação 2023, teste 2024; sem embaralhamento temporal.
- Os resultados de 2024 já haviam sido visualizados em uma execução exploratória
  anterior. Este protocolo definitivo foi congelado antes da execução auditada.
- Após o congelamento, nenhuma variável, busca, hiperparâmetro ou limiar pode
  ser alterado por causa do teste de 2024.

## Preditores congelados

`valor_global_original`, `valor_global_assinatura`, `valor_contrapartida`,
`duracao_original_dias`, `dias_proposta_ate_assinatura`, `modalidade`,
`orgao_superior`, `orgao`, `origem_emenda`, `emenda_individual` e
`emenda_impositiva`.

Identificadores, valores e datas de desembolso, situação atual, resultados
administrativos, CNPJ, `codigo_ibge`, fontes externas e campos posteriores à
assinatura permanecem excluídos de X.

## Modelos e hiperparâmetros

Serão avaliados XGBoost e LightGBM. A busca permanece pequena, determinística,
com `random_state=42`, `n_jobs=1`, `StratifiedGroupKFold(n_splits=3)` e grupos
por município. A métrica de seleção da busca é Average Precision no treino.

Baselines de auditoria: `DummyClassifier(strategy="prior")`,
`DummyClassifier(strategy="most_frequent")` e regressão logística regularizada.

## Limiar e métricas

O limiar será escolhido somente na validação de 2023 pelo maior balanced
accuracy. Youden, custos assimétricos e recall mínimo são análises de
sensibilidade; nenhum deles altera o limiar principal. O teste de 2024 será
avaliado uma única vez após este congelamento.

Critério de superioridade: AP de validação acima da prevalência e dos
baselines, ROC-AUC materialmente acima de 0,5, especificidade não nula,
classes não colapsadas, estabilidade entre CV e validação e calibração sem
degradação clara. Se essas condições não forem atendidas, o veredito será
“nenhum dos dois modelos demonstrou superioridade preditiva consolidada”.

Brier e Log Loss serão reportados somente como calibração. MSE, RMSE e MAE não
serão usados.

## Critérios de parada

Interromper antes da avaliação final se houver Gold incorreto ou alterado,
falha de conciliação, vazamento não resolvido, coorte com menos de 10 positivos
ou negativos, alvo permutado persistentemente acima do acaso, uso de 2024 na
seleção ou impossibilidade de comprovar a disponibilidade dos preditores no
corte. O point-in-time é PASS condicional porque não há snapshots históricos
individualizados que comprovem materialmente cada valor na assinatura.

## Limitações pré-declaradas

O alvo mede apenas atraso do primeiro desembolso, não conclusão física,
qualidade, sucesso ou risco geral do projeto. Não há inferência causal e os
resultados não se generalizam a todos os projetos públicos.
