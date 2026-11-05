# Design — MUNIC no Silver/Gold

## Intenção

Completar a integração da MUNIC do IBGE do Bronze existente para tabelas Silver e Gold auditáveis, preservando o contrato Medallion atual e oferecendo variáveis institucionais separadas para análises descritivas e para o painel município × ano. A MUNIC mede respostas declaradas pelas prefeituras sobre estrutura, pessoal e capacidade administrativa; ela é fundamento analítico de contexto institucional, não evidência de causalidade nem um índice de risco.

## Escopo

- Edições MUNIC 2019, 2020, 2021, 2023 e 2024.
- Bronze imutável, com arquivos originais, revisões separadas, URL, datas, tamanho e SHA-256.
- Silver principal no grão `codigo_ibge + ano_edicao_munic`.
- Silver detalhado no grão `codigo_ibge + ano_edicao_munic + variavel`.
- Gold por edição no grão `codigo_ibge + ano_edicao_munic`.
- Gold point-in-time no grão `codigo_ibge + ano_fotografia`, integrado por merge `one_to_one` ao painel existente.
- Universo restrito aos 223 municípios da Paraíba e painel 2020–2024 com 1.115 chaves.
- CSV UTF-8 e Parquet, além de dicionário e relatório de qualidade.

## Fora do escopo

Não serão implementados bioma, tipologia rural-urbana, MapBiomas, ANA, SINISA/SNIS, indicadores ambientais, score composto, pesos, ranking, probabilidade de falha, imputação automática ou interpretação causal. Área, população e densidade continuarão controles territoriais, sem interpretação ambiental.

## Abordagens consideradas

1. Reescrever o orquestrador e a publicação: rejeitada pelo risco de alterar materialmente fontes já publicadas.
2. Camada MUNIC isolada com extensão aditiva de publicação/orquestração: escolhida porque preserva os contratos existentes, permite testes por fonte e limita o merge ao contrato `one_to_one`.
3. Publicar somente tabelas MUNIC independentes: rejeitada porque não entrega o painel consolidado nem a validação point-in-time.

## Componentes propostos

- `src/etl_municipal/fontes/munic.py`: manter coleta Bronze; completar metadados, retomada, offline e validação de hashes sem alterar outros Bronzes.
- `src/etl_municipal/fontes/munic_transformacao.py`: leitura XLSX/ODS, seleção por mapa versionado, aliases e harmonização; sem inferência por posição de coluna.
- `src/etl_municipal/fontes/munic_catalogo.py` ou catálogo JSON versionado: definição de variáveis por edição, bloco, código original, unidade, tipo, comparabilidade e recomendação.
- `src/etl_municipal/publicacao.py`: aceitar o adicional MUNIC de forma aditiva; preservar todas as colunas existentes e validar merge `one_to_one`.
- `src/etl_municipal/__main__.py`: permitir Bronze MUNIC offline/resume e publicação isolada/consolidada somente depois dos contratos MUNIC.
- `data/` gerado: não versionar Bronze/Gold gerados, salvo regra já existente do repositório.
- `docs/`: contrato, dicionário, qualidade, guia de reprodução e atualizações de arquitetura, fontes, plano e changelog.

## Contratos de dados

### Bronze

Cada arquivo e revisão terá identidade própria no manifesto. `--resume` reutiliza apenas arquivo e hash válidos; `--offline` não acessa rede; `--refresh` não será usado nas demais fontes. A edição 2022 ficará explicitamente ausente, não será criada como linha institucional vazia.

### Silver

O Silver terá uma camada versionada e uma camada analítica adotada. `silver/munic_observacoes_versao` terá a chave `codigo_ibge + ano_edicao_munic + versao_base + variavel`; `silver/munic_municipio_edicao_versao` terá `codigo_ibge + ano_edicao_munic + versao_base`. `versao_base` distinguirá `original` e revisões datadas, preservando sempre as duas versões.

`silver/munic_municipio_edicao` terá a chave `codigo_ibge + ano_edicao_munic` e somente a versão elegível para o corte analisado, com `versao_adotada`, `data_publicacao_original`, `data_publicacao_versao`, `motivo_selecao_versao` e `sha256_origem`.

`silver/munic_observacoes` conterá, no mínimo, `codigo_ibge`, `municipio`, `uf`, `ano_edicao_munic`, `variavel`, `valor_original`, `valor_normalizado`, `tipo`, `unidade`, `status_observacao`, `codigo_original`, `bloco_origem`, `arquivo_origem`, `data_publicacao`, `data_disponibilidade`, `comparabilidade` e `regra_harmonizacao`.

Estados não serão colapsados: `observado`, `nao_informado`, `nao_se_aplica`, `ausente_na_edicao`, `edicao_indisponivel`, `resposta_invalida` e `fora_periodo`. Célula vazia, sentinela e pergunta ausente nunca viram zero.

### Variáveis aprovadas

Prioridade inicial: recursos humanos recorrentes — pessoal ativo, estatutários, celetistas, somente comissionados, estagiários, pessoal sem vínculo permanente e categorias efetivamente publicadas. Indicadores derivados só serão publicados com denominador válido: pessoal por mil habitantes e proporções com intervalo documentado; divisão por zero resulta em nulo.

