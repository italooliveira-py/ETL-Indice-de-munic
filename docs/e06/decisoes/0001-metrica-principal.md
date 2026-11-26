# Decisão 0001 — Brier skill como métrica principal

Data: 2026-11-25. Estado: aceita.

## Contexto

O pacote pede uma métrica principal justificada, mas não define benefícios, custos nem capacidade de acompanhamento. O uso previsto é priorizar instrumentos por chance de não receber em 365 dias. Y=1 é a classe majoritária: 77% no treino e 83% no teste.

## Decisão

Escolher e comparar modelos pelo Brier, reportado como Brier skill contra a prevalência do treino. ROC-AUC e PR-AUC (das duas classes) entram como métricas de ordenação.

## Consequências

Um modelo que ordena bem mas erra o nível perde na métrica principal. O PR-AUC de Y=1 começa perto de 0,8 mesmo para um sorteio, por isso também se reporta o de Y=0.
