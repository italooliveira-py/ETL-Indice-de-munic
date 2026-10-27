# ADR 0003 — Despesa com pessoal do RGF: razão contínua e harmonização da mudança de 2024

Data: 2026-10-26. Estado: aceito e implementado (`siconfi.transformar_rgf`, `painel_rgf`).

## Contexto

O RGF, Anexo 1, informa a despesa total com pessoal (DTP) do Executivo municipal sobre a receita corrente líquida ajustada (RCL ajustada), com limites de alerta (48,6%), prudencial (51,3%) e máximo (54%). Na PB, o número de municípios acima do máximo caiu de 106 em 2023 para 36 em 2024, e a mediana da razão, de 53,6% para 48,0%.

A investigação no Bronze (todos os RGF do último período, 2020–2024) mostrou duas causas:

1. **Receita (≈ 3 p.p. no agregado).** A RCL ajustada da PB cresceu 18,8% em 2024, contra 12,4% da despesa bruta com pessoal. Pela DCA, o crescimento veio sobretudo do FPM (+R$ 1,2 bi), do SUS fundo a fundo (+R$ 0,87 bi), do FUNDEB (+R$ 0,59 bi) e da cota-parte do ICMS (+R$ 0,42 bi). É um efeito real, comum a todos os municípios.
2. **Regra de apuração (≈ 1,5 p.p. no agregado).** O leiaute de 2024 do Anexo 1 passou a ter contas que não existiam em 2020–2023:
   - `AgentesComunitariosDeSaudeEDeCombateAsEndemiasComRecursosVinculados` (CF, art. 198, § 11): despesa excluída da DTP — R$ 207 mi, 101 municípios;
   - `ParcelaDedutivelReferenteAoPisoSalarialDoEnfermeiro...`: despesa excluída da DTP — R$ 211 mi, 148 municípios;
   - `TransferenciasDaUniaoRelativasARemuneracaoDosAgentesComunitariosDeSaude`: repasse excluído da RCL — R$ 226 mi, 121 municípios.

O efeito da regra **não é uniforme**: zero em 60 municípios, mediana de 1,1 p.p., acima de 2 p.p. em 54 municípios e máximo de 5,3 p.p. A adoção é desigual (64 municípios não usaram nenhuma dedução nova) e há declarações inconsistentes (24 municípios excluíram o repasse dos agentes da RCL sem excluir a despesa correspondente). Sem as deduções novas, 48 municípios estariam acima do máximo em 2024, e não 36. Portanto, a mudança de regra não se anula entre municípios.

## Decisões

1. **Razão contínua, não faixa.** A classificação em faixas é instável perto do limite: em 2023, 40 municípios estavam até 3 p.p. acima de 54%. O Gold publica a razão; as faixas podem ser derivadas no consumo.
2. **Silver `siconfi_rgf_pessoal`**, grão município × exercício, um RGF do último período (Q3 ou Simplificado S2, conforme o extrato de entregas), com os componentes separados: despesa bruta, DTP, RCL legal, RCL ajustada, cada dedução nova e o repasse dos agentes excluído da RCL, além de periodicidade, status e data de envio. Conta ausente no leiaute do ano vale zero para a harmonização.
3. **Duas razões no Gold:**
   - `rgf_pessoal_rcl_declarada` = DTP ÷ RCL ajustada, como declarado; é a medida legal (limites, sanções da LRF, acesso a transferências voluntárias). Contrato: difere do percentual publicado no RGF em no máximo 0,01 p.p.
   - `rgf_pessoal_rcl_harmonizada` = (DTP + dedução dos agentes + dedução do piso da enfermagem) ÷ (RCL ajustada + repasse dos agentes excluído); é a regra de 2020–2023, comparável entre anos e entre municípios. Igual à declarada antes de 2024.
   - `rgf_deducoes_novas_pp` = harmonizada − declarada; descritiva da adoção das deduções.
4. **Harmonização para a regra antiga.** É a única direção possível: os componentes das deduções novas não existem para 2020–2023.
5. **O efeito de receita não é corrigido.** É real e comum ao ano; em modelos, trata-se com efeito de ano ou padronização dentro do ano.
6. **Disponibilidade:** `apta_defasagem_t_mais_1`. O RGF do último período é enviado em janeiro de t+1; a data está em `data_envio`. Com status `RE`, a data é a da última retificação e o valor é o retificado.
7. RGF não entregue fica nulo (`indisponivel`), nunca zero. Do SICONFI, só o Anexo 1 do RGF é transformado; DCA, demais anexos e extrato completo seguem no Bronze.

## Consequências

- A série harmonizada permite comparar 2024 com 2020–2023 e municípios entre si sem depender de como cada um preencheu as deduções novas.
- A razão declarada continua disponível para análises legais (por exemplo, impedimento de receber transferências voluntárias, LRF art. 23, § 3º, com as exceções do art. 25, § 3º).
- `OutrasDeducoesConstitucionaisOuLegais`, também nova em 2024 (2 municípios, R$ 0,6 mi), não entra na harmonização: sua natureza não foi verificada.
- **Pendente:** confirmar no Manual de Demonstrativos Fiscais de 2024 a regra de cada dedução nova, em particular que o repasse do piso da enfermagem permanece na RCL. A interpretação acima vem dos dados declarados.
