# Mapeamento de fontes antes da integração

Levantamento feito em 2026-10-26 para SICONFI, Transferegov, MUNIC e IBGE territorial, antes de qualquer implementação. Para cada fonte: disponibilidade e defasagem pública, cobertura na Paraíba (223 municípios, 2020–2024), mudanças de coleta/apresentação no período e relevância para o escopo — índice de contexto municipal para execução de projetos e predição `X(t) → Y(t+1)` sem vazamento.

Evidência própria marcada como **[verificado]** foi obtida diretamente das APIs/FTPs oficiais nesta data; o restante vem de documentação oficial citada.

## Resumo

| Fonte | Situação no repo | Disponibilidade / defasagem | Cobertura PB | Mudanças relevantes 2020–2024 | Relevância | Recomendação |
|---|---|---|---|---|---|---|
| SICONFI DCA | coleta legada | anual; entrega até 30/abr de t+1 | 222–223/223 por ano (2020–2024) | RCL ajustada, layout estável nas contas usadas | essencial (dimensão fiscal) | extrair do legado com datas de entrega |
| SICONFI RGF | ausente | Q3 e S2 até 30/jan de t+1 | 222–223/223 por ano; ~10–13% semestrais | coexistem RGF quadrimestral e RGF Simplificado semestral; quadro de trajetória (LC 178/2021) incluído e removido em 2026 | essencial: único DTP/RCL legal | integrar Anexo 01 do Executivo, harmonizando Q3 e S2 |
| Transferegov Discricionárias | ausente | CSV diário — **parado desde 17/07/2026** | 223/223 (código IBGE na proposta); 122–208 municípios com instrumento assinado por ano | modelo de dados só ganhou campos (v13→v25); APIs só a partir de nov/2026 | essencial (recursos e captação) | Bronze: recorte PB dos 4 CSV + `data_carga` (ADR 0002) |
| Transferegov Especiais (Pix) | ausente | API pública ativa | 223/223 em 2020–2026; 17 municípios em 2020 → 206 em 2024 | modalidade criada pela EC 105/2019; cresce 15× no período | alta, e ausente do plano atual | Bronze da cadeia plano → empenho → pagamento |
| MUNIC | ausente | edições irregulares; publicação 10–13 meses após a referência | universal (5.570 municípios) | sem edição 2022; temas mudam por edição; bases revisadas após publicação | média: capacidade institucional | usar só blocos repetidos (RH) e como contexto por edição |
| IBGE territorial — área, população, densidade | **integrado** | Censo 2022 | 223/223 | — | controle | manter |

## SICONFI

**Acesso.** API `apidatalake.tesouro.gov.br/ords/siconfi/tt`, endpoints `dca`, `rgf` e `extrato_entregas`, sem autenticação. O endpoint `extrato_entregas` informa, por ente, exercício e entregável, a periodicidade, o status (`HO` homologado, `RE` retificado) e a data do status **[verificado]**.

**Cobertura PB** (varredura de `extrato_entregas` para os 223 municípios, exercícios 2020–2025) **[verificado]**:

| Exercício | DCA entregue | DCA retificada (`RE`) | DCA homologada até 30/abr | RGF Q (quadrimestral) | RGF Simplificado S | RGF último período retificado |
|---|---|---|---|---|---|---|
| 2020 | 223 | 4 | 70% | 195 | 28 | 134 |
| 2021 | 223 | 21 | 67% | 200 | 23 | 128 |
| 2022 | 222 | 17 | 88% | 199 | 23 | 120 |
| 2023 | 223 | 46 | 59% | 198 | 25 | 127 |
| 2024 | 222 | 41 | 70% | 201 | 22 | 122 |
| 2025 | 218 | 39 | 75% | 202 | 21 | 139 |

Lacunas: Damião (2505352) sem DCA e sem RGF em 2022; Paulista (2510907) sem DCA em 2024, o que é coerente com os 99% do snapshot atual; 5 municípios ainda sem DCA 2025. Em 36 municípios, a periodicidade do RGF muda entre anos. A coluna "homologada até 30/abr" considera só as DCA sem retificação, cuja data é a do envio original. A base da varredura (Executivo, DCA e RGF) está em [evidencias/siconfi_extrato_entregas_pb_2020_2025.csv](evidencias/siconfi_extrato_entregas_pb_2020_2025.csv).

