# Dicionário point-in-time dos preditores

Todos os campos abaixo são atributos do instrumento disponíveis na assinatura
ou derivados exclusivamente de datas já presentes nesse momento:

| Variável | Descrição/tipo | Origem | Tratamento | Disponibilidade | Decisão | Risco |
|---|---|---|---|---|---|---|
| `valor_global_original` | valor pactuado, numérico | instrumento | mediana no treino | assinatura | incluir | baixo |
| `valor_global_assinatura` | valor assinado, numérico | instrumento | mediana no treino | assinatura | incluir | baixo |
| `valor_contrapartida` | contrapartida, numérico | instrumento | mediana no treino | assinatura | incluir | baixo |
| `duracao_original_dias` | duração original, numérico derivado | datas originais | mediana no treino | assinatura | incluir | baixo |
| `dias_proposta_ate_assinatura` | intervalo, numérico derivado | proposta/assinatura | mediana no treino | assinatura | incluir | baixo |
| `modalidade` | modalidade, categórico | instrumento | moda/one-hot no treino | assinatura | incluir | baixo |
| `orgao_superior` | órgão superior, categórico | instrumento | moda/one-hot no treino | assinatura | incluir | baixo |
| `orgao` | órgão concedente, categórico | instrumento | moda/one-hot no treino | assinatura | incluir | baixo |
| `origem_emenda` | indicador, booleano | instrumento | categórico | assinatura | incluir | baixo |
| `emenda_individual` | indicador, booleano | instrumento | categórico | assinatura | incluir | baixo |
| `emenda_impositiva` | indicador, booleano | instrumento | categórico | assinatura | incluir | baixo |

Foram excluídos identificadores, `codigo_ibge`, desembolsos, `resultado_*`,
situação atual, vigência atualizada, CNPJ, campos de execução financeira,
status operacionais e qualquer variável posterior à assinatura. Imputação,
codificação e seleção são ajustadas dentro do treino/fold.

Identificadores (`nr_convenio`, `id_proposta`, `codigo_ibge`) não são
preditores. Desfechos administrativos e metadados de qualidade podem ser
usados somente em auditoria posterior, nunca em X.

Os preditores foram aceitos a partir de sua definição e do momento esperado de
disponibilidade na assinatura. Entretanto, a fonte não fornece snapshots
históricos individualizados capazes de comprovar materialmente cada valor
publicado naquela data. Por isso o veredito point-in-time é PASS condicional.
