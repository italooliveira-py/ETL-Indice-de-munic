# Modelo de tempo até o 1º desembolso — Transferegov (municípios da PB)

Documento de método e resultados, passo a passo. Código em `src/e05_tempo_desembolso/`, resultados em `docs/e05/tempo_desembolso/resultados/`.
Data de referência dos dados (data de carga): **17/07/2026**.

---

## 1. Resumo

- **Alvo novo:** quanto tempo, desde a assinatura, até o instrumento receber o **1º desembolso** da União.
- **Por que:** a falha contratual (anulação) deixou de ser previsível na assinatura e ficou rara. Mas **100% das falhas são instrumentos que nunca receberam nada**, então o 1º desembolso é o marco que separa um projeto que andou de um que pode morrer.
- **Modelo escolhido:** uma **curva média de recebimento ajustada pelo porte do município e pela fonte do recurso**. Tecnicamente, é uma regressão logística de risco por trimestre com três variáveis: o tempo desde a assinatura, a faixa de população e o ministério concedente.
- **Por que tão simples:** um modelo com cada município e o tipo de instrumento teve o **mesmo desempenho**. Pela navalha de Occam, ficou a versão com menos parâmetros e mais fácil de explicar.
- **Desempenho:** praticamente igual ao de uma média simples. O erro do prazo é de cerca de 7 meses, e a ordenação entre instrumentos é fraca (C-index de 0,56; 0,5 é o acaso). O que o modelo entrega é uma **régua de prazos com faixa de incerteza**, não uma previsão individual.
- **Para o gestor:** prazo de referência por porte e fonte, chance de cada pendente receber nos próximos 6 ou 12 meses e alerta de espera longa.

---

## 2. O alvo novo

**Definição.** Para cada instrumento (convênio, contrato de repasse ou termo de compromisso de município da PB):

| Elemento | Definição |
|---|---|
| Início | data de assinatura |
| Evento | data do **primeiro desembolso com valor > 0** |
| Tempo | dias entre a assinatura e o evento, agrupados em **trimestres** (91 dias) |
| Censura | quem ainda não recebeu é observado até o fim da vigência atual ou até a data de carga (o que vier antes) |
| Horizonte | até 20 trimestres (5 anos) |

**Formato para a regressão.** Cada instrumento vira uma linha por trimestre em que ainda aguardava o 1º desembolso. A variável resposta de cada linha é:

> **y = 1** se o 1º desembolso ocorreu naquele trimestre; **y = 0** se o instrumento continuou aguardando.

A logística estima a chance de receber em cada trimestre, dado que ainda não recebeu. Encadeando os trimestres, sai a **curva S(t)**, a chance de ainda não ter recebido até o trimestre t. Dela vêm:
- P(receber até 12, 18 e 24 meses) = 1 − S(4), 1 − S(6), 1 − S(8);
- mediana do prazo: o primeiro trimestre em que 1 − S(t) ≥ 50%;
- faixa provável: do trimestre em que 1 − S(t) passa de 25% ao trimestre em que passa de 75%;
- condicional ao tempo já decorrido: P(receber nos próximos 6 meses | ainda não recebeu até hoje) = 1 − S(hoje + 2) / S(hoje).

**Relação com o piloto `src/e05_transferegov_atraso.py`.** O alvo binário de lá (`risco_atraso_primeiro_desembolso_365d`: sem 1º desembolso em até 365 dias) corresponde a 1 − P(receber até 12 meses) desta curva. Há duas diferenças de construção:
- lá, desembolsos com data anterior à assinatura são descartados; aqui, contam como dia 0;
- lá, instrumentos sem 365 dias de observação saem da base; aqui, entram como censurados.

**Por que um modelo de sobrevivência e não uma regressão do prazo.** 621 instrumentos da PB ainda aguardam o 1º desembolso. Uma regressão comum do prazo teria de descartá-los, e eles são justamente os mais lentos. O modelo por trimestre usa a informação de que "até agora não recebeu" sem inventar um prazo para eles.

