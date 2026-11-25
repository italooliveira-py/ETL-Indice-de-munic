# Dicionário temporal

| campo | significado |
|---|---|
| `nr_convenio` | identificador textual do instrumento |
| `codigo_ibge` | código municipal textual com sete dígitos |
| `data_assinatura` | data do evento de assinatura |
| `data_maturidade_365` | assinatura acrescida de 365 dias |
| `primeiro_desembolso_positivo` | primeiro desembolso válido, positivo e conciliado |
| `estado_maturidade` | no prazo, atraso, sem desembolso maduro ou censura |
| `evento_sem_desembolso_positivo_ate_365d` | `False` no prazo; `True` atraso/sem desembolso maduro; nulo quando censurado ou indisponível |
| `primeiro_desembolso_observado_ate_corte` | primeiro desembolso positivo conhecido até o corte; eventos futuros ficam nulos |
| `dias_ate_primeiro_desembolso_observado` | dias calculados somente com evento observado até o corte |
| `data_corte` | 31 de dezembro do ano de referência |
| `taxa_atraso_365_acumulada` | atrasados maduros sobre maduros acumulados até o corte |
| `taxa_atraso_365_coorte` | medida da coorte assinada no ano |
| `taxa_atraso_365_janela_3a` | medida diagnóstica dos três anos anteriores |
| `cobertura` | indicação de denominador maduro observado |

As tabelas `instrumentos`, `eventos_financeiros`, `especiais`, `municipio_ano_historico`, `censura_municipio_ano` e `sensibilidade_maturidade` são Parquet analítico. Identificadores são textuais; códigos IBGE têm sete dígitos e prefixo PB. A coorte contém instrumentos assinados no ano de referência. A janela de três anos contém instrumentos assinados entre ano-2 e ano, avaliados somente quando maduros no corte. Ambas são diagnósticas/descritivas e não aptas como probabilidade futura.

`desfecho_365`, quando presente por compatibilidade, é apenas alias de `evento_sem_desembolso_positivo_ate_365d`. “Atraso” é proxy operacional e não comprova falha de execução. Nenhuma taxa é probabilidade futura. Nulos representam cobertura, denominador, modalidade ou temporalidade indisponível; não representam zero.
