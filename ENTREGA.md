# Entrega — confiabilidade e escopo Paraíba

Implementação em dois checkpoints, revalidada em 21/09/2026. Não houve commit, push, publicação, exclusão de dados anteriores nem coleta estadual completa. Os arquivos originais em `output/` foram preservados; as integrações desta implementação usaram exclusivamente `output/smoke/` e `data/raw/smoke/`.

## Diagnóstico

O PNCP executava município × ano × modalidade × página, consultando anos completos desde 2020, com apenas 0,05 s de pausa entre páginas. Havia retry no adaptador HTTP, mas nenhum checkpoint por página; o arquivo bruto só era escrito depois do ano. Falhas eram registradas, porém dados incompletos podiam ser agregados como totais. Esse desenho ampliava a exposição a 429, 503 e timeouts e não permitia retomada confiável. Os erros também dependem da disponibilidade externa; a implementação não elimina indisponibilidades do portal.

No ObrasGov havia `next(..., nomes[0])`, que podia atribuir uma obra ao primeiro município. O merge dependia de código, nome, UF e ano. Não havia cache reutilizável de DCA nem de páginas do ObrasGov.

## Arquivos

Alterados: `etl_primario.py`, `config.json`, `README.md`.

Criados: `etl_confiabilidade.py`, `config.municipio.json`, `tests/test_checkpoint1.py`, `tests/test_checkpoint2.py`, `tests/test_integridade.py` e este relatório. `requirements.txt` não foi alterado. `.validation/` contém ambiente x64 e evidências de teste; não é parte da lógica do ETL.

## Checkpoint 1

- Política HTTP central, sem retry duplicado no adaptador: 429/500/502/503/504, timeouts, falhas de conexão e desconexão remota. `Retry-After` aceita segundos e data HTTP. Backoff exponencial com jitter, tentativas/timeout configuráveis, pausa sequencial entre chamadas e espera adicional em 429/503.
- Janelas de meses sem lacunas/sobreposição, datas PNCP `AAAAMMDD` e início padrão em 2022, independente do período geral.
- JSON validado, escrita temporária com `fsync` e renomeação atômica, cache por escopo/período/modalidade/tamanho/página. Resposta inválida não vira ausência confirmada.
- Manifesto atualizado a cada página e em interrupções. Conferência de número de página, totais e quantidade final quando declarados pela API.
- `--resume` padrão, `--refresh` restrito às fontes selecionadas, gerações separadas para não misturar uma atualização interrompida com páginas antigas.
- Deduplicação antes da agregação. Chave principal `numeroControlePNCP`; alternativa CNPJ/ano/sequencial; último recurso hash do JSON completo, que só elimina duplicatas exatas.
- Falhas e cobertura parcial produzem valores ausentes. Zero somente para consulta anual completa no recorte configurado do PNCP. Valores monetários desconhecidos não são somados como zero.
- HTTP 400 permanece permanente para uma consulta de um dia. Quando os parâmetros já são válidos e a janela tem mais de um dia, o PNCP divide somente essa janela em duas partes contíguas e repete o processo nas partes que ainda retornarem 400. A janela-pai só completa quando todas as folhas completam; manifesto e cache registram as janelas-filhas, páginas, contagens antes/depois da deduplicação e interrupções. A árvore inteira compartilha a geração de refresh, preservando compatibilidade com os marcadores anteriores.

Os 13 testes iniciais passaram antes de iniciar o Checkpoint 2. O smoke municipal original consultou Lucas do Rio Verde, 01–07/01/2024, modalidade 8: uma consulta, sem registros, sem erro. Comando naquele checkpoint: `python etl_primario.py --sources pncp --smoke-test`. Evidência: `output/smoke/20260916T125053889254Z/`.

## Checkpoint 2

