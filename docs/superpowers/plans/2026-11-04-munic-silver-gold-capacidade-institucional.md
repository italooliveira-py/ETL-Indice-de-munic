# Plano TDD — MUNIC Silver/Gold

## Pré-condições verificadas

- Worktree isolado: `feature/munic-silver-gold-capacidade-institucional`.
- Commit-base: `5e8ed87`.
- Ambiente: `venv/Scripts/python.exe`, CPython 3.12.10 AMD64, `win-amd64`.
- Dependências: requirements-e05-lock.txt; `pip check` sem problemas.
- Baseline: 217 testes, 213 aprovados, 4 erros históricos de artefatos E05 ausentes. Nenhum código de produção será alterado para contornar esses erros.
- ODS só será suportado se um arquivo autorizado exigir esse formato; nesse caso, adicionar `odfpy` e repetir `pip check`. XLSX usa `openpyxl` e Parquet usa `pyarrow`.

## Review focus

- Arquivo revisado não substitui o original e mantém ambos no manifesto.
- Pergunta ausente e célula vazia não viram zero.
- Código municipal precisa permanecer com sete dígitos e UF PB.
- Edição publicada depois do corte não entra na fotografia anterior.
- Merge MUNIC não multiplica linhas nem altera colunas preexistentes.
- Indicador proporcional não produz infinito ou zero artificial com denominador inválido.

## Tarefas

### 1. Catálogo versionado e leitura segura

**Arquivos:** criar `src/etl_municipal/fontes/munic_catalogo.py`, catálogo em `data/reference/munic/variaveis.json`, testes em `tests/test_munic_transformacao.py`.

- RED: testar edições autorizadas, ausência explícita de 2022, identidade `(edicao, bloco, codigo_original)`, alias versionado e rejeição de código não catalogado.
- GREEN: implementar catálogo tipado, lookup determinístico e erro de esquema.
- Verificar: `venv/Scripts/python.exe -m unittest tests.test_munic_transformacao -v`.

### 2. Normalização de identificadores e estados

**Arquivos:** modificar `src/etl_municipal/fontes/munic_transformacao.py`; testes no mesmo arquivo de testes.

- RED: testar código de sete dígitos, filtragem PB, sentinelas, vazios, respostas negativas, não aplicável e pergunta ausente.
- GREEN: implementar `normalizar_observacoes(caminho, edicao, catalogo, referencia) -> DataFrame` e estados explícitos sem preenchimento artificial.
- Verificar cardinalidade de 223 municípios quando o fixture representar a edição completa.

### 3. Harmonização e indicadores de RH

**Arquivos:** `munic_transformacao.py`, catálogo e testes.

- RED: testar aliases entre edições, unidade/tipo, proporções em `[0,1]`, por mil habitantes e denominador zero retornando nulo.
- GREEN: implementar regras declaradas por variável; rejeitar variáveis não comparáveis e resultados posteriores.
- Verificar cobertura mínima de 70% antes de aprovar uma variável para Gold.

### 4. Silver por edição e observações

**Arquivos:** `munic_transformacao.py`, `src/etl_municipal/core/contratos.py` se necessário, testes.

- RED: testar `silver/munic_municipio_edicao_versao` com chave município × edição × versão, `silver/munic_observacoes_versao` com a chave quádrupla e preservação simultânea de original/revisão.
- GREEN: implementar `construir_silver_munic_versionado(...) -> dict[str, DataFrame]`; depois implementar `construir_silver_munic(...) -> dict[str, DataFrame]` como camada analítica adotada com `versao_adotada`, datas e SHA-256.
- Verificar cinco edições, revisões preservadas, ausência de linha 2022 e nenhuma substituição silenciosa.

### 5. Gold institucional por edição e point-in-time

**Arquivos:** `munic_transformacao.py`, testes.

- RED: testar `gold/munic_capacidade_institucional_edicao` e seleção `construir_painel_munic(...)` no corte de 31/12.
- GREEN: implementar `gold/munic_capacidade_institucional_ano` e `gold/munic_disponibilidade_variavel`, selecionando a edição e versão mais recentes elegíveis por variável.
- Verificar MUNIC 2021 original em 2022, revisão de 2021 somente a partir de 25/04/2024, MUNIC 2023 em 2024, MUNIC 2024 fora de 2020–2024 e ausência de 2022 sem virar ausência institucional.
- Testar denominador populacional do próprio ano, sem retropropagação do Censo 2022.

### 6. Integração aditiva ao painel

**Arquivos:** modificar `src/etl_municipal/publicacao.py` e `src/etl_municipal/__main__.py`; testes de regressão em `tests/test_medallion.py` e novo arquivo MUNIC.

