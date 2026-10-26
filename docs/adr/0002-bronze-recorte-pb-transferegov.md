# ADR 0002 — Recorte PB no Bronze das Discricionárias do Transferegov

Data: 2026-10-26. Estado: aceito e implementado.

## Contexto

A regra do Bronze (ARQUITETURA.md) é preservar os bytes originais de cada resposta. As Discricionárias e Legais do Transferegov só são publicadas como CSV nacionais compactados, sem filtro no servidor: proposta, convênio, desembolso e emenda somam cerca de 230 MB por carga, dos quais a PB é uma fração pequena. O repositório oficial mantém apenas a carga mais recente (`data_carga_siconv`).

## Decisão

1. O Bronze das Discricionárias guarda o **recorte PB** de cada tabela, e não o zip nacional:
   - proposta: `UF_PROPONENTE = PB` (todas as naturezas jurídicas; o filtro municipal fica no Silver);
   - convênio e emenda: `ID_PROPOSTA` presente no recorte da proposta;
   - desembolso: `NR_CONVENIO` presente no recorte do convênio.
2. O recorte mantém todas as colunas e os textos exatamente como publicados. É gravado como CSV UTF-8 separado por `;`, comprimido em gzip sem data no cabeçalho, para que o mesmo original produza sempre os mesmos bytes.
3. O manifesto declara a origem como `recorte_pb:<url oficial>`. O índice `ref/transferegov_discricionarias_bronze.json` registra, por tabela, o SHA-256, o tamanho e o número de linhas do arquivo oficial, o número de linhas do recorte e o critério aplicado.
4. As Transferências Especiais continuam com o filtro `eq.PB` aplicado pela própria API; para elas o Bronze segue sendo a resposta original.

## Consequências

- O Bronze das Discricionárias passa de ~228 MB para alguns MB por carga.
- **Perda assumida:** depois que o repositório oficial substituir a carga, não é possível refazer o recorte com outro critério nem conferir o recorte contra o original; resta apenas o hash do original registrado no índice. Ampliar o escopo para outra UF exige uma carga nova.
- O recorte é transformação, ainda que mínima. Por isso o Bronze dessa fonte não equivale à resposta original e não serve como reprodução da coleta (mesma ressalva do PLANO_MVP para os snapshots).
- Índices da versão anterior (zips nacionais) são arquivados em `ref/historico/`. Os bytes nacionais já gravados permanecem no Bronze até remoção manual.
