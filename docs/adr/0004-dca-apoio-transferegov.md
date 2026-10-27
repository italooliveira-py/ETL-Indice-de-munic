# ADR 0004 — DCA e RGF no recorte de apoio ao Transferegov

Data: 2026-10-26. Estado: aceito e implementado (`siconfi.transformar_dca`, `painel_dca`; RGF conforme ADR 0003).

## Contexto

O foco do projeto é o Transferegov. A DCA e o RGF do SICONFI cobrem todo o orçamento municipal, mas integrá-los por completo ampliaria muito o escopo. A DCA, porém, ajuda a dimensionar o Transferegov: dá o denominador (receita total), mostra convênios federais que não passam pelo Transferegov, traz os convênios do Estado e permite checar como o município contabiliza as emendas Pix. O RGF, Anexo 1, define se o município pode receber transferências voluntárias (LRF, art. 23, § 3º).

## Decisões

1. **Recorte.** Da DCA, só o Anexo I-C (receitas), nas contas:
   - `ReceitasExcetoIntraOrcamentarias`, bruta e deduções (receita líquida);
   - convênios da União, convênios do Estado e transferência especial da União, corrente e capital.

   Do RGF, só o Anexo 1 (ADR 0003). Os demais anexos de ambos permanecem no Bronze.
2. **Mapa de contas versionado** (`MAPA_RECEITA`, publicado em `ref/siconfi_mapa_receita`), com as agregadoras de cada leiaute do ementário de receita:

   | Grupo | 2020–2021 | 2022 em diante |
   |---|---|---|
   | Convênios da União | `1.7.1.8.10.0.0`, `2.4.1.8.10.0.0` | `1.7.1.7.00.0.0`, `2.4.1.4.00.0.0` |
   | Convênios do Estado | `1.7.2.8.10.0.0`, `2.4.2.8.10.0.0` | `1.7.2.4.00.0.0`, `2.4.2.2.00.0.0` |
   | Transferência especial da União | — (conta inexistente) | `1.7.1.9.57.0.0`, `2.4.1.9.51.0.0` |

   Na PB, a agregadora está sempre presente quando há contas-filhas; soma-se só a agregadora. Conta de um leiaute aparecendo no ano do outro bloqueia a publicação.
3. **Silver:** `siconfi_dca_receita_apoio` (linhas originais das contas do recorte) e `siconfi_dca_receita_municipio` (município × exercício, com status e data de envio da DCA pelo extrato de entregas).
4. **Gold**, grupo `siconfi_dca`:

   | Variável | Uso temporal |
   |---|---|
   | `dca_receita_liquida_total` | apta com defasagem t+1 |
   | `dca_convenios_uniao`, `dca_convenios_estado` | apta com defasagem t+1 |
   | `dca_dependencia_convenios_uniao` (convênios da União ÷ receita líquida) | apta com defasagem t+1 |
   | `dca_convenios_uniao_fora_transferegov` (DCA − desembolsos do Transferegov; pode ser negativo por diferença de data) | apta com defasagem t+1 |
   | `dca_transferencia_especial` | só descritiva |
   | `dca_pix_divergente` (1 = recebeu Pix no Transferegov e declarou zero na conta própria) | só descritiva |

   Os dois cruzamentos só são publicados quando as duas modalidades do Transferegov estão na mesma execução.
5. **Nulos:** DCA não entregue → nulo (Damião 2022, Paulista 2024). DCA entregue sem a conta → zero declarado. Conta inexistente no leiaute do ano (transferência especial em 2020–2021) → nulo.
6. **Reconciliação:** `dca_receita_liquida_total` reproduz exatamente a `receita_total_realizada` da coleta legada (diferença de R$ 0,00 em 1.111 municípios-ano), o que valida a regra de dedução e permite aposentar o cálculo legado no futuro.

## Consequências

- A transferência especial na DCA não substitui o Transferegov: de 66 a 79 municípios por ano receberam Pix e declararam zero na conta própria. A divergência é publicada como sinal de qualidade contábil.
- Convênios da União na DCA ficam de 3% a 35% acima dos desembolsos do Transferegov: incluem convênios fora da plataforma e são registrados pela data do crédito.
- **Pendente:** os convênios do Estado têm um salto em 2022 (R$ 408 mi, contra R$ 20 mi a R$ 154 mi nos demais anos), concentrado em capital para programas de educação (`2.4.2.2.51`, R$ 241 mi, 217 municípios). O dado declarado é mantido; o programa estadual de origem não foi identificado.