---

## 3. Por que trocar de alvo

O alvo foi construído em etapas, e cada etapa testada:

1. **Alvos originais:** falha contratual, não pagamento e atraso grave, previstos na assinatura.
2. **Auditoria de vazamento:**
   - a contrapartida usava o valor atual, que embute aditivos posteriores;
   - no tempo 2, parte dos desfechos já estava decidida no checkpoint.

   Corrigidos esses pontos, os ganhos caíram.
3. **Mudança de regime na falha contratual:**
   - a taxa de falha entre os instrumentos já decididos foi de 25% a 27% em 2015–2017, 6% em 2019, 2% em 2021 e 1,5% em 2023;
   - o modelo treinado em 2015–2019 **inverte a ordem** em 2023 (AUC 0,29), porque o Ministério da Integração deixou de ser sinônimo de anulação;
   - com janelas recentes, a calibração se corrige, mas a ordenação continua ruim, e há poucas falhas para avaliar.
4. **O marco que sobrou:**
   - todas as falhas são instrumentos que **nunca receberam nada**, e quem recebeu algo não falhou;
   - o risco de anulação cresce com a espera: entre os que ficaram sem receber até 1 ano, 24% falharam; até 2 anos, 47%; até 2,6 anos, cerca de 70% (safras 2015–2019).
5. **Ligação com o trabalho da equipe:** o PR #6 do Ítalo propunha o alvo "1º desembolso após 365 dias". A direção estava certa, mas 365 dias é cedo demais: 86% dos instrumentos não recebem nada no 1º ano. Aqui o prazo é tratado como **variável contínua com censura**, em vez de um corte fixo.
6. **Necessidade de quem negocia com o município:** saber **quando** o recurso tende a chegar e **quando a espera vira sinal de risco**.

---

## 4. Fontes dos dados

Camada **Silver** do pipeline `projeto nocturne` (somente leitura):

| Tabela | Grão | Campos usados |
|---|---|---|
| `data/silver/transferegov_instrumentos.parquet` | 1 linha por instrumento de município da PB (Transferegov, Discricionárias) | `nr_convenio`, `codigo_ibge`, `data_assinatura`, `data_fim_vigencia`, `situacao`, `orgao_superior`, `valor_repasse` |
| `data/silver/transferegov_desembolsos.parquet` | 1 linha por liberação de recurso da União | `nr_convenio`, `data_desembolso`, `valor_desembolsado` |
| `data/silver/ibge.parquet` | 1 linha por município × ano (IBGE) | `codigo_ibge`, `ano`, `populacao` |

**Filtros aplicados:**
- `valor_repasse > 0`;
- safras (ano da assinatura) a partir de 2019, que é o regime recente (seção 3).

---

## 5. Variáveis de entrada e como foram construídas

| Variável | Construção | Por que entra |
|---|---|---|
| **Trimestre desde a assinatura** (`trimestre_cat`, 1 a 20, categórica) | índice do trimestre na linha pessoa-período | É a curva de base: a chance de receber muda muito com o tempo (quase zero no 1º ano, pico entre 18 e 24 meses) |
| **Porte do município** (`porte`, categórica) | população mais recente no Silver do IBGE, em faixas: até 10 mil, 10–20 mil, 20–50 mil, 50–100 mil, acima de 100 mil | Municípios grandes demoram mais: mediana de 24 meses até 50 mil habitantes, 27 meses entre 50 e 100 mil, 30 meses acima de 100 mil |
| **Fonte do recurso** (`orgao_superior`, categórica) | órgão superior concedente | Diferenças médias reais: Educação e Cidades são rápidos, Saúde é lento |