Variáveis de planejamento, governança, cadastro e informatização só entram quando a definição oficial e o código forem comprovados, e a variável for classificada como recorrente ou episódica/comparável. Todas as variáveis catalogadas permanecem na auditoria: cobertura >=70% é candidata ao Gold largo; 50–70% fica sob revisão; <50% fica somente na auditoria; definição não comparável fica somente na auditoria independentemente da cobertura.

O catálogo registra a decisão de uso; nenhuma variável é apagada silenciosamente.

### Gold temporal

O corte é 31 de dezembro de cada ano. A seleção considera edição e versão, usando a publicação da versão adotada, nunca apenas o ano da edição. A regra inicial é:

| Fotografia | Edição elegível |
|---|---|
| 2020 | 2019 |
| 2021 | 2020 |
| 2022 | 2021 |
| 2023 | última edição publicada até 31/12/2023 |
| 2024 | edição 2023 publicada até 31/12/2024 |

A MUNIC 2021 original, publicada em 08/12/2022, pode entrar em 2022; sua revisão de 25/04/2024 só é elegível a partir dessa data e não altera 2022/2023. A MUNIC 2023 publicada em 31/10/2024 pode entrar em 2024. A MUNIC 2024 publicada em 31/10/2025 não entra em nenhuma fotografia 2020–2024. Cada valor point-in-time preservará `ano_edicao_origem`, `versao_origem`, `data_publicacao_original`, `data_disponibilidade_adotada`, `precisao_data_disponibilidade`, `defasagem_edicao`, `status_observacao`, `status_temporal`, `arquivo_origem`, `sha256_origem` e `regra_temporal`. Não haverá retropreenchimento com edição futura nem tratamento da ausência de 2022 como ausência institucional.

O Gold terá `gold/munic_capacidade_institucional_ano` no grão município × ano e `gold/munic_disponibilidade_variavel` no grão município × ano × variável. A rastreabilidade completa fica na tabela longa; o painel largo não repetirá metadados por indicador.

Indicadores por habitante usarão a população disponível no próprio ano da fotografia e temporalmente apta. População do Censo 2022 não será repetida em 2020/2021; ausência, futuro, zero ou denominador inválido resultam em nulo com status explícito. Proporções internas usam denominadores da própria edição MUNIC.

## Segurança e baseline

O trabalho ocorre exclusivamente no worktree `feature/munic-silver-gold-capacidade-institucional`, baseado em `5e8ed87` (`origin/main`). O checkout principal permanece intocado. Ambiente usado no baseline: CPython 3.12.10 64-bit AMD64, `win-amd64`, pandas 2.3.3, pyarrow 21.0.0, requests 2.34.2; `pip check` passou.

Baseline completo: 217 testes executados, 213 aprovados e 4 erros históricos por artefatos E05 ausentes: três dependem de `config.e05.revisao.json`/`dados/modelagem/e05_revisao/manifesto.json` e um de `data/gold/versoes/65260a170ee18cd79501`. Nenhum erro foi causado pela MUNIC e nenhum teste foi alterado ou silenciado.

O baseline de regressão permanece fixo: os testes MUNIC devem passar, nenhum dos 213 testes aprovados pode regredir e a suíte completa deve continuar exibindo exatamente os mesmos quatro erros históricos até uma atividade própria tratar os artefatos E05.

### Ressalva oficial sobre revisões

Para 2019 e 2021, o repositório oficial consultado disponibiliza apenas as revisões. O contrato passa a declarar `status_versao = revisao_unica_disponivel`, `original_disponivel = false` e `original_bytes_disponiveis = false`, sem inventar hash, tamanho, nome ou conteúdo do original. A nota oficial do IBGE delimita as correções a `MREG0151`, `MREG0152`, `MREG0153` (2019) e `MCUL42` (2021). Esses códigos permanecem no Silver/auditoria, recebem disponibilidade da revisão e ficam fora do Gold largo do MVP. RH e demais variáveis comprovadamente não listadas na errata podem usar a data original como premissa condicional documentada. A condição temporal da MUNIC é `apta_com_ressalva_documentada`, não point-in-time integralmente comprovado.

## Gate de interrupção encontrado

O smoke e a coleta completa confirmaram que o FTP oficial atualmente disponibiliza somente `Base_MUNIC_2019_20210817.xlsx` e `Base_MUNIC_2021_20240425.xlsx` para as edições 2019 e 2021. As tentativas oficiais pelos nomes originais `Base_MUNIC_2019.xlsx` e `Base_MUNIC_2021.xlsx` retornaram HTTP 404. A revisão oficial atualmente disponível será preservada com seus metadados e ressalva; não será declarada preservação histórica integral.

## Critérios de aceitação

- Bronze MUNIC validável offline, com revisões preservadas e hashes estáveis.
- Cinco edições autorizadas, sem edição 2022 artificial.
- Chaves Silver únicas por município × edição e 223 municípios PB reconciliados.
- Gold por edição e point-in-time sem vazamento temporal.
- Painel consolidado com exatamente 1.115 chaves únicas município × ano.
- Colunas preexistentes materialmente iguais na regressão sem MUNIC.
- Ausência, não aplicável, resposta negativa e pergunta ausente preservadas.
- Nenhuma variável ambiental, score, peso ou imputação automática.
- Execução offline reproduz conteúdo e hashes.
