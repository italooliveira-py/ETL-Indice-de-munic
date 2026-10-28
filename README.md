# ETL municipal — contexto para execução de projetos

A arquitetura foi reorganizada de forma incremental em `src/etl_municipal`, preservando os comandos anteriores. O produto é um **índice de contexto municipal para execução de projetos**, sem interpretação como probabilidade definitiva de falha.

## Entrega 5 versão 2 — risco observado em obras e sensibilidade de 180 dias

O [novo notebook de benchmarking](notebooks/03_E05_benchmark_risco_obras_180dias.ipynb) retoma o alvo da E04: **evento adverso observado em obra**. Ausência de repasse em **180 dias** é uma análise secundária separada. A escolha foi confirmada após a revisão dos documentos e do artigo do índice; ela não corresponde a prever o próprio índice, os pesos das variáveis ou estouro de custo.

```powershell
python -m pip install -r requirements-e05-lock.txt
python -m src.e05.revisao executar
python -m src.e05.revisao executar-notebook
```

Os snapshots públicos e as partições estão versionados em `dados/modelagem/e05_revisao/`; a execução comum é offline e usa seed 42. O novo [quadro para comparação coletiva](docs/e05/revisao_v2/quadro_comparacao_2024.csv) e a [nota metodológica](docs/e05/revisao_v2/README.md) separam os resultados de cada tarefa. Não comparar uma AUC do repasse com outra do evento adverso como se fossem o mesmo problema.

Foram preservados os 358 IDs da E04, com 127 projetos de 2022, 121 de 2023 e 110 de 2024. Os baselines são recalculados com o mesmo contexto e ajuste final das árvores. O contexto foi corrigido para não reutilizar 21 casos cujo ano de referência avançava até ou além da coorte. Ainda há limitações na data de observação dos rótulos: o benchmark é retrospectivo, não uma comprovação de previsão operacional de todas as obras. O teste de 2024 já havia sido consultado na E04.

MAE e RMSE aparecem apenas como erros auxiliares das **probabilidades**, em escala 0–1; o RMSE é a raiz do Brier. Não são erros de um desfecho financeiro contínuo. Prospecção, Escuta, Canvas e os documentos fornecidos não foram reescritos nesta revisão.

## Histórico da Entrega 5 versão 1 — repasse em 90 dias

A E05 usa exclusivamente dados públicos. O alvo é **`sem_repasse_90d`: 1 se não houver desembolso positivo até 90 dias após a assinatura; 0 se houver**. A unidade é o instrumento municipal da PB. IBGE, SICONFI e histórico do Transferegov entram como contexto anterior à assinatura. O experimento não mede diretamente estouro financeiro ou margem e não transforma a previsão em um risco definitivo do município.

O [notebook da E05](notebooks/02_E05_classificacao_risco_municipal.ipynb) compara Decision Tree Classifier e Random Forest Classifier com o baseline trivial e a Regressão Logística. A [Prospecção](docs/e05/PROSPECCAO.md), a [Escuta documental](docs/e05/ESCUTA.md) e o [Canvas atualizado](docs/e05/CANVAS_ML.md) estão consolidados e datados de 28/10/2026. Não foram inventados dados internos nem entrevistas.

**Reprodução rápida:** a base pública derivada, seu manifesto SHA-256 e os IDs das partições estão versionados em `dados/modelagem/e05/`. Depois de instalar as dependências, execute `python -m src.e05 executar --offline` e `python -m src.e05 executar-notebook --offline`. Na ausência da preparação local, os comandos usam esse snapshot, sem nova coleta e sem modificar os arquivos versionados. Isso permite ao Jorge usar exatamente os mesmos instrumentos de teste. Os comandos completos abaixo são para reconstruir/atualizar a coleta; uma carga posterior pode exigir uma nova versão do experimento.