- `escopo.tipo=uf` resolve catálogo oficial do IBGE e prevalece sobre `municipios`; sem escopo UF, permanece a seleção municipal. Catálogo vazio/inválido gera erro claro. Divergência da referência de 223 municípios da PB gera aviso.
- PNCP estadual usa `uf=PB` uma vez por janela/modalidade/página; não executa uma consulta para cada município. Filtragem por código IBGE e arquivo de rejeitados. Sem correspondência aproximada por nome.
- SICONFI continua municipal, com cache DCA validado, paginação completa via offset e checkpoints por página. Links ORDS internos fornecem somente o próximo offset; as requisições mantêm o endpoint público e filtros originais. DCA antiga com `hasMore=false`, município/ano válidos é reutilizada.
- ObrasGov lista projetos por UF/ano/página. Identificação conservadora por código ou executor/tomador exato; consulta catálogo territorial completo antes de aceitar identificação por nome no modo municipal. Projetos fora do recorte não contaminam agregados válidos; desconhecidos/ambíguos deixam cobertura parcial. Detalhes por projeto mantêm execução física e histórico com seus próprios checkpoints.
- A qualidade do ObrasGov separa coleta da API, atribuição territorial e agregado. Projetos federais/estaduais fora do escopo municipal não bloqueiam o ano; pendências municipais e multiterritorialidade publicam somente valor observado parcial. A saída preserva papéis territoriais, evidências, alvo/censura e temporalidade de cadastro, previsão e execução.
- SIDRA consulta lotes de até 50 municípios por padrão, preserva população/fonte/PIB e dados brutos por lote. Falha em uma série não descarta as outras. Censo 2022 tem fonte explícita. SICONFI não preenche população IBGE.
- Esqueleto com todas as combinações município/ano; para PB 2020–2024 são 1.115 linhas. Merge exclusivamente por código e ano, validado como um para um.
- Auditoria inclui variáveis ausentes do catálogo, metadados, cobertura/faltantes, cardinalidade, média/desvio, primeiros/últimos anos, recomendação, risco de vazamento e observações metodológicas. Quase constante: frequência dominante >=95% por padrão. Correlações Spearman só com >=20 pares, independentemente de configuração inferior, e alerta com |r|>=0,85.
- Sem Elastic Net, PCA ou score. Arquivos manuais continuam sendo inventariados/perfilados, sem integração/imputação automática de colunas ainda não mapeadas.

## Testes e integrações

Suíte final: **57 testes, todos aprovados**, com HTTP simulado e diretórios temporários. Cobertura: retry/Retry-After/timeout/503, erro permanente, cache válido/corrompido, escrita interrompida, Ctrl+C, refresh interrompido, deduplicação, zero versus ausente, janelas bissextas, resolução UF/legado, chave do merge, PNCP UF/filtro/rejeitados, período independente, cache/paginação SICONFI, identificação e ambiguidade ObrasGov, lote SIDRA, auditoria/correlação e limites/isolamento da CLI. Os testes PNCP adicionais cobrem subdivisão recursiva do HTTP 400, folha diária definitiva, composição de estados, totais declarados, contagem bruta/deduplicada, retomada das filhas, geração compartilhada e compatibilidade com marcadores de refresh anteriores.

Retomada PNCP estadual executada em 22/09/2026, sem `--refresh` e sem reconstrução conjunta das demais fontes:

| Ano | Eventos | Situação municipal final |
|---|---:|---|
| 2022 | 1.047 | 45 municípios com registros e 178 sem registros confirmados |
| 2023 | 2.810 | 81 municípios com registros e 142 sem registros confirmados |
| 2024 | 20.507 | 217 municípios com registros e 6 sem registros confirmados |

Total: **24.364 eventos**, `erros = 0`, nenhuma cobertura parcial/falha e nenhum zero derivado de cobertura incompleta. O manifesto contém 156 partições trimestrais/modalidade: 62 com páginas reutilizadas e 94 sem registros confirmados. A partição PB/2023-10-01 a 2023-12-31/modalidade 6 respondeu diretamente nesta validação e completou quatro páginas; portanto, o fallback foi comprovado pelos testes determinísticos, mas não precisou ser acionado pela API nessa retomada.

Executado com Python 3.12 ARM64/pandas 3.0.4/requests 2.34.2 e, separadamente, Python 3.12 x64/pandas 2.3.3/requests 2.34.2 com todas as dependências de `requirements.txt`. As mensagens de warning nos testes correspondem às falhas simuladas deliberadamente.

```powershell
python -m unittest discover -s tests -v
.\.validation\venv\Scripts\python.exe -m unittest discover -s tests -v
python -m py_compile etl_primario.py etl_confiabilidade.py
```

O smoke estadual limitado mais recente está em `output/smoke/20260921T120758274248Z/`. Ele reutilizou os checkpoints válidos existentes e não iniciou coleta estadual completa. Comando:

```powershell
python etl_primario.py --sources ibge siconfi pncp obrasgov --smoke-test
```

