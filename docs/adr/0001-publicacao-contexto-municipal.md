# ADR 0001 — Publicação incremental do contexto municipal

Data: 2026-10-24. Estado: aceito e implementado na publicação Medallion.

## Contexto

Há coleta com cache, checkpoint, manifesto, validações eleitorais e tratamento conservador de ausências. O snapshot existente contém 1.115 linhas município-ano e 1.638 obras. Reescrever a coleta de uma vez aumentaria o risco de regressão.

## Decisões

1. Preservar os coletores sob `src/etl_municipal/legado` e manter entradas compatíveis na raiz. Fontes novas ficam em módulos próprios. A extração dos coletores antigos será feita fonte a fonte.
2. ObrasGov sai do Gold municipal do MVP. Mantém-se o grão projeto em Silver e o experimento de infraestrutura, que não representa o índice geral.
3. O painel exploratório continua em 2020–2024. Publica-se uma seleção MVP 2020–2023; PIB 2024 fica nulo com flag explícita. Atrasos de outras fontes serão tratados por variável e edição, sem impor um corte artificial a todas.
4. O contexto territorial usa o recorte oficial do Censo 2022, tabela 4714. Área e densidade preservam o ano de referência; não são apresentadas como séries anuais de área ou como densidade atual.
5. Bioma predominante deverá ser calculado por maior área de interseção das malhas oficiais, preservando percentuais e versão das geometrias. Até implementar e validar a operação espacial, bioma permanece indisponível; não se infere pelo nome ou centroide. Tipologia também exige classificação oficial específica.
6. RGF deverá usar Executivo, Anexo 01 e último período anual (Q3 ou S2 conforme a declaração efetiva). DCA continua proxy, sem renomear despesa/receita como pessoal/RCL. A implementação e os mapeamentos versionados ainda estão pendentes.
7. Datas públicas desconhecidas ficam nulas. A publicação não está liberada para treino temporal. Não há imputação no ETL.

## Consequências

A arquitetura pode evoluir sem quebrar os consumidores existentes. Há dois fluxos claramente nomeados: coleta legada e publicação Medallion do snapshot. A publicação consistente usa uma geração versionada, e ausência de integração não é anunciada como dado coletado.

Referências: [API de agregados IBGE](https://servicodados.ibge.gov.br/api/docs/agregados?versao=3), [tabela 4714](https://sidra.ibge.gov.br/tabela/4714), [SICONFI](https://apidatalake.tesouro.gov.br/docs/siconfi/).
