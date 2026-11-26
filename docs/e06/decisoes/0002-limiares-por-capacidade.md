# Decisão 0002 — Limiares sem custos definidos

Data: 2026-11-25. Estado: aceita.

## Contexto

Sem valores de benefício, custo e capacidade no pacote, um único limiar seria arbitrário.

## Decisão

Reportar a matriz de confusão em três limiares, definidos sem o teste:

1. F1 máximo de Y=1 na validação. Em A1 e A2, que não usam a validação, nas previsões fora da amostra das janelas.
2. Prevalência do treino.
3. Capacidade: os 10%, 20% e 30% de maior risco, com os empates repartidos pelo valor esperado.

## Consequências

Com 93% de Y=1 na validação, o limiar de F1 marca quase todos os instrumentos. A escolha do cenário de capacidade fica com quem usar o modelo.
