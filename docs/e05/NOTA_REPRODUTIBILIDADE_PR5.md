# Nota de reprodutibilidade do PR #5

O PR #5 (`74f944f`, incorporado por `52a7e8a`) versionou o código e os quatro snapshots históricos da revisão E05, mas não versionou `config.e05.revisao.json` nem `dados/modelagem/e05_revisao/manifesto.json`, embora ambos sejam exigidos por `src/e05/revisao.py`.

Foram feitas buscas nos worktrees, arquivos ocultos/ignorados, histórico Git, branches remotas, notebook e documentação disponíveis. Os dois artefatos não foram recuperados. Portanto, a reprodução histórica exata do PR #5 permanece bloqueada.

Nenhuma configuração ou manifesto aproximado foi inventado. Os snapshots históricos permanecem preservados com hashes inalterados:

- `principal.parquet`: `E83225B87A6096B6558C256515E493983277E2E495078C22FC43FCBFCABFACA4`
- `principal_particoes.csv`: `697C10ABE0DA68028AE86D054019F05258E5E8C12B4DBEE3C63EC16F54E16F13`
- `secundario.parquet`: `97DBD4769CC11ABB7D4ED02BE695EA04234E1D51F547765CFC640D7D805EB1FE`
- `secundario_particoes.csv`: `E473E6D20A902EE40C59849BFD745CBEA1EA760C5FC2792881B5984F9EB715A8`

Essa limitação é histórica e específica do PR #5. Ela não representa falha do Gold congelado nem do novo contrato Transferegov de 365 dias, que possui configuração própria e snapshot derivado separado.
