# Decisão 0005 — Ano da assinatura como número

Data: 2026-11-25. Estado: aceita.

## Contexto

O pacote define `ano_origem` como preditor numérico, e o teste (2022–2023) fica fora da faixa do treino (2008–2019). A logística prolonga a tendência; as árvores tratam todo ano a partir de 2019 como o último ano visto.

## Decisão

Manter o ano como no pacote e medir o efeito em C1: M1+ sem `ano_origem`.

## Consequências

Se C1 não piorar, o relatório recomenda retirar o ano.