```powershell
# Instalar as dependências da análise no Python x64 do projeto.
uv pip install --python .venv/Scripts/python.exe -r requirements-e05.txt

# Coleta longa, com retomada. Não usar --refresh na primeira execução.
& ".\.venv\Scripts\python.exe" -m src.etl_municipal --bronze-only --sources transferegov_discricionarias transferegov_especiais siconfi --resume

# Publicar o Gold enriquecido sem rede, depois da conclusão do Bronze.
& ".\.venv\Scripts\python.exe" -m src.etl_municipal --sources snapshot ibge_territorial transferegov_discricionarias transferegov_especiais siconfi --offline --resume

# Completar PIB/população 2019 do IBGE e congelar a base por instrumento.
& ".\.venv\Scripts\python.exe" -m src.e05 preparar-dados

# Treinar, avaliar e exportar o quadro com as mesmas linhas do teste de 2024.
& ".\.venv\Scripts\python.exe" -m src.e05 executar --offline

# Executar todas as células e salvar o notebook com suas saídas.
& ".\.venv\Scripts\python.exe" -m src.e05 executar-notebook --offline

# Testes do ETL e dos contratos da modelagem, sem coleta real.
& ".\.venv\Scripts\python.exe" -m unittest discover -s tests -v
```

Depois da primeira preparação, `python -m src.e05 preparar-dados --offline` reconstitui a base usando somente o Bronze local. O notebook reproduz os ajustes sem rede, a partir da base congelada em `output/e05/`. Os hashes e a configuração são conferidos antes da execução. Não executar dois coletores da mesma fonte no mesmo diretório.

`requirements-e05-lock.txt` registra o ambiente completo resolvido nesta validação; pode substituir `requirements-e05.txt` para reproduzir essas versões exatas. O lock anterior do ETL permanece separado.

**Partições:** desenvolvimento em 2022, validação em 2023 e reajuste em 2022–2023, sempre excluindo rótulos ainda não conhecidos na data de corte; teste nas assinaturas de 2024. Anos anteriores fornecem contexto, não exemplos adicionais de treino. Imputação e categorias são ajustadas dentro do pipeline. Poucos preditores foram pré-declarados; não há seleção baseada no teste.

**Limitação encontrada:** no treino de 2022–2023, o alvo de 90 dias possui somente a classe sem repasse. As árvores ajustam regras constantes; a Logística não é estimável e não é substituída artificialmente por outro modelo. A auditoria e as métricas executadas ficam em [resultados E05](docs/e05/RESULTADOS.md), e o quadro para comparação coletiva em `docs/e05/quadro_comparacao_2024.csv`. Uma acurácia elevada por prevalência não demonstra discriminação. Outros integrantes precisam usar o mesmo alvo e os mesmos IDs, não apenas o mesmo nome de ano.

## ETL e publicação municipal

A publicação Medallion já importa os snapshots verificados, separa eventos ObrasGov do painel municipal e coleta área, população censitária e densidade oficiais do Censo 2022 para os 223 municípios da Paraíba.

```powershell
# Depois de instalar requirements.txt:
python -m src.etl_municipal --sources snapshot ibge_territorial --resume

# Reproduzir o mesmo Bronze sem rede, depois da primeira coleta:
python -m src.etl_municipal --sources snapshot ibge_territorial --offline --resume

python -m unittest discover -s tests -v
```

As saídas novas ficam em `data/bronze/`, `data/silver/` e `data/gold/`. O painel exploratório mantém 1.115 linhas em 2020–2024; o recorte MVP 2020–2023 tem 892 linhas. `data/gold/CURRENT.json` aponta a geração publicada. Os agregados ObrasGov não entram nesse Gold; as 1.638 obras permanecem como eventos Silver. PIB 2024 é nulo com flag de período. As datas públicas ainda não verificadas impedem o uso direto em treino temporal.

O novo fluxo publica os snapshots versionados e o enriquecimento territorial; a coleta completa abaixo continua produzindo seus arquivos CSV legados. Para publicar uma coleta real, use `python -m src.etl_municipal --sources coleta_legada ibge_territorial --input-dir output --resume`. Transferegov e os recortes de DCA/RGF possuem transformação e publicação próprias quando selecionados. MUNIC permanece Bronze; SINISA, MapBiomas, bioma e tipologia continuam pendentes.

