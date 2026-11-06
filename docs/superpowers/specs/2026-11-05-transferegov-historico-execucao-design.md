# Especificação — Histórico temporal de execução do Transferegov

## Status e escopo

Esta especificação registra auditoria empírica e desenho para revisão. Não implementa o índice definitivo, não altera PNCP, Bronze/Silver/Gold operacional, não coleta, não faz refresh, staging, commit, push ou Pull Request.

O worktree é `feature/transferegov-historico-execucao`, em `f10172c`, igual a `origin/main`; `fc4f5c1` já está incorporado. As fontes permanecem separadas: PNCP (intensidade/perfil contratual), Transferegov (transferências), SICONFI (fiscal), MUNIC (institucional) e eleitorais adiados. `historico_execucao_transferegov` permanece nulo.

## Auditoria empírica somente leitura

Foi usado um caminho externo por parâmetro (`TRANSFEREGOV_DATA_ROOT`), sem registrar caminho absoluto versionável e sem copiar ou alterar dados. Foram confirmados `gold/CURRENT.json`, `data/silver`, `data/bronze` e a versão Gold `65260a170ee18cd79501`.

O manifesto existe, declara pipeline `0.2.0`, versão Gold `65260a170ee18cd79501` e carga `17/07/2026 06:30:47`. Seu SHA-256 calculado é exatamente:

`28E24585431DC29B0DA53B10FD0811B91A02BA79BD00484EA6297D9ABB84F5B5`

| tabela | linhas | colunas | chave/observação | hash do Parquet |
|---|---:|---:|---|---|
| `transferegov_instrumentos` | 6.182 | 34 | `nr_convenio` único | coincide |
| `transferegov_desembolsos` | 9.411 | 5 | `id_desembolso` único | coincide |
| `transferegov_discricionarias` | 1.115 | 8 | município × ano | coincide |
| `transferegov_especiais` | 1.115 | 6 | município × ano | coincide |
| `transferegov_especiais_planos` | 1.901 | 12 | `id_plano_acao` único | coincide |
| `transferegov_especiais_empenhos` | 1.949 | 7 | `id_empenho` único | coincide |
| `transferegov_especiais_pagamentos` | 1.746 | 8 | pagamentos por ordem bancária | coincide |

O manifesto declara 223 municípios e 1.115 linhas anuais. A conciliação encontrou: instrumentos sem município 0; fora da PB 0; `nr_convenio` duplicado 0; `id_desembolso` duplicado 0; desembolsos órfãos 0; desembolsos anteriores à assinatura 0; assinaturas inválidas 0; desembolsos inválidos 0; `data_carga` inválida 0; valores de desembolso negativos/zero/nulos 0/0/0. Foram encontradas 21 datas de publicação inválidas; `data_publicacao` fica fora do contrato de execução. Nas Especiais, município ausente foi 0 e pagamento nulo foi 0.

Isso confirma a geração conhecida, mas não prova que estados carregados em 17/07/2026 eram disponíveis em cada corte anual.

## Contrato temporal

Para cada ano de 2020 a 2024, o corte é 31/12. Entram instrumentos com `data_assinatura <= corte` e desembolsos positivos, válidos, conciliados, com `data_desembolso <= corte` e `data_desembolso >= data_assinatura`. `data_carga` é disponibilidade da fotografia e nunca data do evento.

Para Discricionárias/Legais, maturidade é `data_assinatura + 365 dias`: dia 365 no prazo; dia 366 atraso; maturidade posterior ao corte = `censurado_365_incompleto`. Ausência de desembolso positivo após maturidade é estado auditável de `sem_desembolso_ate_maturidade`, não zero imputado. Situação atual, resultados posteriores, valores ajustados e `resultado_*` não entram em fotografia passada.

Para Transferências Especiais, planos usam ano do plano e pagamentos usam data da ordem bancária. A regra de 365 dias não será aplicada sem data equivalente de assinatura e contrato temporal defensável.

## Reconstrução em memória

| ano | elegíveis | maduros | no prazo | atrasados/sem desembolso maduro | censurados |
|---:|---:|---:|---:|---:|---:|
| 2020 | 3.995 | 3.711 | 871 | 2.840 | 284 |
| 2021 | 4.734 | 3.995 | 889 | 3.106 | 739 |
| 2022 | 4.973 | 4.734 | 939 | 3.795 | 239 |
| 2023 | 5.359 | 4.973 | 967 | 4.006 | 386 |
| 2024 | 5.601 | 5.359 | 1.044 | 4.315 | 242 |

Todos os anos tiveram 223 municípios com ao menos um instrumento maduro. A prevalência bruta de atraso foi 76,5292%, 77,7472%, 80,1648%, 80,5550% e 80,5188%.

### Denominador maduro por município

| ano | 0 | 1–4 | 5–9 | 10–19 | 20+ |
|---:|---:|---:|---:|---:|---:|
| 2020 | 0 | 3 | 25 | 118 | 77 |
| 2021 | 0 | 0 | 17 | 95 | 111 |
| 2022 | 0 | 0 | 11 | 94 | 118 |
| 2023 | 0 | 0 | 4 | 78 | 141 |
| 2024 | 0 | 0 | 4 | 71 | 148 |

A participação dos dez maiores municípios nos maduros foi 12,6112%, 12,3655%, 11,5547%, 11,4619% e 11,1961%; a do maior município ficou próxima de 2%.

## Comparação de métodos, sem seleção

Foram comparados em memória: taxa bruta; taxa com denominador mínimo 5; Beta-Binomial Beta(1,1); shrinkage para média estadual com `k=5`. Coberturas foram, respectivamente, 223/223 em todos os anos; 217, 220, 223, 223, 223; 223/223; 223/223. A taxa mínima 5 teve a mesma ordenação da bruta nos municípios retidos. Spearman Beta/bruta variou de 0,9805 a 0,9858, com 88,79%–92,83% das posições alteradas; shrinkage/bruta variou de 0,9945 a 0,9980, com 78,03%–88,79% alteradas.

Recomendação: manter os quatro métodos como diagnóstico, publicar denominador/maturidade/censura e não transformar qualquer taxa em índice definitivo. A taxa bruta é referência descritiva transparente, não escolha preditiva. Nenhum método foi selecionado por associação futura.

## Namespace analítico futuro

Qualquer saída nova, se aprovada, ficará somente em:

- `dados/analitico/transferegov_temporal/instrumentos.parquet`;
- `dados/analitico/transferegov_temporal/eventos_financeiros.parquet`;
- `dados/analitico/transferegov_temporal/especiais.parquet`;
- `dados/analitico/transferegov_temporal/municipio_ano_historico.parquet`;
- `dados/analitico/transferegov_temporal/censura_municipio_ano.parquet`;
- `dados/analitico/transferegov_temporal/sensibilidade_maturidade.parquet`.

Cada tabela deverá manter município, modalidade, identificador, evento, corte, carga, origem, hash, cobertura e censura. A raiz será configurável; caminhos absolutos não serão gravados.

## Viabilidade e interrupção

Viável para assinatura, desembolso, plano e ordem bancária datados. Condicional para vigência, situação atual, valores ajustados e resultados de contas. Implementação fica bloqueada se houver perda de conciliação, município/assinatura não confiáveis, maturidade não reproduzível, uso de situação atual, cobertura insuficiente, vazamento temporal, coleta/refresh necessário ou regressão. A aprovação futura exige testes offline, fronteiras 365/366, separação de modalidades e hashes verificáveis.
