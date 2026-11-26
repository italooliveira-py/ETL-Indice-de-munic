# Decisão 0004 — Histórico do município como variável explicativa

Data: 2026-11-25. Estado: aceita, com a interpretação a confirmar pelo Jorge.

## Contexto

As contagens do histórico crescem com o tempo e misturam o comportamento do município com o ano.

## Decisão

O histórico entra como variável explicativa; o alvo não muda. Dentro do pipeline:

- `taxa_atraso_hist = (atrasados + 5·p) / (maduros + 5)`, com p = prevalência do treino;
- `sem_historico`: nenhum instrumento maduro anterior;
- `valor_medio_evento`: valor desembolsado anterior dividido pelos eventos anteriores.

B1 troca as contagens por essas variáveis; B2 usa as duas.

## Consequências

Só a prevalência do treino é aprendida. Um teste confirma que as variáveis não dependem do alvo das linhas avaliadas.