Consulte [arquitetura e reprodução](docs/ARQUITETURA.md), [plano revisado e pendências](docs/PLANO_MVP.md), [decisões](docs/adr/0001-publicacao-contexto-municipal.md) e [histórico da publicação](CHANGELOG.md).

## Coleta existente e saídas exploratórias

Este pacote monta a primeira base auditável para escolher variáveis do projeto de risco de execução de projetos públicos. Ele não calcula um índice definitivo e não atribui pesos arbitrários.

O fluxo produz:

1. dados brutos preservados por fonte;
2. tabelas normalizadas por município-ano para as APIs já automatizáveis;
3. inventário de todos os arquivos e colunas encontrados;
4. cobertura, faltantes, cardinalidade, variância e pares muito correlacionados;
5. status de cada variável candidata: disponível, derivável, ausente ou dependente de arquivo manual.

## Fontes contempladas

| Fonte | Acesso oficial | Uso no projeto | Situação no ETL |
|---|---|---|---|
| IBGE Localidades/SIDRA | https://servicodados.ibge.gov.br/api/docs/ | identificação, população e PIB | automático |
| SICONFI/STN | https://apidatalake.tesouro.gov.br/docs/siconfi/ | receitas, despesas, pessoal, investimento, restos a pagar e caixa | automático, via DCA |
| Transferegov.br | https://api-publica.transferegov.gestao.gov.br/ | instrumentos, valores, vigência, repasses e execução | arquivos históricos em `data/manual/transferegov/` |
| PNCP | https://pncp.gov.br/api/consulta/swagger-ui/index.html | demanda pública, compras e contratações similares | automático |
| ObrasGov | https://api-publica.obrasgov.gestao.gov.br/obras/docs | obras, situação, valor, execução e paralisação | automático |
| FNDE | https://www.gov.br/fnde/pt-br/acesso-a-informacao/dados-abertos | infraestrutura escolar e execução | ingestão manual; não somar novamente registros já presentes no ObrasGov |
| SINISA 2025 | https://www.gov.br/cidades/pt-br/acesso-a-informacao/acoes-e-programas/saneamento/sinisa/resultados-sinisa/resultados-sinisa-2025 | água, esgoto, resíduos e águas pluviais, referência 2024 | ZIP/XLSX em `data/manual/sinisa/` |
| SNIS Série Histórica | https://dadosabertos.cidades.gov.br/dataset/snis-serie-historica | histórico anterior ao SINISA | arquivos em `data/manual/snis/`; não concatenar com SINISA sem testar quebra metodológica |
| MapBiomas | https://brasil.mapbiomas.org/downloads/estatisticas/ | uso/cobertura da terra, urbanização, vegetação e água | planilha municipal em `data/manual/mapbiomas/` |
| ANA | https://dadosabertos.ana.gov.br/ | chuva, hidrologia, outorgas e eventos críticos | arquivos em `data/manual/ana/`; exige agregação espacial para município |

URLs diretas e observações de uso estão em `catalogo_fontes.csv`.

## Instalação

No PowerShell ou terminal, dentro desta pasta:

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Linux/macOS:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Escopo e primeiro teste

O `config.json` usa todos os municípios da **Paraíba**, resolvidos pelo catálogo oficial do IBGE, de 2020 a 2024. PNCP inicia em 2022. `escopo.tipo = "uf"` tem precedência sobre a lista `municipios`. Para o recorte original de Lucas do Rio Verde, use `--config config.municipio.json`, ou retire `escopo` e mantenha sua lista de municípios.

Comece com o teste limitado; as saídas ficam em `output/smoke/<execucao>/` e os checkpoints em `data/raw/smoke/`. Ele não altera os arquivos de configuração:

```powershell
python etl_primario.py --sources ibge siconfi pncp obrasgov --smoke-test
python etl_primario.py --config config.municipio.json --sources pncp --smoke-test
python -m unittest discover -s tests -v
```