| Fonte | Recorte e resultado observado |
|---|---|
| IBGE Localidades | Catálogo PB: 223 municípios. |
| SIDRA | Lote de Água Branca (2500106) e Aguiar (2500205), 2024. População: 9.578 e 5.061. PIB 2024 retornou `[]`; valores ficaram ausentes. |
| SICONFI | Mesmos dois municípios, 2024: 1.228 e 645 linhas DCA, uma página cada. Reutilização confirmada na segunda execução. |
| PNCP PB | 02/01/2024, modalidade 8, uma página. Primeiro timeout, segunda tentativa HTTP 204: ausência de registros confirmada somente nesse dia/modalidade. Base anual permanece ausente por ser smoke. |
| ObrasGov PB | Ano 2024: duas páginas de 200 registros, de cinco páginas declaradas (808 registros totais). 270 identificados e 130 rejeitados/ambíguos nas páginas lidas. Parada controlada no limite; agregados anuais ausentes. Sem chamadas aos detalhes por obra. |

O smoke conjunto teve **uma ocorrência esperada** em `erros_coleta.csv`: limite de duas páginas do ObrasGov. Portanto, execução limitada concluída não significa cobertura estadual completa. A primeira tentativa estadual, preservada em `output/smoke/20260916T130054276345Z/`, registrou erros SIDRA de separador corrigidos por teste de regressão e timeouts PNCP de uma janela de sete dias. A janela final foi reduzida a um dia; nenhuma falha foi transformada em zero.

## Comandos de uso

`config.json` está configurado para PB. Estes comandos iniciam a coleta configurada; **não foram executados sem `--smoke-test` nesta implementação**:

```powershell
# Apenas IBGE e SICONFI
python etl_primario.py --sources ibge siconfi

# Apenas PNCP, retomada padrão
python etl_primario.py --sources pncp --resume

# Apenas ObrasGov
python etl_primario.py --sources obrasgov

# Todas as fontes automáticas
python etl_primario.py --sources ibge siconfi pncp obrasgov

# Recorte legado (Lucas do Rio Verde)
python etl_primario.py --config config.municipio.json --sources ibge siconfi

# Smoke municipal PNCP na versão final
python etl_primario.py --config config.municipio.json --sources pncp --smoke-test

# Atualizar somente a fonte escolhida
python etl_primario.py --sources pncp --refresh
```

Retomada após Ctrl+C: repita com `--resume`. Não repita `--refresh` se pretende aproveitar as páginas da atualização interrompida. `--only-profile` mantém o comportamento de perfilar arquivos manuais, não reconstrói dados das APIs a partir dos brutos. Em UF, exige catálogo territorial já salvo e não faz consultas de rede.

## Quantidade de chamadas e duração

Estimativas para uma UF com 223 municípios, 2020–2024, PNCP 2022–2024, 13 modalidades, janelas trimestrais, sem cache e sem retries:

| Fonte | Chamadas estimadas |
|---|---|
| IBGE | 1 catálogo + 5 lotes × 3 séries (estimativas, Censo 2022, PIB) = **16**. |
| SICONFI | **1.115** consultas iniciais município/ano; somar páginas adicionais quando `hasMore=true`. |
| PNCP | **156 consultas iniciais** (1 UF × 3 anos × 4 janelas × 13 modalidades), mais as páginas seguintes. O desenho municipal faria 34.788 consultas iniciais para essas mesmas janelas. |
| ObrasGov | Soma das páginas de listagem dos cinco anos + páginas de execução física/histórico dos projetos identificados. Em 2024 a API declarou cinco páginas de listagem. Para W projetos identificados, estimar inicialmente cerca de **2W** chamadas de detalhes, sujeitas à paginação. |

O cache reduz a zero as chamadas das unidades válidas; a conferência/geração de saídas ainda usa CPU e disco. Cada chamada HTTP pode chegar ao número configurado de tentativas, sem multiplicação escondida pelo adaptador.

Ordem de grandeza, não medição de coleta completa: IBGE de segundos a poucos minutos; SICONFI cerca de 25–100 minutos se cada consulta levar 1–5 s mais 0,3 s de intervalo. PNCP leva ao menos cerca de `1,5 × páginas` segundos só de pausas, além da latência; 1.000 páginas com 1–5 s de latência equivalem a aproximadamente 42–108 minutos sem retries. ObrasGov depende principalmente de W e dos detalhes. Reserve **algumas horas (aproximadamente 2–8 h em condições favoráveis)** para uma primeira coleta de todas as fontes; pode passar de um dia sob timeouts/429/503 ou muitos projetos. Os smoke tests não permitem estimativa precisa de W ou do total de páginas PNCP.

