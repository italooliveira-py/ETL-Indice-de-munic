# Histórico da publicação

## Não publicado

- Carga somente no Bronze (`--bronze-only`) para fontes ainda sem transformação.
- Transferegov Discricionárias: recorte PB de proposta, convênio, desembolso e emenda no Bronze, com hash do arquivo nacional no índice (ADR 0002); uma geração por `data_carga`.
- Transferegov no Silver: instrumentos assinados de administrações municipais, desembolsos, mapa CNPJ → IBGE pelas propostas oficiais, planos, empenhos e pagamentos das Transferências Especiais.
- Transferegov no Gold: painel município × ano por data do evento (instrumentos assinados e vigentes, repasse assinado, valor desembolsado, planos e valores planejado e pago das Especiais); zero no recorte completo é `sem_registro_confirmado`.
- RGF, Anexo 1, no Silver (`siconfi_rgf_pessoal`) e no Gold: razão despesa com pessoal ÷ RCL ajustada declarada e harmonizada para a regra de 2020–2023, mais o efeito das deduções novas de 2024 (ADR 0003).
- Chave de grão de tabelas adicionais declarada em `attrs['chave']`; zero confirmado só para fontes com cobertura completa declarada.
- Uso temporal por variável na auditoria (`status_temporal`, `motivo_temporal`) e lista `variaveis_aptas_treino_temporal` no manifesto; o Gold como um todo segue não apto por causa das variáveis legadas.
- Transferegov: instrumentos anulados contam como vigentes (anulação é desfecho); valor global na assinatura no lugar do repasse atual para uso preditivo; desfechos `resultado_*` no Silver como candidatos a alvo.
- Brief de negócio do Transferegov em `docs/BRIEF_TRANSFEREGOV.md`.
- Transferegov Transferências Especiais: plano de ação, empenho, documento hábil e ordem de pagamento, com filtro `eq.PB` aplicado pela API e retomada por página.
- SICONFI: extrato de entregas, DCA e RGF do último período do Executivo (Q3 ou Simplificado S2, conforme o extrato), por município e exercício; falhas registradas e repetidas na retomada, nunca tratadas como ausência.
- MUNIC: base xlsx de cada edição desde 2019, descoberta pelas listagens do FTP; revisões do IBGE entram sem apagar a versão anterior.
- Mapeamento de disponibilidade, cobertura e mudanças das fontes em `docs/MAPEAMENTO_FONTES.md`.

## 0.2.0 — 2026-10-24

- Reorganização incremental em `src/etl_municipal`, com compatibilidade dos comandos anteriores.
- Publicação Medallion a partir de snapshots verificados; Bronze imutável, manifestos SHA-256, Parquet e geração Gold versionada.
- Fonte territorial oficial do Censo 2022, com validação de catálogo, área e densidade para 223 municípios.
- ObrasGov preservado em eventos Silver e excluído do Gold municipal.
- Painéis exploratório 2020–2024 e MVP 2020–2023 separados; PIB 2024 nulo com flag.
- Auditoria por variável e ano e observações com status individual; treino temporal permanece bloqueado por disponibilidade pública pendente.
- O índice completo e as demais fontes do MVP continuam pendentes conforme `docs/PLANO_MVP.md`.