**Pré-processamento** (`Pipeline` do scikit-learn, ajustado só no treino):
- `OneHotEncoder(min_frequency=15)`: fontes raras vão para uma categoria "rara".
- **Regularização L2**, com C escolhido na última safra do treino de cada corte (C = 0,1 no modelo final). C pequeno puxa os efeitos para a média quando os dados são escassos.

**Variáveis testadas e descartadas:**

| Variável | Resultado |
|---|---|
| **Município** (categoria própria para cada um) e **tipo de instrumento** | Mesmo desempenho do porte e fonte (C-index de 0,55 contra 0,56), com muito mais parâmetros. Descartadas pela navalha de Occam. Mantidas na validação como comparação |
| Atributos do instrumento (valor, contrapartida, duração, dias da proposta à assinatura, assinatura em dezembro, flags de emenda) | Pioraram o erro em 2% a 12% |
| Sazonalidade do calendário (trimestre civil) | Sem ganho |
| Mediana histórica de prazo do município | Sem ganho |
| Ritmo atual do concedente (fração dos que aguardavam e receberam no trimestre anterior) | Sem ganho (±0,2%) |

---

## 6. Validação: aplicando o modelo no teste

**Protocolo temporal:** treina em safras anteriores e prevê a safra seguinte, como no uso real.

| Corte | Treino | Teste | Observação |
|---|---|---|---|
| teste_2022 | 2019–2021 | 2022 | 83% já receberam |
| teste_2023 | 2019–2022 | 2023 | 86% já receberam |
| checagem_2024 | 2019–2023 | 2024 | 64% já receberam; desfecho em andamento |

**Métricas:**
- C-index: o modelo coloca antes quem recebe antes? 0,5 equivale ao acaso.
- Redução do Brier: erro da probabilidade de ter recebido até 12, 18 e 24 meses, comparado à **média simples** (a curva média, igual para todos).
- Erro mediano do prazo, em meses.
- % de prazos reais dentro da faixa p25–p75 prevista (o esperado para uma faixa bem calibrada é perto de 50%).

**Média dos três cortes:**

| Modelo | Variáveis (além do trimestre) | C-index | Redução do Brier 12 m | 18 m | 24 m | Erro mediano | Dentro da faixa p25–p75 |
|---|---|---|---|---|---|---|---|
| Média simples | nenhuma | 0,500 | — | — | — | 7 meses | 62% |
| Média por porte | porte | 0,526 | −0,9% | +1,3% | +1,1% | 7 meses | 62% |
| **Final: média por porte e fonte** | porte, fonte | **0,560** | −2,4% | **+2,8%** | +1,1% | 7 meses | 62% |
| Comparação | município, fonte, tipo | 0,549 | −4,8% | +2,4% | +1,3% | 7 meses | 63% |

**Por corte (modelo final):**

| Corte | C-index | Redução do Brier 12 m | 18 m | 24 m | Erro mediano | Dentro da faixa |
|---|---|---|---|---|---|---|
| 2022 | 0,568 | −5,8% | +4,2% | +5,9% | 9 meses | 49% |
| 2023 | 0,523 | +1,3% | −1,4% | +1,8% | 6 meses | 64% |
| 2024 (checagem) | 0,588 | −2,6% | +5,5% | −4,2% | 6 meses | 73% |

**Calibração.** Percentual que recebeu até o horizonte, previsto pelo modelo final contra o real (Kaplan–Meier):

| Corte | 12 meses | 18 meses | 24 meses |
|---|---|---|---|
| 2022 | 14% previsto · 11% real | 30% · 37% | 51% · 51% |
| 2023 | 14% · 20% | 30% · 39% | **50% · 71%** |
| 2024 | 17% · 12% | 32% · 40% | **52% · 72%** |