- RED: testar merge `one_to_one`, 223 × 5 = 1.115 linhas, chaves únicas e igualdade material das colunas anteriores ao publicar sem MUNIC.
- GREEN: aceitar MUNIC como adicional opcional, manter grupos/status existentes e rejeitar duplicidade ou UF fora de PB.
- Verificar publicação isolada e consolidada sem `--refresh` das outras fontes.

### 7. Bronze offline/resume e smoke

**Arquivos:** modificar `src/etl_municipal/fontes/munic.py` e CLI; ampliar `tests/test_bronze_siconfi_munic.py`.

- RED: testar metadados de URL, coleta, Last-Modified, tamanho, SHA-256, revisão separada, `--offline` sem rede, `--resume` apenas para artefato válido e smoke limitado a 2019/2024.
- GREEN: completar manifesto e validação sem sobrescrever bytes.
- Verificar com fixtures mockados; não executar coleta completa nem refresh real nesta fase.

### 8. Exportações e documentação

**Arquivos:** criar `docs/CONTRATO_DADOS_MUNIC.md`, `docs/DICIONARIO_VARIAVEIS_MUNIC.md`, `docs/RELATORIO_QUALIDADE_MUNIC.md`, `docs/GUIA_REPRODUCAO_VISUALIZACAO.md`; atualizar `docs/MAPEAMENTO_FONTES.md`, `docs/ARQUITETURA.md`, `docs/PLANO_MVP.md`, `CHANGELOG.md`.

- RED: testar presença de dicionário, dimensões, fontes, edição, regra temporal, cobertura, status e recomendação.
- GREEN: publicar Parquet/CSV UTF-8 e manifesto de qualidade.
- Verificar que a documentação distingue fato, hipótese, limitação e exclusões ambientais.

### 9. Smoke, coleta completa e regressão A/B

**Arquivos:** fixtures/testes de Bronze e integração, sem alterar outros Bronzes.

- RED: testar smoke 2019/2024, depois comparar duas publicações temporárias: pipeline atual sem MUNIC e pipeline com MUNIC.
- GREEN: executar smoke real autorizado; após atender contratos, coletar 2019, 2020, 2021, 2023 e 2024 com `--resume`; publicar Silver/Gold e comparar 1.115 chaves, tipos, nulos, valores, status e hashes preexistentes.
- Verificar que a única diferença A/B são tabelas/colunas/proveniência MUNIC e qualidade; qualquer quinto erro ou divergência material bloqueia.

### 10. Reprodução offline e auditoria final

**Arquivos:** testes de integração e scripts existentes, sem alterar snapshots preexistentes.

- RED: comparar Gold anterior e Gold sem MUNIC, testar hashes idênticos em duas execuções offline.
- GREEN: integrar a comparação ao fluxo de validação e bloquear publicação quando diferenças preexistentes surgirem.
- Verificar `py_compile`, suíte MUNIC, suíte completa, `pip check`, `git diff --check` e auditoria das cardinalidades.

## Ordem de execução

1. Executar a suíte-base somente para referência, sem modificar os quatro artefatos históricos.
2. Executar tarefas 1–5 em ciclos RED/GREEN; checkpoint: catálogo/normalização e Silver versionado.
3. Executar tarefa 6; checkpoint: Gold point-in-time.
4. Executar tarefa 7 com smoke real 2019/2024; checkpoint: smoke aprovado.
5. Executar tarefa 9, coleta completa e integração; checkpoint: coleta final e regressão A/B.
6. Executar documentação, reprodução offline e suíte completa.
7. Antes de qualquer alegação de conclusão, reportar: “213 testes-base aprovados, quatro erros históricos E05 preservados e nenhum novo erro introduzido”, ou o estado real caso haja regressão.

## Política de ressalva oficial

O FTP oficial retornou 404 para os nomes originais de 2019 e 2021. Isso não bloqueia toda a integração: o manifesto deve marcar `revisao_unica_disponivel`, `original_disponivel=false`, motivo, data original, data da revisão, escopo da errata, URL da nota e precisão temporal. `MREG0151–MREG0153` e `MCUL42` ficam apenas em auditoria e fora do Gold largo; RH e demais variáveis não listadas na errata podem seguir com evidência temporal condicional. A condição final será `apta_com_ressalva_documentada`.

## Comandos de verificação previstos

```powershell
venv\Scripts\python.exe -m unittest tests.test_munic_transformacao -v
venv\Scripts\python.exe -m unittest discover -s tests -v
venv\Scripts\python.exe -m compileall -q src tests
venv\Scripts\python.exe -m pip check
git diff --check
```

Nenhum commit, push ou refresh das demais fontes faz parte deste plano.
