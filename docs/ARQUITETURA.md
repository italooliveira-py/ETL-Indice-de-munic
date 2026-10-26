# Arquitetura do ETL municipal

O produto é um **índice de contexto municipal para execução de projetos**. A publicação não calcula probabilidade de falha, pesos ou imputações. A migração é incremental: os coletores existentes continuam disponíveis; a nova publicação é validada separadamente.

```text
etl_primario.py                  entrada compatível da coleta existente
etl_confiabilidade.py            import compatível de HTTP/cache/checkpoint
etl_tse_eleitoral.py             import compatível eleitoral
obrasgov_qualidade.py            import compatível territorial de obras
src/
  etl_municipal/
    __main__.py                 orquestra migração e publicação
    core/
      armazenamento.py          Bronze imutável e manifesto SHA-256
      contratos.py              identidade, grão, painel, tipos e faixas
    fontes/
      snapshot.py               importação verificável dos snapshots
      coleta_legada.py          importação das saídas de uma coleta real
      ibge_territorial.py        API oficial → Bronze → contexto 2022
      transferegov_discricionarias.py  CSV nacionais → Bronze (transformação pendente)
      transferegov_especiais.py  API, filtro PB na consulta → Bronze (transformação pendente)
    publicacao.py               Silver/Gold, auditoria e versionamento
    legado/                     implementação anterior preservada
  e04_baseline_obras_publicas.py experimento supervisionado independente
dados/bruto/                    snapshots versionados da prova de conceito
data/
  bronze/<fonte>/<sha256>/       bytes originais + manifesto por arquivo
  silver/                       tabelas por fonte e grão
  gold/
    base_municipio_ano.parquet   painel exploratório 2020–2024
    base_municipio_ano_mvp.parquet painel MVP 2020–2023
    base_municipio.parquet      contexto estático do Censo 2022
    auditoria_cobertura.parquet cobertura por variável/ano
    CURRENT.json                aponta a geração publicada
    versoes/<versao>/           conjunto íntegro de tabelas + manifesto
  ref/                          catálogo oficial e ponteiros de retomada
  reference/                    referências eleitorais já existentes
  raw/                          cache/checkpoints dos coletores legados
  manual/                       arquivos oficiais ainda sem integração
tests/                          contratos e regressões sem rede
```

## Fronteiras e compatibilidade

Os quatro arquivos históricos da raiz passam a ser entradas pequenas. O alias de módulo preserva imports e mocks: a suíte original continua testando a mesma implementação. Os diretórios raiz são calculados explicitamente, preservando `config.json`, catálogos e referências eleitorais.

`requirements.txt` continua definindo as faixas de dependências suportadas; `requirements-lock.txt` registra as versões exatas do ambiente usado nesta validação com Python 3.12 x64. Para reproduzir esse ambiente, instale `python -m pip install -r requirements-lock.txt`. O lock não inclui as dependências opcionais do experimento E04.

`legado/primario.py` ainda concentra os coletores IBGE econômico, DCA, PNCP e ObrasGov. Isso é dívida conhecida, não uma modularização fictícia. Extraí-los um por vez exige conservar checkpoints, testes e semântica de cobertura. Fontes novas devem seguir `extrair(sessao, raiz, refresh=False)` e `transformar(caminhos)`; não devem ampliar esse módulo. A fonte snapshot usa a mesma separação, com extração de arquivos locais.

A CLI Medallion importa os snapshots disponíveis, verificados pelo manifesto original, ou as saídas de uma coleta real, pelo adaptador `coleta_legada`. O adaptador exige resumo de execução PB 2020–2024 fora do smoke e verifica as contagens; preserva também manifestos, erros e cobertura quando disponíveis. Não substitui a coleta normal nem afirma reproduzir chamadas originais a partir dos snapshots. Os números de eventos PNCP e mandatos não podem ser recontados a partir dos dois snapshots versionados; exigem as saídas completas da coleta.

## Contratos

