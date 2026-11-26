# Execução reproduzível da Entrega 6

A rotina coletiva E06 reconstrói a matriz do Transferegov para a Paraíba, busca hiperparâmetros por validação cruzada temporal e avalia os modelos na coorte de 2022–2023. Os experimentos A0 a C1 e seus resultados publicados continuam sendo a referência da rodada anterior.

## Execução

Use Python 3.12 x64. A origem Bronze requer o índice de cargas em data/ref e os recortes oficiais gzip do Transferegov em data/bronze. Para repetir a rodada do relatório, use a carga de 17/07/2026 e os SHA-256 de auditoria_base.json. O comando só lê o Bronze local.

~~~powershell
python -m pip install -r requirements-e06.txt
python -m src.e06.entrega --saida output/e06_entrega
python -m unittest discover -s tests -p "test_e06*.py"
~~~

Um clone sem o Bronze consegue repetir o protocolo de modelagem sobre a matriz versionada. Esse caminho produz uma análise distinta, com os históricos do pacote e sem reavaliar os censurados de 2024.

~~~powershell
python -m src.e06.entrega --origem pacote --saida output/e06_pacote
~~~

Para usar valores acordados, informe juntos B, C e k por mês pelos argumentos --beneficio, --custo e --capacidade. Use a mesma unidade de utilidade para B e C. Sem os três argumentos, a rotina usa um cenário de sensibilidade com B=C=1 e dimensiona k a partir da média mensal de instrumentos na validação. Cada execução recebe um diretório novo e publica seus artefatos somente depois de concluir as etapas.

## Dados e protocolo

- O ETL verifica os hashes do Bronze e reutiliza a normalização Silver. A matriz inclui instrumentos municipais assinados de 2008 a 2024. O corte supervisionado é 31/12/2024 e o horizonte é de 365 dias, inclusive.
- Os históricos usam maturidades e desembolsos positivos estritamente anteriores ao dia da assinatura. O saldo do dia da assinatura não entra. As diferenças em relação ao histórico do pacote congelado são medidas coluna a coluna. Os dois resultados têm trilhas independentes.
- A escolha usa Brier médio nas janelas 2016–2019. A janela de um ano ajusta apenas instrumentos com horizonte encerrado antes de 1º de janeiro daquele ano. Os cinco pipelines são ajustados sobre o treino 2008–2019 com as escolhas já gravadas.
- A validação de 2020–2021 descreve mudança de período e fornece o volume de referência da fila. Nenhum resultado dessa janela entra na escolha de hiperparâmetros. O teste de 2022–2023 é a mesma coorte já utilizada nos experimentos anteriores. A verificação de 2024 usa o Bronze, com rótulos maturados na data da carga.
- O porte municipal usa a população do Censo 2022, disponível no snapshot versionado, somente para auditar desempenho e acesso à fila. As diferenças entre ano, modalidade, porte e experiência são descritivas.

## Artefatos para conferência

A pasta [dados/modelagem/e06_entrega](../../dados/modelagem/e06_entrega) contém os quadros da rodada do relatório, as premissas e a auditoria. O manifesto lista também os arquivos gerados sob output, incluindo os modelos, as matrizes e as previsões individuais.

| Arquivo | Finalidade |
|---|---|
| auditoria_base.json e manifesto.json | Carga, hashes, ambiente, sementes, partições e divergências do pacote congelado |
| grades_cv.csv, janelas_cv.csv e escolhas.json | Busca temporal e parâmetros gravados antes da avaliação |
| comparacao.csv, previsoes.parquet e modelos/ | Métricas, ICs por município, tempos medidos, previsões e estimadores ajustados |
| calibracao.csv e erros.csv | Frequências por faixa, ano e outros grupos |
| premissas.json, operacao.csv e operacao_mensal.csv | Piso econômico, teto, volumes, cortes efetivos e utilidade normalizada |
| equidade.csv e casos.csv | Cobertura por grupo e exemplos de erros no cenário de referência |

Os tempos de busca, ajuste e inferência são indicativos da máquina usada. Contagens operacionais fracionárias são expectativas de desempate uniforme no último escore. A análise usa os escores como aproximação de probabilidades. A calibração observada e a confirmação de custos, benefícios e capacidade condicionam qualquer uso operacional.