**Leitura:**
1. **O ganho sobre a média simples é pequeno**, de −2% a +3% no erro conforme o horizonte. O porte e a fonte acrescentam alguma ordenação (C-index 0,56), mas o prazo de cada instrumento continua imprevisível, com erro de cerca de 7 meses.
2. **A curva típica é bem estimada em anos normais:** em 2022, a previsão de 24 meses acertou em cheio (51% contra 51%).
3. **O nível de cada ano não é previsível.** Em 2023 e 2024, a União pagou bem mais rápido (71% a 72% em 24 meses) do que qualquer ano do treino, e o modelo subestimou. O ciclo fiscal da União pesa mais que qualquer característica do instrumento.
4. **Conclusão honesta:** o modelo é uma **régua de referência com faixa de incerteza**, não um previsor preciso de cada instrumento.

---

## 7. Aplicação

Modelo final treinado nas safras 2019–2024, com C = 0,1.

### 7.1 Régua de referência: prazo até o 1º desembolso por porte e fonte

**Mediana prevista (meses):**

| Fonte | até 10 mil | 10–20 mil | 20–50 mil | 50–100 mil | acima de 100 mil |
|---|---|---|---|---|---|
| Educação | 21 | 21 | 21 | 24 | 24 |
| Cidades | 21 | 21 | 24 | 24 | 24 |
| Agricultura | 24 | 24 | 27 | 27 | 30 |
| Integração e Desenvolvimento Regional | 24 | 24 | 27 | 27 | 30 |
| Esporte | 27 | 27 | 27 | 30 | 30 |
| Turismo | 27 | 27 | 27 | 30 | 30 |
| Desenvolvimento e Assistência Social | 27 | 27 | 27 | 30 | 30 |
| Saúde | 33 | 33 | 39 | 42 | 48 |

**Chance de receber em 24 meses:**

| Fonte | até 10 mil | 10–20 mil | 20–50 mil | 50–100 mil | acima de 100 mil |
|---|---|---|---|---|---|
| Educação | 70% | 69% | 65% | 62% | 56% |
| Cidades | 66% | 65% | 61% | 58% | 52% |
| Agricultura | 53% | 52% | 49% | 46% | 40% |
| Integração e Desenvolvimento Regional | 53% | 52% | 48% | 45% | 40% |
| Turismo | 50% | 49% | 45% | 42% | 37% |
| Esporte | 49% | 48% | 45% | 42% | 37% |
| Desenvolvimento e Assistência Social | 48% | 48% | 44% | 41% | 36% |
| Saúde | 31% | 30% | 27% | 25% | 22% |

### 7.2 Municípios selecionados (instrumento do Ministério das Cidades)

| Município | População | Porte | Instrumentos 2019–2024 | Receber em 12 meses | Receber em 24 meses | Mediana prevista | Faixa provável | Mediana real observada |
|---|---|---|---|---|---|---|---|---|
| **Pombal** | 33.796 | 20–50 mil | 20 | 17% | **61%** | **24 meses** | 18–30 meses | 23 meses |
| Cajazeiras | 66.171 | 50–100 mil | 18 | 15% | 58% | 24 meses | 18–33 meses | 19 meses |
| Sousa | 69.876 | 50–100 mil | 8 | 15% | 58% | 24 meses | 18–33 meses | 25 meses |
| Patos | 107.774 | acima de 100 mil | 19 | 13% | 52% | 24 meses | 18–33 meses | 17 meses |
| Campina Grande | 440.939 | acima de 100 mil | 29 | 13% | 52% | 24 meses | 18–33 meses | 16 meses |
| João Pessoa | 888.679 | acima de 100 mil | 48 | 13% | 52% | 24 meses | 18–33 meses | 26 meses |

O modelo não distingue municípios do mesmo porte. A "mediana real observada" mostra que a variação dentro de cada porte existe (Patos e Campina Grande com 16–17 meses, João Pessoa com 26), mas não se mostrou estável o bastante entre anos para entrar no modelo. Ela usa só os instrumentos que já receberam, de todas as fontes.

### 7.3 Instrumentos pendentes hoje: Pombal

Instrumentos vigentes, sem nenhum desembolso até 17/07/2026:

| Instrumento | Safra | Tipo | Fonte | Repasse | Idade | Receber nos próximos 6 meses | Nos próximos 12 meses |
|---|---|---|---|---|---|---|---|
| 974499 | 2025 | Termo de compromisso | Cidades | R$ 6,50 mi | 14 meses | **24%** | **54%** |
| 984582 | 2025 | Convênio | Integração | R$ 0,50 mi | 8 meses | 9% | 25% |
| 982969 | 2025 | Convênio | Agricultura | R$ 0,54 mi | 7 meses | 10% | 26% |
| 991196 | 2025 | Contrato de repasse | Turismo | R$ 0,97 mi | 7 meses | 9% | 23% |
| 989439 | 2025 | Contrato de repasse | Esporte | R$ 0,97 mi | 7 meses | 8% | 23% |
| 992977 | 2026 | Convênio | Integração | R$ 0,38 mi | 3 meses | 3% | 12% |

**Leitura para Pombal:**
- Nenhum pendente está em espera anormal. Todos têm menos de 15 meses, ainda dentro do período normal da cláusula suspensiva.
- O termo de compromisso das Cidades (R$ 6,5 mi) está entrando na janela de maior liberação: cerca de 1 em 2 de receber nos próximos 12 meses. Termos de compromisso tendem a ser mais rápidos que a média (21 meses de mediana), então a estimativa pode ser conservadora.
- Os convênios da Integração e da Agricultura são jovens. O ponto de atenção é se continuarem sem desembolso depois de 18 a 24 meses.

### 7.4 Contraste: esperas longas (outros municípios)

| Município | Instrumento | Safra | Fonte | Repasse | Sem receber há | Receber nos próximos 12 meses | Falha final histórica nessa espera* |
|---|---|---|---|---|---|---|---|
| Campina Grande | 928152 | 2022 | Agricultura | R$ 4,58 mi | 50 meses | 31% | 88% |
| Campina Grande | 923516 | 2022 | Cidades | R$ 2,10 mi | 43 meses | 49% | 84% |
| Campina Grande | 953709 | 2023 | Integração (convênio) | R$ 7,32 mi | 31 meses | 36% | 66% |
| João Pessoa | 886299 | 2019 | Cidades | R$ 19,30 mi | 79 meses | 41% | 88% |
| João Pessoa | 922080 | 2021 | Saúde | R$ 0,30 mi | 55 meses | 16% | 88% |

\* Fração dos instrumentos de 2015–2019 que ficaram sem receber pelo mesmo tempo e acabaram anulados. Use como **sinal relativo de alerta**, não como probabilidade atual: a anulação caiu muito no regime recente, então o número tende a superestimar o risco.

---

## 8. O que o modelo informa ao gestor

**O que ele informa:**
1. **Prazo de referência na negociação.** Para Pombal (20 a 50 mil habitantes), um instrumento do Ministério das Cidades tem mediana prevista de 24 meses até o 1º recurso, com faixa provável de 18 a 30 meses, e cerca de 60% de chance de receber em 2 anos. A mesma operação na Saúde tem mediana de 39 meses e só 27% em 2 anos.
2. **A fonte do recurso é a decisão que mais muda o prazo.** Entre Educação e Cidades (21 a 24 meses) e Saúde (33 a 48 meses), a diferença é de 1 a 2 anos.
3. **Municípios maiores esperam mais**, em torno de 6 meses a mais acima de 100 mil habitantes.
4. **O 1º ano é praticamente sem caixa.** Em 12 meses, só de 13% a 17% recebem. O fluxo de caixa de um projeto não deve depender do repasse nesse período.
5. **Chance de receber nos próximos 6 ou 12 meses para cada pendente,** atualizada pelo tempo já decorrido. Serve para priorizar o acompanhamento.
6. **Alerta de espera longa.** O 1º desembolso é o marco de segurança: depois dele, a anulação não ocorreu em nenhum caso. Uma espera acima de 24 a 30 meses entra na zona em que, historicamente, a maioria foi anulada. É o momento de agir sobre a cláusula suspensiva (documentação, licenças, projeto) junto ao concedente.

