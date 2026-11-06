# Sensibilidade da maturidade

São mantidos, sem seleção automática, quatro métodos: taxa bruta; taxa com denominador mínimo 5; Beta-Binomial Beta(1,1); shrinkage para média estadual com `k=5`.

Os métodos diagnósticos devem publicar numerador, denominador, estimativa, posição, diferença para a taxa bruta, faixa de denominador, cobertura e Spearman anual. Beta(1,1) e `k=5` não são parâmetros aprovados de índice e nenhuma escolha será feita por associação futura.

A saída corrigida publica esses campos por município-ano, além de municípios incluídos/excluídos e quantidade/percentual de posições alteradas. Os parâmetros são lidos do JSON; não há constantes silenciosas no módulo.

Resultados observados na versão `95534890b62018db9922`:

| ano | bruta | mínimo configurado | Beta-Binomial | shrinkage | Spearman Beta | Spearman shrinkage | mudanças Beta | mudanças shrinkage |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2020 | 223 | 217 | 223 | 223 | 0,980457 | 0,994515 | 207 | 198 |
| 2021 | 223 | 220 | 223 | 223 | 0,985779 | 0,996851 | 200 | 188 |
| 2022 | 223 | 223 | 223 | 223 | 0,980452 | 0,997214 | 207 | 192 |
| 2023 | 223 | 223 | 223 | 223 | 0,980532 | 0,997283 | 207 | 177 |
| 2024 | 223 | 223 | 223 | 223 | 0,984940 | 0,997953 | 198 | 174 |

As contagens são específicas de cada método. O mínimo configurado é 5; Beta(1,1) e `k=5` permanecem cenários diagnósticos, sem seleção automática.
