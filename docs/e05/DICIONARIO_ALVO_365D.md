# Dicionário do alvo de 365 dias

| Campo | Definição |
|---|---|
| Nome | `risco_atraso_primeiro_desembolso_365d` |
| Tipo | binário observável, com ausente para censura |
| Unidade | instrumento discricionário |
| Evento inicial | `data_assinatura` |
| Evento observado | primeiro desembolso válido conciliado por `nr_convenio` |
| Horizonte | 365 dias corridos |
| Data de corte | 17/07/2026 |

## Regra

`risco_atraso_primeiro_desembolso_365d` é definido por instrumento:

- `0`: primeiro desembolso válido em até 365 dias, incluindo o dia 365;
- `1`: ausência de desembolso válido até o dia 365, ou primeiro desembolso somente após o dia 365;
- ausente: ainda não transcorreram 365 dias completos na data de carga;
- inválido: chave, data ou conciliação inconsistente, reportado fora da modelagem.

O primeiro desembolso é o menor `data_desembolso` não nulo, com valor positivo,
posterior ou igual à assinatura, conciliado por `nr_convenio`. Duplicidades de
`id_desembolso` e inconsistências temporais são contabilizadas; não são
silenciosamente descartadas.

O dia 365 pertence à classe 0; o dia 366 pertence à classe 1. Instrumentos
sem 365 dias completos na data de corte são censurados e não entram na
modelagem. A ausência de desembolso não é convertida em censura quando a
janela já amadureceu.

## Limitações e interpretação

Campos de origem: `nr_convenio`, `data_assinatura`, `id_desembolso`,
`data_desembolso` e `valor_desembolsado`. Inconsistências de chave, data,
valor, duplicidade e ordem temporal são reportadas em vez de descartadas em
silêncio.

Interpretação permitida: probabilidade estimada de o primeiro desembolso não
ocorrer em até 365 dias após a assinatura.

Não é probabilidade de fracasso geral, paralisação física, baixa qualidade,
conclusão do projeto, causalidade municipal ou risco de todos os projetos
públicos.