O smoke usa o último ano configurado, dois municípios para IBGE/SICONFI, uma UF para PNCP/ObrasGov, modalidade PNCP 8 em **02 de janeiro**, e no máximo duas páginas por fonte paginada. No modo municipal limita a um município. Não busca detalhes por obra. Um limite atingido fica registrado como cobertura parcial, nunca como total anual.

Os comandos abaixo executam o escopo configurado, sem os limites do smoke. Para apenas IBGE e SICONFI:

```bash
python etl_primario.py --sources ibge siconfi
```

PNCP com retomada (a retomada já é o padrão):

```bash
python etl_primario.py --sources pncp --resume
```

O ObrasGov consulta a UF inteira porque sua API não oferece filtro municipal. Por isso ele fica separado:

```bash
python etl_primario.py --sources obrasgov
```

Para rodar tudo o que estiver configurado e perfilar também arquivos manuais:

```bash
python etl_primario.py --sources ibge siconfi pncp obrasgov
```

### Fonte político-eleitoral do TSE

A fonte `tse_eleitoral` é opt-in e não integra a lista padrão de `fontes`. Ela usa os arquivos oficiais do TSE para as edições municipais de 2016, 2020 e 2024, valida a correspondência dos 223 municípios da Paraíba e produz:

- `output/eventos_eleitorais_tse.csv`;
- `output/mandatos_municipais.csv`;
- `output/municipio_ano_politico.csv`;
- `output/qualidade_tse_eleitoral.csv`;
- `output/manifesto_tse_eleitoral.json`.

`municipio_ano_politico.csv` é uma fotografia às 00:00 de 1º de janeiro. Resultados ocorridos durante o ano só entram depois de `data_disponibilidade_adotada`; o resultado municipal de 2020, por exemplo, não altera a fotografia de 2020. Eleições suplementares permanecem eventos separados e só substituem um mandato quando `data/reference/tse_eleitoral/evidencias_posse.csv` contém posse diária validada em fonte oficial.

O coletor prefere HTTP Range e recorre ao ZIP integral quando o servidor não oferece intervalos consistentes. Tamanho e CRC validam o membro; `sha256_local` identifica o artefato persistido, sem ser apresentado como hash oficial do TSE.

No leiaute oficial observado de 2016 e 2020, o denominador de votos válidos é publicado como `QT_TOTAL_VOTOS_VALIDOS`; o esquema o normaliza para `QT_VOTOS_VALIDOS` por alias versionado, preservando o valor original e os metadados de qualidade. Se o denominador não estiver disponível, o evento permanece registrado e percentual/margem ficam ausentes.

O smoke mockado do TSE usa João Pessoa e um município sem segundo turno, consulta somente as edições 2016/2020 e produz 10 fotografias para 2020–2024. O smoke real continua exigindo autorização explícita.

Comandos propostos, ainda condicionados à autorização operacional:

```powershell
# Smoke isolado: dois municípios e edições 2016/2020
python etl_primario.py --sources tse_eleitoral --resume --smoke-test

# Coleta PB: executar somente depois de validar e aprovar o smoke
python etl_primario.py --sources tse_eleitoral --resume
```

Não use `--refresh` na primeira retomada. Uma correspondência estadual diferente de 223 vínculos válidos bloqueia a integração; falhas e transições pendentes permanecem ausentes e nunca são convertidas em zero.

Para atualizar apenas uma fonte: `python etl_primario.py --sources pncp --refresh`. Reinicie uma atualização interrompida com `--resume`; páginas antigas e novas ficam em gerações separadas. Não execute duas instâncias no mesmo diretório de checkpoints.

O catálogo IBGE e os lotes SIDRA são reutilizados. Use `--sources ibge --refresh` quando precisar atualizar a divisão territorial e as séries. Para qualquer fonte, `<fonte>_ano_inicial` e `<fonte>_ano_final` restringem o período geral; por exemplo, `siconfi_ano_inicial` ou `pncp_ano_final`.

