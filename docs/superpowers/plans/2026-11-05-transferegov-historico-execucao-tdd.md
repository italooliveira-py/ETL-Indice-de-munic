# Plano TDD — Histórico temporal de execução do Transferegov

## Gate atual

O desenho está atualizado com auditoria empírica e aguarda aprovação explícita. Até essa aprovação não haverá código de produção, coleta, refresh, alteração de Bronze/Silver/Gold operacional, alteração do índice PNCP, campos eleitorais, staging, commit, push ou Pull Request.

Worktree: `feature/transferegov-historico-execucao`; HEAD/origin-main: `f10172c`; `fc4f5c1` incorporado.

## Ajustes obrigatórios incorporados antes do RED

A implementação aprovada usará somente o pacote versionado em `dados/analitico/transferegov_temporal/versoes/<versao_analitica>/`, contendo `instrumentos.parquet`, `eventos_financeiros.parquet`, `especiais.parquet`, `municipio_ano_historico.parquet`, `censura_municipio_ano.parquet`, `sensibilidade_maturidade.parquet`, `elegibilidade_variaveis.csv` e `manifesto.json`. A versão será determinística a partir da versão Gold, hash do manifesto Gold, contrato temporal, configuração e parâmetros de maturidade. Não haverá `CURRENT.json` analítico nesta etapa.

Arquivos de implementação: `src/etl_municipal/analitico/transferegov_temporal.py`, `config/transferegov_historico_temporal.v0.json`, `tests/test_transferegov_historico.py` e documentação em `docs/transferegov/`. A configuração controlará período 2020–2024, cortes, maturidade de 365 dias, fronteiras 365/366, valores positivos, modalidades, métodos de sensibilidade, faixas de denominador e contrato.

Identificadores serão tratados como texto: convênio, proposta, desembolso, CNPJ, IBGE de sete dígitos, plano, empenho e ordem bancária. Duplicidade bloqueará publicação; não haverá descarte silencioso.

`municipio_ano_historico` terá visões acumulada, coorte de assinatura e janela de três anos, com nomes `taxa_atraso_365_acumulada`, `taxa_atraso_365_coorte` e `taxa_atraso_365_janela_3a`. A fotografia de 31/12/t somente poderá contextualizar instrumento assinado depois do corte; instrumento assinado em t usará no máximo a fotografia de t-1. Nenhuma taxa será apresentada como probabilidade futura.

Zero exige cobertura confirmada, município no universo e consulta completa. Caso contrário, usa-se nulo com status/motivo separado. Especiais permanecem separadas e não recebem desfecho de 365 dias.

## Fase 0 — Auditoria reproduzível, concluída

Usar somente leitura, com `TRANSFEREGOV_DATA_ROOT` ou parâmetro equivalente: validar manifesto, `gold/CURRENT.json`, `data/silver`, `data/bronze`; calcular SHA-256; registrar versão, carga, linhas, colunas e chaves; conciliar instrumentos/desembolsos; reconstruir 2020–2024 em memória; imprimir denominadores e métodos.

Resultado: Gold `65260a170ee18cd79501`, manifesto SHA-256 `28E24585431DC29B0DA53B10FD0811B91A02BA79BD00484EA6297D9ABB84F5B5`, 6.182 instrumentos, 9.411 desembolsos, 223 municípios e carga `17/07/2026 06:30:47`. Sem instrumentos sem município/fora da PB, desembolsos órfãos ou anteriores à assinatura, nem valores de desembolso negativos/zero/nulos. Há 21 datas de publicação inválidas; esse campo não será evento. Testes históricos: 40 casos, 39 aprovados e 1 erro por ausência do Gold congelado no caminho relativo do repositório; o artefato externo não foi copiado.

## Fase 1 — Contrato de saída analítica isolada

RED: fixtures com IDs duplicados, datas inválidas, município ausente, modalidade, carga e valores inválidos.

GREEN, somente após aprovação: criar apenas:

- `dados/analitico/transferegov_temporal/instrumentos.parquet`;
- `dados/analitico/transferegov_temporal/eventos_financeiros.parquet`;
- `dados/analitico/transferegov_temporal/especiais.parquet`;
- `dados/analitico/transferegov_temporal/municipio_ano_historico.parquet`;
- `dados/analitico/transferegov_temporal/censura_municipio_ano.parquet`;
- `dados/analitico/transferegov_temporal/sensibilidade_maturidade.parquet`.

Nenhum arquivo novo em `data/bronze`, `data/silver` ou `data/gold` operacional. Preservar proveniência, hash, modalidade, município, identificador, evento, carga e estado temporal.

## Fase 2 — Temporalidade e maturidade

RED: assinatura e desembolso somente até o corte; desembolso positivo e posterior/igual à assinatura; dia 365 no prazo; dia 366 atraso; maturidade posterior censurada; situação atual, resultados posteriores e `data_carga` excluídos como evento.

GREEN: funções puras sem rede, com estados `observado`, `sem_desembolso_ate_maturidade`, `censurado_365_incompleto`, `desfecho_indisponivel` e `indisponivel_sem_data`. Ausência, não aplicabilidade e censura nunca viram zero.

## Fase 3 — Município-ano e denominadores

RED: `one_to_one` município × ano, 1.115 chaves quando completo, faixas 0/1–4/5–9/10–19/20+, cobertura, atraso, no prazo, censura e concentração. GREEN: medidas descritivas com denominador explícito.

Distribuição auditada:

| ano | 0 | 1–4 | 5–9 | 10–19 | 20+ |
|---:|---:|---:|---:|---:|---:|
| 2020 | 0 | 3 | 25 | 118 | 77 |
| 2021 | 0 | 0 | 17 | 95 | 111 |
| 2022 | 0 | 0 | 11 | 94 | 118 |
| 2023 | 0 | 0 | 4 | 78 | 141 |
| 2024 | 0 | 0 | 4 | 71 | 148 |

## Fase 4 — Comparação sem seleção automática

RED: taxa bruta, mínimo 5, Beta-Binomial Beta(1,1) e shrinkage estadual `k=5`, comparando cobertura, estabilidade, posições, sensibilidade, interpretação e limitações. GREEN: somente relatório de sensibilidade; nenhuma escolha por associação futura.

## Fase 5 — Modalidades separadas

RED: manter Discricionárias/Legais e Especiais separadas. GREEN: planos pelo ano do plano e pagamentos pela ordem bancária; não aplicar 365 dias às Especiais sem data de assinatura equivalente e contrato defensável.

## Fase 6 — Validação de vazamento

RED: inserir eventos/desfechos posteriores, situação atual e carga posterior. GREEN: matriz de elegibilidade `apta_data_evento`, `descritiva_retrospectiva`, `censurada` ou `indisponivel`.

## Fase 7 — Reprodução offline

Após aprovação: executar fixtures, validar esquema/chaves/hashes, reproduzir duas execuções offline em diretórios temporários, comparar hashes/conteúdo, auditar caminhos absolutos/credenciais, executar compileall, pip check, suíte específica e suíte completa. Os quatro erros históricos E05 só permanecem se idênticos ao baseline.

## Critérios de interrupção

- artefatos ausentes ou hashes não verificáveis;
- instrumentos/desembolsos não conciliáveis;
- município ou assinatura não confiáveis;
- uso de situação atual ou carga como evento;
- maturidade/censura não reproduzíveis;
- cobertura insuficiente;
- mistura de modalidades;
- vazamento temporal;
- coleta, refresh ou alteração operacional necessários;
- regressão em testes existentes.

## Verificações futuras, após aprovação

```powershell
<PYTHON_X64> -m unittest tests.test_transferegov_historico -v
<PYTHON_X64> -m unittest tests.test_transferegov_bronze tests.test_e05_transferegov_atraso -v
<PYTHON_X64> -m unittest discover -s tests -v
<PYTHON_X64> -m compileall -q src tests
<PYTHON_X64> -m pip check
git diff --check
```

Nenhuma coleta, refresh, publicação operacional, alteração de dados, commit ou push faz parte desta fase.