## Limitações preservadas e explícitas

- Cache é um retrato; atualização posterior no portal exige `--refresh`. Mudança de totais durante paginação produz cobertura parcial, não tentativa silenciosa de reconciliar versões.
- Não há lock entre processos. Use uma instância por diretório; o PNCP permanece estritamente sequencial dentro dela.
- Arquivos PNCP anuais antigos não comprovam completude. São preservados, mas a retomada confiável usa os novos checkpoints validados por página.
- PNCP sem publicação histórica e dados rejeitados não provam inexistência de contratação. Números ausentes não são imputados. Os termos de similaridade seguem `palavras_objeto`.
- Um registro sem município identificável pode afetar a completude de qualquer município do escopo; por isso os agregados daquele escopo/ano são conservadoramente ausentes até revisão. A contagem bruta permanece no manifesto e os eventos válidos continuam disponíveis.
- Situação e execução de obras são retratos atuais agrupados pelo ano de cadastro, não snapshots históricos daquele ano: potencial vazamento temporal explícito na auditoria. Detalhes com falha não geram zero.
- SIDRA pode não oferecer determinados anos/tabelas; PIB 2024 e estimativa populacional 2023 estavam ausentes nas pequenas consultas realizadas. Não foram substituídos por outra fonte.
- `obrasgov_max_paginas_por_uf_ano=100` continua sendo um limite de proteção; se atingido, a coleta fica parcial. Aumente conscientemente se necessário.
- Rejeitados são JSON com o registro original e o motivo. A auditoria de fontes é baseada em valores presentes; o manifesto é a evidência do que foi efetivamente consultado, inclusive quando não houve registros.
- `requirements.txt` exige pandas 2.x. Neste Windows ARM64 não havia wheel compatível para esse intervalo; a validação fiel foi feita com o Python x64 instalado, sem modificar dependências globais nem ampliar o requisito.

## Referências verificadas

Rotas de localidades: [IBGE Localidades](https://servicodados.ibge.gov.br/api/docs/localidades). Consulta PNCP e filtros: [manuais oficiais PNCP](https://www.gov.br/pncp/pt-br/pncp/manuais). Paginação fiscal: [SICONFI API](https://apidatalake.tesouro.gov.br/docs/siconfi/). Projetos/detalhes: [ObrasGov API](https://api-publica.obrasgov.gestao.gov.br/obras/docs). Os smoke tests usaram diretamente os endpoints oficiais do projeto.

## Configuração final recomendada

O conteúdo abaixo corresponde ao `config.json`. `municipios` permanece como recorte de compatibilidade; com `escopo.tipo=uf`, prevalece PB. Para usar Lucas, adote `config.municipio.json` ou remova `escopo`.

```json
{
  "escopo": {"tipo": "uf", "ufs": ["PB"]},
  "municipios": [
    {
      "codigo_ibge": "5105259",
      "nome": "Lucas do Rio Verde",
      "uf": "MT"
    }
  ],
  "ano_inicial": 2020,
  "ano_final": 2024,
  "fontes": ["ibge", "siconfi", "pncp", "obrasgov"],
  "palavras_objeto": [
    "reurb",
    "regularizacao fundiaria",
    "regularização fundiária",
    "plano diretor",
    "saneamento",
    "drenagem",
    "meio ambiente",
    "ambiental"
  ],
  "pncp_modalidades": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13],
  "pncp_tamanho_pagina": 50,
  "pncp_intervalo_requisicoes_segundos": 1.5,
  "pncp_backoff_base_segundos": 3,
  "pncp_max_tentativas": 6,
  "pncp_timeout_segundos": 60,
  "pncp_janela_meses": 3,
  "pncp_ano_inicial": 2022,
  "ibge_tamanho_lote": 50,
  "siconfi_intervalo_requisicoes_segundos": 0.3,
  "obrasgov_tamanho_pagina": 200,
  "obrasgov_max_paginas_por_uf_ano": 100,
  "timeout_segundos": 60,
  "max_tentativas": 4,
  "limiar_cobertura_manter": 0.70,
  "limiar_cobertura_revisar": 0.50,
  "limiar_correlacao": 0.85,
  "min_observacoes_correlacao": 20
}
```