**O que ele não informa:**
- **Data exata:** o erro típico é de cerca de 7 meses, igual ao de uma média simples.
- **Diferenças entre municípios do mesmo porte:** existem, mas não foram estáveis entre anos.
- **O ritmo do ano fiscal:** em anos de liberação rápida, como 2023 e 2024, o modelo subestima o recebimento. As faixas devem ser lidas como conservadoras.
- **Causa:** as diferenças por porte e fonte são associações.
- **A qualidade da execução depois do 1º desembolso:** o atraso grave aos 75% da vigência é outro modelo, documentado à parte.

---

## 9. Limitações

1. **Mudança de regime:** a escolha de treinar com 2019 em diante supõe que o regime atual continua. Uma nova mudança nas regras (por exemplo, os prazos da cláusula suspensiva da Portaria Conjunta 33/2023) pode deslocar a curva.
2. **Efeito do ano não modelado:** o nível de liberação da União em cada ano é o principal fator e não é previsível com estes dados.
3. **Censura informativa:** a vigência atual é usada como fim da observação. Instrumentos anulados sem data de anulação na fonte ficam em risco até o fim da vigência, o que pode subestimar levemente a chance de receber.
4. **Porte pela população mais recente:** a faixa de porte é fixa no tempo, o que é razoável para mudanças pequenas de população, mas ignora mudanças de faixa.
5. **Curva de anulação de 2015–2019:** está desatualizada para o nível atual e serve só como sinal relativo.

---

## 10. Reprodução

Na raiz do repositório, com a camada Silver em `data/silver` (`transferegov_instrumentos`, `transferegov_desembolsos`, `ibge`):

```bash
python src/e05_tempo_desembolso/modelo_primeiro_desembolso.py
```

Os scripts de comparação rodam do mesmo jeito (`acerto_medias.py`, `svc_mlp_desembolso.py` e depois `acerto_svc_mlp.py`, `regularizacao_desembolso.py`). Os resultados são gravados em `docs/e05/tempo_desembolso/resultados/`. Só é preciso scikit-learn, pandas e numpy.

Os testes de fonte, município e ritmo do concedente (seção 5) e da mudança de regime da falha (seção 3) foram exploratórios e não estão no repositório. Os números deles estão registrados neste documento.

| Arquivo | Conteúdo |
|---|---|
| `src/e05_tempo_desembolso/modelo_primeiro_desembolso.py` | Modelo final, validação e aplicação |
| `src/e05_tempo_desembolso/tempo_primeiro_desembolso.py` | Preparação (evento, censura, trimestres), expansão pessoa-período, Kaplan–Meier e C-index |
| `src/e05_tempo_desembolso/experimento.py`, `alvos_falha.py` | Carga da base, pipeline de pré-processamento e data de carga |
| `src/e05_tempo_desembolso/acerto_medias.py` | Taxas de acerto: média geral, média por ministério e modelo final |
| `src/e05_tempo_desembolso/svc_mlp_desembolso.py`, `acerto_svc_mlp.py` | SVC e MLP no mesmo alvo |
| `src/e05_tempo_desembolso/regularizacao_desembolso.py` | Município com ridge, lasso e elastic net |
| `resultados/modelo_1o_desembolso_validacao.csv` | Métricas por corte e modelo |
| `resultados/modelo_1o_desembolso_referencia.csv` | Régua de prazos por porte e fonte |
| `resultados/modelo_1o_desembolso_municipios.csv` | Curva de cada município (fonte de referência) |
| `resultados/modelo_1o_desembolso_pendentes.csv` | Os 621 pendentes da PB, com a chance de receber nos próximos 6 e 12 meses |
