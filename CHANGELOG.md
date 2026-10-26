# Histórico da publicação

## 0.2.0 — 2026-10-24

- Reorganização incremental em `src/etl_municipal`, com compatibilidade dos comandos anteriores.
- Publicação Medallion a partir de snapshots verificados; Bronze imutável, manifestos SHA-256, Parquet e geração Gold versionada.
- Fonte territorial oficial do Censo 2022, com validação de catálogo, área e densidade para 223 municípios.
- ObrasGov preservado em eventos Silver e excluído do Gold municipal.
- Painéis exploratório 2020–2024 e MVP 2020–2023 separados; PIB 2024 nulo com flag.
- Auditoria por variável e ano e observações com status individual; treino temporal permanece bloqueado por disponibilidade pública pendente.
- O índice completo e as demais fontes do MVP continuam pendentes conforme `docs/PLANO_MVP.md`.