- Identidade: `codigo_ibge` textual, sete dígitos, PB, pertencente ao catálogo usado na publicação.
- Painel: exatamente 223 × 5 chaves distintas; o MVP é uma seleção de 223 × 4.
- Contexto estático: 223 chaves municipais distintas. O catálogo de Localidades fornece a validação externa quando a fonte territorial é selecionada.
- Eventos ObrasGov: identificador de projeto único e território válido; não é exigida presença de eventos nos 223 municípios.
- Área, população e densidade: positivas e sem nulos na fonte territorial; densidade conferida com população/área, tolerância de 0,02 hab/km² por arredondamento.
- PNCP: ausência confirmada depende de cobertura completa e zero explicitamente publicado pelo pipeline anterior. Falta de dado continua nula.
- Resultados e agregados ObrasGov ficam fora do Gold municipal. Os snapshots originais e a prova de conceito permanecem preservados.

`silver/observacoes_municipio_ano.parquet` fornece status por município, ano e variável: `observado`, `parcial`, `sem_registro_confirmado`, `indisponivel` e `fora_periodo`. O valor nessa tabela de auditoria é textual para permitir variáveis numéricas, booleanas e categóricas; nas tabelas analíticas os tipos são preservados. `status_<fonte>` resume completude das variáveis daquela fonte, sem substituir os estados de coleta legados.

## Temporalidade

Área e densidade censitárias são contexto estático de referência 2022; não são repetidas artificialmente no painel 2020–2024. Bioma e tipologia permanecem nulos com status explícito. PIB 2024 e seu derivado ficam nulos com `status_pib=fora_periodo`; os demais campos observados de 2024 não são descartados.

Datas de coleta e preservação não são datas públicas de disponibilidade. As datas não documentadas ficam nulas e o manifesto declara `apto_para_treino_temporal=false`. Mesmo que o TSE tenha temporalidade própria validada, a migração do painel consolidado não presume disponibilidade histórica dos demais campos. O Gold não deve ser usado diretamente como `X(t)` em modelos até haver datas de divulgação e junção point-in-time.

## Reprodução e publicação

```powershell
# Migração inteiramente local dos snapshots
python -m src.etl_municipal --sources snapshot --offline --resume

# Catálogo e contexto territorial oficiais, com cache verificado
python -m src.etl_municipal --sources snapshot ibge_territorial --resume

# Mesma publicação sem qualquer consulta, depois da primeira coleta
python -m src.etl_municipal --sources snapshot ibge_territorial --offline --resume

# Nova extração territorial; versões anteriores são preservadas
python -m src.etl_municipal --sources snapshot ibge_territorial --refresh

# Depois de uma coleta completa pelo comando legado:
python -m src.etl_municipal --sources coleta_legada ibge_territorial --input-dir output --resume

# Fontes ainda sem transformação: somente carga no Bronze
python -m src.etl_municipal --bronze-only --sources transferegov_discricionarias transferegov_especiais
python -m src.etl_municipal --bronze-only --offline --sources transferegov_discricionarias transferegov_especiais

# Isolar uma experiência
python -m src.etl_municipal --sources snapshot --offline --data-dir output/experimento_medallion

python -m unittest discover -s tests -v
```

Bronze guarda os bytes HTTP originais e metadados de origem, tamanho e SHA-256. Filtros só entram no Bronze quando a própria fonte os aplica na consulta, como `eq.PB` nas Transferências Especiais; arquivos nacionais sem filtro no servidor, como os CSV das Discricionárias, são preservados inteiros e recortados no Silver. Na importação local, a origem é explicitamente `repositorio:...`. Retomada verifica os hashes. Cada versão Gold identifica os hashes Parquet e a proveniência; reexecutar o mesmo Bronze com o mesmo runtime deve produzir a mesma versão. Mudanças de pandas/pyarrow podem alterar a serialização: compare também conteúdo e schema ao migrar o runtime.

Todos os contratos são avaliados antes da publicação. `CURRENT.json` só muda depois de todas as tabelas da geração existirem. Para uma leitura consistente, abra esse ponteiro e leia as tabelas dentro de `gold/versoes/<versao>/`; os caminhos diretos Silver/Gold são atalhos com substituição atômica individual, não uma transação de múltiplos arquivos. Não executar dois escritores no mesmo `--data-dir`.

Os artefatos gerados não são versionados no Git. Decisões, catálogos, testes e evidências resumidas são versionados. `data/raw/`, `data/reference/` e `dados/bruto/` não foram renomeados: migrá-los abruptamente quebraria os checkpoints, as referências TSE e os notebooks existentes.