**Disponibilidade pública.** O prazo legal da DCA é 30 de abril de t+1 (LRF, art. 51). O do RGF Q3 é 30 de janeiro, e o do S2, também ao final de janeiro. A varredura mostra mediana de entrega da DCA exatamente no prazo (dia 117–121 após 31/12), mas 12–41% das DCA homologadas chegaram depois de 30/abr. No RGF do último período, 54–62% dos registros estão retificados, e a data disponível é a da retificação. Portanto:

- DCA de t não está disponível em 1º de janeiro de t+1. Para `X(t) → Y(t+1)` com data de corte no início de t+1, usar a DCA de t−1, ou a data de entrega por município.
- `data_status` com status `RE` é a data da **última retificação**, não da primeira publicação. O valor servido pela API também é o retificado. Point-in-time estrito não é recuperável pela API; registrar `status_relatorio` e `data_status` e tratar `RE` como disponibilidade aproximada.

**Mudanças de apresentação.**

- Coexistem dois formatos de RGF do Executivo. O **RGF** quadrimestral (`co_tipo_demonstrativo=RGF`, `in_periodicidade=Q`, `nr_periodo=3`) e o **RGF Simplificado** semestral (`co_tipo_demonstrativo=RGF Simplificado`, `in_periodicidade=S`, `nr_periodo=2`), opção de municípios com menos de 50 mil habitantes (LRF, art. 63). Na PB, 21 a 28 municípios por ano usam o semestral, e 36 mudam de periodicidade entre anos. Ambos trazem o Anexo 01 com os mesmos códigos: `DespesaComPessoalTotal` (colunas `Valor` e `% sobre a RCL Ajustada`), `ReceitaCorrenteLiquidaAjustada` e limites máximo, prudencial e de alerta **[verificado: João Pessoa Q3 2020/2023/2024; município pequeno S2 2023]**.
- Os códigos de conta de pessoal/RCL ficaram estáveis de 2020 a 2024 em João Pessoa. O número de linhas do Anexo 01 muda (152 em 2020, 197 em 2023, 189 em 2024) por causa do quadro "Trajetória de Retorno ao Limite" da LC 178/2021, que é excluído no leiaute de 2026 ([síntese de alterações RGF 2026](https://siconfi.tesouro.gov.br/siconfi/pages/public/arquivo/conteudo/2026_Anexo_Sintese_de_Alteracoes_RGF_26_Estados_Municipios.pdf)). Selecionar contas por código, nunca por posição.
- RCL ajustada difere da RCL legal a partir de 2021 (deduções de emendas e transferências). Usar `% sobre a RCL Ajustada`, que é a base legal do limite.

**Relevância.** Alta. O RGF é a única fonte do indicador legal de pessoal/RCL, que o catálogo marca como essencial e que a DCA só aproxima (`pressao_pessoal_proxy`). As datas de entrega são, além disso, a evidência de disponibilidade pública que hoje bloqueia o treino temporal (`apto_para_treino_temporal=false`). A pontualidade/retificação da entrega é candidata a variável de capacidade administrativa.

## Transferegov

O Transferegov tem dois módulos com escopo municipal e acesso diferente. Os dois foram medidos na PB em 2026-10-26 **[verificado]**.

### Discricionárias e Legais (antigo SICONV)

**Acesso.** CSV compactados em `repositorio.dados.gov.br/seges/detru/`, um arquivo por tabela (o pacote completo `siconv.zip` tem ~3 GB). A página oficial diz que a extração é diária, mas `data_carga_siconv` marca **17/07/2026 06:30** e todos os arquivos têm essa data. A notícia de 10/07/2026 anuncia uma "nova área" de download e APIs do módulo em quatro etapas: atos preparatórios (jul–out/2026), instrumentos (nov/2026–fev/2027), execução financeira (mar–jun/2027) e obras (jul–out/2027) ([fonte](https://www.gov.br/transferegov/pt-br/ferramentas-gestao/api-de-dados-abertos-transferegov.br)). O endereço `api-publica.transferegov.gestao.gov.br/downloads` é uma aplicação JavaScript, e os arquivos não puderam ser listados automaticamente. Para 2020–2024 o arquivo parado não é problema; ele só não traz o que mudou depois de 17/07/2026.

**Tabelas com escopo municipal e chaves.**

| Tabela | Tamanho (zip) | Grão | Chave | Ligação com o município |
|---|---|---|---|---|
| `siconv_proposta` | 190 MB | proposta | `ID_PROPOSTA` | `COD_MUNIC_IBGE` (7 dígitos), `UF_PROPONENTE`, `NATUREZA_JURIDICA`, CNPJ em `IDENTIF_PROPONENTE` |
| `siconv_convenio` | 16 MB | instrumento | `NR_CONVENIO` | via `ID_PROPOSTA` |
| `siconv_desembolso` | 15 MB | desembolso (ordem bancária) | `ID_DESEMBOLSO` | via `NR_CONVENIO` |
| `siconv_emenda` | 7 MB | emenda × proposta | `NR_EMENDA` + `ID_PROPOSTA` | via `ID_PROPOSTA` |
| `data_carga_siconv` | <1 KB | — | — | data da extração, necessária para a proveniência |

Só `siconv_proposta` traz o município. As demais tabelas são nacionais e se ligam a ele pela proposta. Outras tabelas do modelo (empenho, pagamento, termo aditivo, cronograma físico, licitação etc.) descem para o nível de execução do instrumento e ficam para o escopo de projeto.

**Cobertura PB.**

- 54.226 propostas de "Administração Pública Municipal" na PB, com `COD_MUNIC_IBGE` preenchido em todas e **223 de 223 municípios**.
- São 288 CNPJs proponentes para 223 municípios (até 7 por município): prefeitura, fundos municipais de saúde, fundações, autarquias. O código IBGE da proposta atribui todos eles ao município, sem depender de catálogo CNPJ.
- 7.987 instrumentos de municípios da PB; 1.805 são pré-convênios (`IND_ASSINADO = NÃO`) e devem ser excluídos. 3.580 instrumentos assinados estiveram vigentes em algum momento de 2020–2024, cobrindo os 223 municípios.

| Ano de assinatura | Instrumentos | Municípios | Repasse pactuado (R$ mi) | Desembolsos no ano | Municípios com desembolso | Desembolsado (R$ mi) |
|---|---|---|---|---|---|---|
| 2020 | 284 | 142 | 316,9 | 1.087 | 202 | 333,6 |
| 2021 | 739 | 208 | 514,9 | 527 | 179 | 110,0 |
| 2022 | 239 | 129 | 183,3 | 611 | 185 | 173,2 |
| 2023 | 386 | 180 | 426,9 | 747 | 199 | 281,4 |
| 2024 | 242 | 122 | 1.079,7 | 805 | 185 | 306,8 |

O pico pactuado de 2024 é real: instrumentos do Novo PAC em João Pessoa (R$ 100 mi só para o Porto do Capim). Modalidades: contrato de repasse (3.981), convênio (1.965) e termo de compromisso (236). Anulados são 0–6% dos assinados por ano e devem ser mantidos com status, não apagados. A publicação (`DIA_PUBL_CONV`) é nula em 0,3% dos instrumentos.

**Mudanças no modelo de dados** ([histórico de versões](https://repositorio.dados.gov.br/seges/detru/historico_de_versoes.pdf)). No período houve apenas inclusões (v13 2021 a v25 08/2025): licitação, tributos, tabelas do Novo PAC (2023), contratos (2024), itens de documento de liquidação (2025), campos de empenho. Não há remoção nem renomeação de campos de valor ou vigência desde a v2 (2016). Desde a v8 (2018), `siconv_convenio` inclui pré-convênios. Os valores vêm sem separador de milhar e com vírgula decimal; o Bronze deve preservar o texto como veio.

**Disponibilidade temporal.** Há datas por registro (proposta, assinatura, publicação, vigência original e atual, desembolso), o que permite junção point-in-time melhor que nas demais fontes. Os CSV, porém, são uma fotografia da data de carga: situação, valores e vigência refletem o estado de hoje, não o de t. Por isso, cada carga no Bronze precisa guardar a `data_carga` junto.

### Transferências Especiais ("emendas Pix")

Modalidade criada pela EC 105/2019 (art. 166-A da Constituição) e **fora dos CSV de Discricionárias**. API PostgREST ativa em `api.transferegov.gestao.gov.br/transferenciasespeciais/`, sem autenticação, com no máximo 1.000 linhas por página (paginar com `order`, `offset` e `limit`).

**Tabelas com escopo municipal e chaves.**

| Recurso | Registros PB | Filtro PB | Ligação |
|---|---|---|---|
| `plano_acao_especial` | 1.925 | `uf_beneficiario_plano_acao=eq.PB` | `id_plano_acao`; beneficiário por CNPJ |
| `empenho_especial` | 1.979 | `uf_beneficiario_empenho=eq.PB` | `id_empenho` → `id_plano_acao` |
| `documento_habil_especial` | 1.874 | por `id_empenho` | `id_dh` → `id_empenho` |
| `ordem_pagamento_ordem_bancaria_especial` | 1.777 | por `id_dh` | `id_op_ob` → `id_dh` |
| `plano_trabalho_especial` | 1.879 | por `id_plano_acao` | prazo e situação da execução |
| `executor_especial` | 1.883 | por `id_plano_acao` | executor e valores |

Os quatro primeiros formam a cadeia financeira (planejado → empenhado → pago), que é municipal. `plano_trabalho` e `executor` descrevem a execução do objeto e ficam para o escopo de projeto. As tabelas filhas não têm UF; a extração as filtra pelos identificadores da tabela-mãe (`in.(...)`, em lotes).

**Cobertura PB.** Os 223 municípios aparecem como beneficiários ao menos uma vez em 2020–2026. Não há código IBGE: a identidade é pelo CNPJ do beneficiário, e o nome aparece ora como "MUNICIPIO DE X", ora só como "X". Isso exige o catálogo CNPJ → IBGE.

Somente beneficiários municipais (os pagamentos ao Estado da Paraíba, de R$ 1 mi a R$ 30 mi por ano, ficam fora); valores do Gold publicado:

| Ano | Planos | Municípios com plano | Planejado (R$ mi) | Municípios pagos | Pago (R$ mi) |
|---|---|---|---|---|---|
| 2020 | 18 | 17 | 9,1 | 17 | 9,1 |
| 2021 | 79 | 66 | 43,3 | 64 | 42,0 |
| 2022 | 207 | 121 | 85,0 | 81 | 40,4 |
| 2023 | 383 | 192 | 226,0 | 202 | 259,8 |
| 2024 | 375 | 206 | 209,5 | 206 | 207,8 |

O empenho sai sempre no mesmo ano do plano de ação. Já o pagamento pode escorregar para o ano seguinte, como em 2022 → 2023. Todas as ordens de pagamento da PB estão na situação 5 (concluída).

**Relevância.** Alta para a dimensão de recursos e captação, nos dois módulos. Na PB, as Especiais passaram a pagar quase tanto quanto as Discricionárias desembolsam (R$ 208 mi pagos a municípios contra R$ 307 mi desembolsados em 2024). Contar só as Discricionárias criaria uma falsa tendência de queda. A mudança de regime (as Pix não exigem convênio nem projeto prévio) é, ela própria, relevante para risco de execução. O plano atual (etapa D) não menciona as Especiais.

### O que carregar no Bronze

| Módulo | Artefatos | Volume | Retomada |
|---|---|---|---|
| Discricionárias | recorte PB das 4 tabelas (CSV gzip, textos originais), mais a `data_carga`; o índice guarda SHA-256, tamanho e linhas do zip nacional | poucos MB por carga | o `data_carga` identifica a geração; mesma `data_carga` = nada a baixar |
| Especiais | uma página JSON por requisição: `plano_acao` e `empenho` filtrados por PB; `documento_habil` e `ordem_pagamento` filtrados pelos identificadores | ~30 requisições por carga | cada página é preservada com URL e parâmetros; a retomada recomeça da página que faltou |

No Bronze entra só o recorte PB, sem conversão de tipos ([ADR 0002](adr/0002-bronze-recorte-pb-transferegov.md)). Filtro municipal por natureza jurídica, exclusão de pré-convênios, conversão de valores e ligação CNPJ → IBGE ficam para o Silver.

## MUNIC

**Acesso.** FTP `ftp.ibge.gov.br/Perfil_Municipios/<ano>/Base_de_Dados/` (xlsx/ods). Questionário respondido pela prefeitura, cobertura universal.

**Edições e publicação** **[verificado no FTP]**:

| Edição | Publicação | Base disponível | Temas principais |
|---|---|---|---|
| 2019 | 02/12/2020 | revisada em 17/08/2021 | RH, recursos para gestão, comunicação e informática, governança, articulação interinstitucional, segurança, direitos humanos |
| 2020 | 10/11/2021 | original | RH, habitação, transporte, agropecuária, meio ambiente |
| 2021 | 08/12/2022 | revisada em 25/04/2024 | RH, legislação e instrumentos de planejamento, educação, cultura, esporte, saúde, COVID-19 |
| 2022 | — | **não houve edição** (ano do Censo) | — |
| 2023 | 31/10/2024 | original | RH, assistência social, segurança alimentar, mulheres, segurança, direitos humanos, primeira infância |
| 2024 | 31/10/2025 | revisada em 07/11/2025 | RH, informática e comunicação, governança, habitação, transporte e mobilidade, agropecuária, gestão migratória, igualdade racial |
| 2025 | ainda não publicada | — | — |

**Mudanças.** Os temas variam por edição; só **recursos humanos** (servidores por vínculo) aparece em todas. Instrumentos de planejamento (plano diretor, legislação urbanística) aparecem em 2021, e habitação/transporte em 2020 e 2024: não formam série anual. As bases são substituídas por versões revisadas e o arquivo original não fica disponível, o que impede point-in-time estrito.

**Disponibilidade temporal.** A edição t é publicada entre 10 e 13 meses depois de t. Em 1º de janeiro de t+1, a edição t ainda não existe: usar a edição publicada mais recente antes da data de corte (por exemplo, para X(2024), a MUNIC 2023 publicada em 31/10/2024).

**Relevância.** Média e específica: capacidade técnica e institucional (proporção de estatutários, existência de plano diretor, órgão de habitação, informatização). Recomenda-se um bloco pequeno e estável, com o valor sempre acompanhado da edição de origem, e não espalhar temas esporádicos pelo painel anual. Ausência de resposta é diferente de resposta negativa.

## IBGE territorial

**Integrado:** área, população e densidade do Censo 2022 (tabela 4714) para os 223 municípios, como contexto estático.

Bioma e tipologia rural-urbana ficam **fora deste escopo**: descrevem o território do projeto e não o município como gestor; serão tratados junto ao escopo de tipo de projeto.


## Ordem sugerida

1. **SICONFI**: extrair a DCA do legado e integrar o RGF Anexo 01 (Q3 e S2 harmonizados), publicando `data_status` e `status_relatorio`. É a dimensão essencial e é a única fonte que já fornece datas de disponibilidade por município.
2. **Transferências Especiais**: API estável, volume pequeno, alto impacto. Exige incluí-la no plano (etapa D).
3. **Transferegov Discricionárias**: Bronze dos CSV atuais (cobertura 2020–2024 confirmada); acompanhar a nova área de download para cargas futuras.
4. **MUNIC**: bloco de RH por edição, com a regra da última edição publicada antes do corte.

## Pendências para decidir

- Decidir a data de corte de `X(t)` (1º de janeiro de t+1 ou outra), pois ela define qual DCA, RGF e MUNIC entram.