O relatório [ENTREGA.md](ENTREGA.md) contém diagnóstico, resultados dos testes, chamadas estimadas, limites e a configuração completa recomendada. Em Windows ARM64, a validação adicional com as versões de `requirements.txt` foi feita com Python 3.12 **x64**, em `.validation/venv`.

## Como adicionar os arquivos das fontes sem API municipal

Baixe os arquivos oficiais e coloque-os em qualquer subpasta de `data/manual/`. O script reconhece CSV, CSV compactado, XLSX, XLS, JSON, Parquet e ZIP. Recomenda-se usar estas subpastas:

```text
data/manual/
  transferegov/
  fnde/
  sinisa/
  snis/
  mapbiomas/
  ana/
```

O arquivo do MapBiomas deve ser a tabela **Biomas, Estados e Municípios - Cobertura 30m - Coleção 11**. No SINISA, baixe as planilhas de Água, Esgotamento Sanitário, Resíduos Sólidos e Águas Pluviais.

Depois execute:

```bash
python etl_primario.py --only-profile
```

## Saídas principais

| Arquivo | Finalidade |
|---|---|
| `output/base_municipio_ano.csv` | uma linha por município e ano, com variáveis e indicadores já deriváveis |
| `output/eventos_pncp.csv` | registros de compras coletados no PNCP |
| `output/eventos_obrasgov.csv` | projetos/obras identificados para os municípios do recorte |
| `output/inventario_arquivos.csv` | arquivos e abas lidos |
| `output/inventario_colunas.csv` | todas as colunas encontradas e estatísticas básicas |
| `output/status_variaveis.csv` | confronto entre o catálogo desejado e o que realmente foi encontrado |
| `output/qualidade_variaveis.csv` | cobertura, variação e recomendação inicial |
| `output/pares_correlacionados.csv` | redundâncias potenciais por correlação de Spearman |
| `output/erros_coleta.csv` | falhas por fonte sem interromper as outras coletas |
| `output/manifesto_coleta.json` | escopo, período, modalidade, páginas esperadas/concluídas, contagem, estado, erro e horário UTC |
| `output/cobertura_fontes.csv` | cobertura observada por fonte/ano e estados dos coletores |
| `output/rejeitados_pncp.json` | registros sem código municipal válido ou fora do catálogo |
| `output/rejeitados_obrasgov.json` | registros fora do recorte, ambíguos ou não identificados |
| `output/projetos_multiterritoriais_obrasgov.json` | projetos com evidência de mais de um município, sem duplicação silenciosa |
| `output/cobertura_territorial_obrasgov.csv` | coleta da API, atribuição territorial e disponibilidade do agregado por ano |

Os nomes e formatos CSV/JSON existentes foram mantidos; há colunas adicionais de cobertura. O merge usa exclusivamente `codigo_ibge + ano`; nome e UF vêm do catálogo/seleção territorial. Antes de uma execução normal, saídas anteriores são copiadas para `output/historico/`. Dados brutos substituídos são preservados por conteúdo em `data/raw/historico/`.

PNCP só fornece zero quando todas as modalidades, janelas e páginas do ano foram concluídas. Falhas, truncamento do smoke e registros sem identificação municipal deixam os agregados ausentes. O zero significa **nenhum registro retornado no recorte do portal**, e não prova ausência de contratação. Valores monetários faltantes também permanecem ausentes. A deduplicação prioriza `numeroControlePNCP`; na ausência dele usa CNPJ + ano + sequencial da compra, ou hash do JSON completo quando faltam esses campos.

No ObrasGov, `status_coleta_api`, `status_atribuicao_territorial` e `status_agregado` são independentes. Código oficial, CNPJ municipal catalogado, executor/tomador concordantes, nome exato, CEP catalogado e ponto em malha oficial formam uma hierarquia conservadora. Não há fuzzy matching nem município mais próximo. Conflitos, projetos multiterritoriais e projetos municipais pendentes não viram zero; entidades positivamente federais/estaduais sem território municipal não bloqueiam todo o ano. A malha é opcional porque a distribuição estável do Shapely não é compatível com Windows ARM64; sem motor espacial, o ETL continua e preserva a pendência.

