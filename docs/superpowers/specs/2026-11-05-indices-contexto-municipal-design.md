# Especificacao - Indices de Contexto Municipal

## Escopo aprovado

Produtos experimentais, descritivos, anuais e relativos entre municipios no mesmo ano. Periodo 2020-2024; PNCP sem retropreenchimento. Nao alterar Bronze/Silver/Gold operacional, MUNIC, coleta, refresh, commit ou push.

Produtos: `indice_vulnerabilidade_fiscal`, `indice_estrutura_vinculos_institucionais`, `indice_contexto_estrutural_municipal`, `indice_intensidade_contratual_pncp`, `historico_execucao_transferegov` nulo, `status_historico_execucao = indisponivel_dados_transferegov`, `indice_contexto_ampliado` nulo apenas se exigido por compatibilidade e `versao_metodologia_indice`.

Nao sao produtos de risco, probabilidade de falha, atraso, recomendacao ou execucao validada.

## Temporalidade

Cada linha publica `ano_referencia_indice`, `data_corte_indice` (31 de dezembro), `status_temporal_indice` e `motivo_status_temporal`. Uma variavel e point-in-time apenas se disponivel ate o corte. Fonte do proprio ano publicada depois pode compor fotografia descritiva retrospectiva, marcada `descritivo_retrospectivo`, mas nao e apta a predicao no inicio do ano. PNCP acumulado no proprio ano e contexto observado ate o encerramento, sem prever eventos anteriores no ano sem defasagem. Manifesto: `apto_analise_descritiva`, `apto_predicao_point_in_time`, `justificativa_temporal`. Regras auditadas do MUNIC nao mudam.

## Variaveis e formulas

Fiscal: `dependencia_transferencias = transferencias_correntes_realizadas / receita_total_realizada`; `restos_pagar_sobre_receita = restos_pagar_total / receita_total_realizada`; `caixa_sobre_receita = caixa_equivalentes / receita_total_realizada` (inversa); `pressao_pessoal_proxy = despesa_pessoal_liquidada / receita_total_realizada`; `resultado_orcamentario_proxy = (receita_total_realizada - despesa_total_liquidada) / receita_total_realizada` (margem relativa, inversa). Receita estritamente positiva; margem negativa valida; nulo/infinito/denominador invalido nulo; exigir 4/5 componentes.

Institucional: `proporcao_pessoal_estatutario = pessoal_estatutario / pessoal_ativo` (inversa); `proporcao_pessoal_comissionado = pessoal_comissionado / pessoal_ativo` (direta); `proporcao_pessoal_sem_vinculo = pessoal_sem_vinculo / pessoal_ativo` (direta). Denominador `pessoal_ativo > 0`; valores em [0,1]; nulos nao imputados; exigir pelo menos dois componentes distintos. Spearman estatutario-sem vinculo -0,715 e possivel redundancia composicional, nao erro; outras correlacoes auditadas: -0,275 e -0,327.

Configuracao versionada declara os tres componentes e direcoes. Sensibilidades sem estatutarios e sem pessoal sem vinculo sao somente diagnosticas e nao mudam a formula; qualquer composicao futura exige nova versao.

PNCP: `contratacoes_por_mil_habitantes = total_contratacoes / populacao * 1000`; `exposicao_contratual_sobre_receita = valor_estimado_contratacoes / receita_total_realizada`; `proporcao_contratacoes_similares = contratacoes_similares / total_contratacoes`. Populacao/receita positivas; denominador invalido nulo; proporcao fora de [0,1] rejeitada; `log1p` apenas nas duas intensidades.

Subgrupos: `subindice_intensidade_geral_pncp` e media dos percentis das duas intensidades; `subindice_similaridade_pncp` e percentil da proporcao similar; `indice_intensidade_contratual_pncp = 0,5 * subindice_intensidade_geral_pncp + 0,5 * subindice_similaridade_pncp`, somente se ambos validos. Zero confirmado com cobertura completa e numeradores confirmados gera zero nas intensidades; similaridade nula com `status_similaridade_pncp = nao_aplicavel_sem_contratacoes`; subindice geral preservado, indice completo nulo, sem penalizacao. Alto significa intensidade/exposicao, nao risco; similaridade nao indica dificuldade/falha.

## Normalizacao e faixas

Winsorizacao anual P1/P99, interpolacao linear, somente validos; registrar limites e contagens abaixo/acima; nulos preservados. Percentis por ranking anual com empates em rank medio: `(rank_medio - 1) / (n_validos - 1) * 100`; um valor valido = 50; nulos permanecem; inversao `100 - percentil` somente depois do ranking.

Faixas por Q1/Q2/Q3 anuais, interpolacao linear: baixo `<= Q1`; moderado `Q1 < x <= Q2`; alto `Q2 < x <= Q3`; muito_alto `> Q3`; empate no limite fica na faixa inferior. Menos de quatro valores distintos validos: faixa nula e motivo no manifesto.

Estrutural somente se fiscal e institucional aprovados: `0,5 * indice_vulnerabilidade_fiscal + 0,5 * indice_estrutura_vinculos_institucionais`. Publicar coberturas, quantidades e faixas separadas por indice; aliases genericos somente se documentados como estrutural.

## Transferegov e exclusoes

`historico_execucao_transferegov` permanece nulo e `status_historico_execucao = indisponivel_dados_transferegov`; ausencia nao reduz indice nem vira zero. O PNCP representa contexto de contratacao publica e nao comprova execucao material ou financeira; historico de execucao fica indisponivel ate integracao temporalmente valida do Transferegov.

Excluir resultados posteriores ao corte, status operacional, metadados, vazamento temporal, variaveis ambientais, bioma, tipologia rural-urbana, score, ranking, imputacao automatica e causalidade.

## Arquivos autorizados

`config/indice_contexto_municipal.v0.json`; modulo isolado em `src/`; `tests/test_indices_contexto.py`; `notebooks/05_MVP_indices_contexto_municipal.ipynb`; `docs/indices/CONTRATO_INDICES.md`; `docs/indices/DICIONARIO_COMPONENTES.md`; `docs/indices/RELATORIO_METODOLOGICO.md`; `docs/indices/RELATORIO_SENSIBILIDADE.md`; `dados/visualizacao/indices_contexto_municipal.csv`; `dados/visualizacao/indices_contexto_municipal.parquet`; `dados/visualizacao/manifesto_indices_contexto.json`; tabelas auxiliares proprias. Nao sobrescrever MUNIC; referenciar hash da entrada; nao gravar caminhos absolutos.
