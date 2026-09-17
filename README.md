# ETL primário - risco e oportunidade municipal

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

Os nomes e formatos CSV/JSON existentes foram mantidos; há colunas adicionais de cobertura. O merge usa exclusivamente `codigo_ibge + ano`; nome e UF vêm do catálogo/seleção territorial. Antes de uma execução normal, saídas anteriores são copiadas para `output/historico/`. Dados brutos substituídos são preservados por conteúdo em `data/raw/historico/`.

PNCP só fornece zero quando todas as modalidades, janelas e páginas do ano foram concluídas. Falhas, truncamento do smoke e registros sem identificação municipal deixam os agregados ausentes. O zero significa **nenhum registro retornado no recorte do portal**, e não prova ausência de contratação. Valores monetários faltantes também permanecem ausentes. A deduplicação prioriza `numeroControlePNCP`; na ausência dele usa CNPJ + ano + sequencial da compra, ou hash do JSON completo quando faltam esses campos.

No ObrasGov, códigos oficiais têm prioridade. Nomes são comparados integralmente, com normalização de acentos/caixa e prefixos institucionais, somente em executor/tomador. Ambiguidades não são atribuídas ao primeiro município. Registros comprovadamente de outra cidade são descartados do recorte; registros não identificados tornam a cobertura conservadoramente parcial. Execução física e histórico continuam sendo consultados por projeto, com paginação/cache, apenas fora do smoke.

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


