# Contrato temporal analítico do Transferegov

Este produto é descritivo e retrospectivo. Não preenche `historico_execucao_transferegov`, não calcula índice ampliado e não altera Bronze/Silver/Gold operacional.

As saídas vivem em `dados/analitico/transferegov_temporal/versoes/<versao_analitica>/`. A versão é derivada deterministicamente da versão Gold, SHA-256 do manifesto Gold, configuração, contrato temporal e maturidade.

Para Discricionárias/Legais, assinatura e desembolso usam a data do evento; a maturidade é assinatura + 365 dias. Dia 365 é `no_prazo_365`; dia 366 é `atrasado_apos_365`. Maturidade posterior ao corte é censura. `primeiro_desembolso_observado_ate_corte` e `dias_ate_primeiro_desembolso_observado` nunca revelam eventos futuros. `data_carga`, situação atual e resultados posteriores não são eventos históricos.

Especiais são separadas: plano pelo ano/data disponível, empenho e pagamento pela ordem bancária. Não recebem desfecho de 365 dias.

O campo principal é `evento_sem_desembolso_positivo_ate_365d`: `False` no prazo, `True` atraso/sem desembolso maduro e nulo em censura/indisponibilidade. “Atraso” é alias/proxy operacional e não comprova falha de execução. Zero exige cobertura confirmada, universo municipal e consulta completa. Caso contrário, o valor é nulo e o status/motivo é publicado separadamente.
