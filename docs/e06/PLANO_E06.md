# E06 — Plano de execução

Escrito antes de qualquer treino, num repositório local de trabalho cujo histórico não foi migrado; as datas de cada escolha e de cada abertura do teste estão em `dados/modelagem/e06/`. Os desvios estão em `docs/e06/RESULTADOS_E06.md`, seção 6.

Pacote `pacote_final_modelagem_e06`, versão `4h1a7c9e3b5d0f2e6a8c` (PR #11). Os Parquets não são alterados; toda transformação acontece dentro do pipeline, ajustada só no treino.

## 1. Alvo e dados

- Alvo: `y_1_sem_desembolso_365 = 1` quando não houve 1º desembolso positivo em até 365 dias após a assinatura. Previsão feita na data da assinatura, para priorizar o acompanhamento. O alvo não mede irregularidade.
- Partições:

  | Partição | Anos | n | Y=1 |
  |---|---|---|---|
  | Treino | 2008–2019 | 3.711 | 76,5% |
  | Validação | 2020–2021 | 1.023 | 93,4% |
  | Teste | 2022–2023 | 625 | 83,2% |

- Conjuntos: M1 (`ano_origem`, `modalidade` e quatro contagens do histórico do município) e M1+ (M1 + `valor_global_assinatura`). Identificadores e datas não entram como preditores.
- Censurados: os 242 instrumentos de 2024 ficam fora da escolha dos modelos e só entram na seção 7.

## 2. Protocolo

**Pré-processamento.** `modalidade` em one-hot (`handle_unknown='ignore'`); contagens e valores em `log1p`; padronização só para logística, SVC e MLP; `ano_origem` numérico, como no pacote.

**Modelos e grades** (em M1 e M1+):

| Modelo | Grade |
|---|---|
| Trivial (prevalência do treino) | — |
| Taxa por modalidade no treino | — |
| Logística | penalidade L2, L1 ou elastic net 0,5 × C ∈ {0,01; 0,1; 1; 10} |
| Árvore | profundidade {2, 3, 4, 6} × mínimo por folha {20, 50, 100} |
| Random Forest | 500 árvores × profundidade {4, 8, livre} × mínimo por folha {10, 30} |
| Gradient Boosting (HistGB) | taxa {0,03; 0,1} × profundidade {2, 3}, 300 iterações com parada antecipada |
| SVC (RBF) | C {0,3; 1; 3}, probabilidade por Platt |
| MLP | camada oculta (8) ou (16) × alpha {1; 10}, lbfgs, média de 3 sementes |

**Escolha.** Hiperparâmetros pelo Brier na validação 2020–2021. Para conferir a robustez, a escolha é repetida em janelas no tempo dentro do treino (valida 2016 a 2019). Na janela que valida o ano V, o treino só tem instrumentos com assinatura + 365 dias antes de 01/01/V, a mesma regra da `folds_temporais` da E05.

**Teste.** O modelo escolhido é reajustado no treino e avaliado no teste. A versão reajustada em treino + validação entra como sensibilidade. O teste só é aberto depois de as escolhas estarem commitadas, uma vez por experimento.

**Métricas.**
- Principal: Brier skill contra a prevalência do treino (decisão 0001).
- Também: Brier, log loss, ROC-AUC e PR-AUC das duas classes.
- Intervalo de 95% por bootstrap de municípios (1.000 reamostragens).
- Matriz de confusão em três limiares (decisão 0002): F1 máximo na validação, prevalência do treino e capacidade de 10%, 20% e 30%.
- Calibração por decil e por ano.

**Erros por grupo** (teste): ano, modalidade, porte do município e experiência do município. O porte vem do IBGE e só é usado na leitura dos erros.

## 3. Experimentos avulsos

Rodam com os dois melhores modelos da validação em M1+, mais a logística e os dois baselines.

| Experimento | Mudança em relação ao A0 | Decisão |
|---|---|---|
| A0 | oficial | — |
| A1 | escolha em janelas no tempo (valida 2018 e 2019), sem usar 2020–2021 | 0003 |
| A2 | treino só com 2015–2019, escolha em janelas | 0003 |
| B1 | contagens do histórico trocadas por taxa de atraso suavizada, marca de município sem histórico e valor médio por desembolso | 0004 |
| B2 | contagens e as três variáveis do B1 | 0004 |
| C1 | M1+ sem `ano_origem` | 0005 |

## 4. Registro

- `registro.csv`: uma linha por experimento × conjunto × modelo × partição, com proveniência (commit, hash do pacote, versões). Só recebe linhas novas.
- `aberturas_teste.csv`: cada uso do teste.
- `previsoes.parquet`: probabilidade por instrumento, para recalcular métricas sem treinar de novo.
- `grades.csv`, `erros.csv`, `calibracao.csv`, `robustez.csv`, `replicacao.csv` e `proveniencia.json`: um arquivo por tipo, com o `run_id` de cada rodada.
- `escolhas/<experimento>.json`: hiperparâmetros e limiares, commitados antes do teste.
- As rodadas gravam em `output/e06/` (fora do git); a versão final fica em `dados/modelagem/e06/`, com `manifesto.json` de hashes.
- `docs/e06/decisoes/`: decisões no formato dos ADRs do repo. `CHECKPOINT_E06.md`: estado e próximo passo.

## 5. Replicação

1. `verify_package.py` antes de cada rodada; um hash divergente interrompe a rodada.
2. Sementes fixas no `config.e06.json`.
3. Ambiente virtual criado a partir do `requirements-e05-lock.txt` da equipe. Com versões fora do lock, a rodada é interrompida, salvo `--fora-do-lock`; nesse caso ela é marcada e gravada à parte.
4. Rodar o A0 duas vezes e comparar as previsões, com tolerância de 1e-9.
5. Testes `unittest`: partições iguais às do pacote, pipeline sem identificadores, transformações ajustadas só no treino, variáveis do B1 sem o alvo, janelas sem desfecho futuro.
6. Texto gerado sempre com LF.

## 6. Ordem

1. Ambiente, pacote e testes.
2. Escolha do A0.
3. Commit das escolhas.
4. Teste do A0 e erros.
5. Experimentos A1 a C1, cada um com escolha, commit e teste.
6. Replicação do A0.
7. `RESULTADOS_E06.md` e revisão do Jorge antes de qualquer migração para o repo.

## 7. Censurados de 2024 (opcional)

Aplicar os modelos escolhidos aos 242 instrumentos de 2024 quando o desfecho deles for conhecido, sem usá-los em nenhuma escolha.
