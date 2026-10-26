# Plano revisado do MVP

Atualizado em 2026-10-24. Reaproveitar coletores, catálogos, checkpoints e política de nulos. Cada etapa termina com dados, contratos, auditoria e documentação; criar uma pasta ou um adaptador vazio não conta como fonte integrada.

## Entregue nesta etapa

- Pacote `src/etl_municipal` com armazenamento, contratos, fontes, publicação e implementação legada separada; entradas anteriores preservadas.
- Bronze imutável, migração por hashes dos snapshots e Silver/Gold Parquet com geração versionada.
- Adaptador das saídas completas da coleta legada para Bronze, com conferência do resumo, contagens e bloqueio de smoke.
- Validação independente do universo oficial de 223 municípios pela API de Localidades.
- Coleta territorial real do Censo 2022: área, população e densidade dos 223 municípios.
- Gold exploratório de 1.115 linhas e Gold MVP de 892 linhas, sem agregados ObrasGov.
- Tabela separada com as 1.638 obras; cobertura e status por variável; disponibilidade temporal não inventada.
- Contratos e testes de regressão offline.

## Correções em relação ao plano inicial

1. Exigir 223 municípios na tabela de referência e no painel completo; não em cada tabela de eventos. Zero eventos é possível, falha de consulta não comprova zero.
2. Cobertura é por variável e ano. Um status por fonte não descreve sozinho colunas com disponibilidades diferentes. Preservar também os estados legados de coleta.
3. Não anular todo o ano de 2024. Aplicar defasagem por variável e publicação; manter observações válidas. A seleção 2020–2023 é um produto específico, não evidência automática de que todas as fontes cobrem esse período.
4. Bronze de snapshot tem origem local declarada; não substitui respostas originais das APIs. Reproduzir o Gold a partir dele não equivale a reproduzir a coleta original.
5. Contexto 2022 não deve ser retropropagado como informação conhecida em 2020. Disponibilidade não comprovada bloqueia treino temporal, mesmo com boa cobertura.
6. A notícia oficial do Transferegov atualizada em julho de 2026 distingue APIs de Parcerias/Especiais dos CSV de Discricionárias e Legais. O cronograma prevê instrumentos entre novembro/2026 e fevereiro/2027 e execução financeira entre março e junho/2027. Usar os arquivos históricos disponíveis, sem implementar um endpoint presumido. [Fonte oficial](https://www.gov.br/transferegov/pt-br/ferramentas-gestao/api-de-dados-abertos-transferegov.br).

## Próximas entregas, em ordem

| Etapa | Implementação | Critério de aceite |
|---|---|---|
| A — concluir migração | Extrair IBGE econômico, DCA, PNCP e ObrasGov do orquestrador antigo, um por vez; o adaptador de `output/` já está implementado | Comparação dos dados, checkpoints e erros; mesma suíte; execução completa de regressão por fonte |
| B — territorial restante | Tipologia oficial e interseção município × bioma, com percentuais e versão da malha | 223 linhas, soma espacial reconciliada, regra de predominância auditada |
| C — RGF | Verificar esquema oficial e mapear contas por exercício; Executivo Q3/S2; pessoal/RCL, prudencial e caixa líquido | Não misturar Legislativo; paginação completa; conta/coluna/unidade verificadas; ausência de declaração identificada; totais reconciliados |
| D — Transferegov | Importar instrumentos, proponentes e desembolsos dos CSV oficiais; módulos separados | Identidade por IBGE/CNPJ e evidência; valores liberados pelo ano do desembolso; vigência por data; instrumentos únicos; reconciliação externa |
| E — MUNIC | Selecionar campos e códigos do questionário por edição: planejamento, cadastro, habitação e capacidade técnica | Grão município, ano e disponibilidade explícitos; ausente diferente de resposta negativa; cobertura mínima 70% para uso |
| F — MapBiomas | Fixar coleção e legenda da planilha municipal; trabalhar com classes de um nível, sem somar classes pai e filhas | Área total reconciliada em hectares; classe urbana identificada; proporção entre 0 e 1; crescimento só entre anos consecutivos e base positiva |
| G — SINISA | Selecionar indicadores/glossários de água, esgoto, resíduos e drenagem, referência 2024 | Prestadores consolidados sem duplicar população; não declaração explícita; cobertura mínima definida; corte estático sem concatenação automática com SNIS |
| H — liberação analítica | Disponibilidade pública por variável/edição; deduplicação entre instrumentos e obras; decisão de variáveis e versões | Join point-in-time; validação temporal; nenhum resultado posterior em X(t); índice descrito como contexto |

## Gates comuns

Antes do merge: grão e chave documentados; identidade contra referência oficial; tipos/unidades conforme catálogo; faixas plausíveis; auditoria de cobertura por ano; totais externos quando publicados; reexecução offline do Bronze com comparação de hashes no mesmo runtime. Fontes declaratórias abaixo de 70% ficam fora do índice ou sob revisão explícita, sem imputação automática.

Não adotar `sem_registro_confirmado` para toda resposta vazia de RGF ou SINISA. A confirmação exige resposta válida no recorte correto e entendimento da cobertura da fonte; sem isso, usar `indisponivel`. `nao_entregue` e `nao_declarou` exigem evidência específica, não inferência de erro HTTP.

Não somar valor total do instrumento em cada ano nem atribuir desembolsos pela data de celebração. A deduplicação Transferegov/ObrasGov/FNDE deve publicar uma tabela de vínculos por identificador de instrumento e evidência, preservando registros ambíguos para revisão.