Em `eventos_obrasgov.csv`, `ano` é um alias legado de `ano_cadastro`. Anos previstos e efetivos ficam separados e datas ausentes não são imputadas. `evento_adverso_execucao` vale 1 para Cancelada, Inacabada ou Paralisada, 0 para Concluída e fica vazio para Cadastrada, Em execução ou estado desconhecido. `obra_parada` permanece como alias temporário. Situação, percentual de execução, datas finais e o alvo são informações de resultado e não são recomendados automaticamente como preditores anteriores ao projeto.

## Como escolher as variáveis depois do ETL

Use cinco filtros em ordem:

1. **Vínculo teórico:** a variável deve representar mecanismo plausível de risco ou oportunidade.
2. **Disponibilidade anterior ao evento:** nenhum dado publicado depois do problema pode explicar o passado.
3. **Cobertura:** como regra inicial, manter variáveis com pelo menos 70% de observações no recorte; de 50% a 70% ficam sob revisão.
4. **Informação:** eliminar constantes, quase constantes e duplicatas; investigar correlações absolutas acima de 0,85.
5. **Validação estatística:** somente após definir o alvo `Y(t+1)`.

O script só emite alertas de correlação quando há pelo menos 20 observações pareadas. A série isolada de Lucas do Rio Verde serve para auditoria retrospectiva, mas não possui amostra suficiente para seleção estatística.

Para o índice de visualização, pode-se adaptar o artigo: escolher três âncoras teóricas por dimensão, rodar Elastic Net separadamente para cada âncora e manter variáveis selecionadas de forma estável em pelo menos dois modelos. Isso é uma análise de estrutura do índice, não prova de causalidade.

Para a disciplina de aprendizagem supervisionada, a seleção deve usar diretamente o evento futuro:

```text
X do município no ano t -> evento de risco no ano t+1
```

Nesse caso, o Elastic Net deve estar dentro da validação temporal. Não use divisão aleatória de treino e teste.

## Limites que o ETL deixa explícitos

- A DCA do SICONFI permite construir proxies fiscais, mas o indicador legal de pessoal/RCL deve ser confirmado no RGF antes de uso final.
- O PNCP tem cobertura condicionada à publicação dos órgãos e à vigência do portal; ausência de registro não significa ausência de contratação.
- ObrasGov e FNDE/SIMEC podem conter o mesmo empreendimento.
- SNIS e SINISA têm transição metodológica; mantenha uma coluna de fonte/metodologia.


# Nota de governanÃ§a TSE

As decisÃµes operacionais usam `status_detalhe_apuracao`, `status_denominador`, `status_vencedor`, `status_evento` e `status_transicao`. `status_resultado` Ã© legado, mantido apenas para auditoria e compatibilidade; nÃ£o deve ser usado como filtro nem como preditor. `SQ_CANDIDATO_VENCEDOR` Ã© interno e nÃ£o Ã© publicado nas saÃ­das analÃ­ticas.
# Runtime validado no Windows ARM

No Windows ARM, o runtime recomendado para o ETL e o Python x64 do ambiente `.validation/venv`:

```powershell
& ".\.validation\venv\Scripts\python.exe" etl_primario.py --sources tse_eleitoral --resume
& ".\.validation\venv\Scripts\python.exe" etl_primario.py --sources ibge siconfi pncp obrasgov tse_eleitoral --resume
```

O ambiente validado usa Python 3.12.10 AMD64, pandas 2.3.3 e numpy 2.5.3. O Python ARM64 global (pandas 3.0.4 e numpy 2.3.5) apresentou encerramento nativo durante `pandas.to_datetime` sobre a serie de datas de mandatos. Essa falha e de runtime e nao deve ser interpretada como erro dos dados eleitorais.
