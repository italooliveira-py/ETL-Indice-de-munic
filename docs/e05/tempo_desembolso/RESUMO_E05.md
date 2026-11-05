# E05 — Resumo dos resultados (tempo até o 1º pagamento)

Documento para leitura rápida. Explica o que tentamos prever, com quais dados, como testamos e o que encontramos ao comparar os modelos com uma simples média.

---

## 1. O que queremos prever

**Pergunta:** depois que um convênio é assinado com um município, **quanto tempo leva até a União fazer o primeiro pagamento?**

**Como chegamos nessa pergunta:**
- No começo, o objetivo era prever se o projeto ia **falhar**: ser cancelado, não ser pago ou atrasar muito.
- Isso não funcionou, porque o "jeito de falhar" mudou muito ao longo dos anos. Em 2016, 92% dos convênios do Ministério da Integração terminavam em falha; em 2023, só 1%. Um modelo treinado no passado passou a errar ao contrário no presente.
- O tempo até o 1º pagamento é mais estável. Também é o que interessa a quem negocia com o município: **"quando o dinheiro deve chegar?"**

**Como medimos:**
- Para cada convênio, contamos os meses entre a assinatura e o primeiro pagamento maior que zero.
- Alguns convênios **ainda não receberam nada**. Eles não são descartados: entram como "esperou pelo menos X meses até hoje" (dados de 17/07/2026). Descartá-los faria o tempo de espera parecer menor do que é.
- O resultado é uma **curva de chance de já ter recebido** em 12, 18, 24 meses e assim por diante. Dela tiramos um **prazo provável** (o meio da curva) e uma **faixa provável**, dentro da qual cai metade dos casos.

---

## 2. Dados usados

| Dado | De onde vem | Para que serve |
|---|---|---|
| Convênios assinados (data, valor, ministério, tipo de instrumento, município) | Transferegov, camada Silver | Base de tudo |
| Pagamentos (data e valor de cada desembolso) | Transferegov, camada Silver | Calcular quando veio o 1º pagamento |
| População do município | IBGE, camada Silver | Classificar o porte do município |

**Recorte:**
- Municípios da Paraíba.
- Convênios com repasse da União assinados de 2019 a 2024: **2.211 convênios**.
- **223 municípios** e **17 ministérios**.

**Variáveis de entrada, todas conhecidas no dia da assinatura:**
- **Ministério que paga** (a "fonte"): Cidades, Saúde, Educação, Agricultura etc.
- **Porte do município**: até 10 mil habitantes, 10–20 mil, 20–50 mil, 50–100 mil e acima de 100 mil.
- **Testadas e descartadas**:
  - o município em si;
  - o tipo de instrumento;
  - o valor do convênio;
  - a contrapartida;
  - o histórico de pagamentos do município.

  Nenhuma delas melhorou a previsão de forma consistente.

**Cuidado com "olhar o futuro":** verificamos que nenhuma variável traz informação que só existiria depois da assinatura. Encontramos e corrigimos um caso: a contrapartida estava registrada com valores de aditivos posteriores à assinatura.

---

## 3. Como testamos (de forma justa)

- Os modelos sempre aprenderam **só com anos anteriores** e foram testados no ano seguinte, como aconteceria na vida real:
  - aprende 2019–2021 e testa em 2022;
  - aprende 2019–2022 e testa em 2023;
  - aprende 2019–2023 e testa em 2024.
- Os ajustes finos de cada modelo foram escolhidos **sem olhar o ano de teste**.
- **Régua de comparação:** a **média simples**, isto é, a curva média de todos os convênios dos anos anteriores, igual para todo mundo. Um modelo só vale a pena se for melhor que ela.

**Como medimos o acerto:**
- **Acerto do prazo (±6 meses):** o pagamento real caiu até 6 meses antes ou depois do prazo previsto?
- **Acerto da faixa:** o pagamento real caiu dentro da faixa prevista? Uma faixa larga demais acerta "de graça", por isso também mostramos a largura.
- **Acerto do "recebe em até 24 meses?":** sim ou não.
- **Ordenação:** o modelo coloca na frente quem de fato recebe primeiro? A nota 0,50 equivale a sortear; 1,00 seria ordenação perfeita.
- **Erro das chances em 24 meses:** quanto o modelo melhora sobre a média simples, em %.

---

## 4. Modelos comparados

| Modelo | Em palavras simples |
|---|---|
| **Média simples** | Todo convênio recebe a mesma previsão: a média do passado |
| **Média por ministério** | Uma média para cada ministério |
| **Regressão logística (porte + ministério)** | Uma média ajustada para cada combinação de porte e ministério, puxada para a média geral quando há poucos casos. É o **modelo final** |
| **SVC** | Modelo que busca fronteiras não lineares entre "recebe agora" e "ainda não" |
| **MLP (rede neural)** | Rede neural pequena, que pode combinar as variáveis de formas mais complexas |

O SVC e a MLP foram testados com as mesmas variáveis do modelo final. Também foram testados em uma versão **"rica"**, com tipo de instrumento, valores e contrapartida, para ver se achavam padrões que a regressão não acha.

---

## 5. Resultados (média dos 3 anos de teste)

| Modelo | Acerto do prazo (±6 meses) | Acerto da faixa (largura) | Acerto em 24 meses | Ordenação (0,50 = sorteio) | Melhora sobre a média |
|---|---|---|---|---|---|
| **Média simples** | 56% | 62% (15 meses) | 68% | 0,50 | — |
| Média por ministério | 53% | 60% (17 meses) | 53% | 0,55 | +1% |
| **Regressão logística (final)** | 53% | 62% (18 meses) | 55% | 0,56 | +1% |
| SVC (porte + ministério) | **67%** | 94% (**32 meses**) | 69% | 0,55 | +5% |
| SVC rico | 58% | 88% (26 meses) | 62% | 0,56 | +3% |
| MLP (porte + ministério) | 48% | 57% (17 meses) | 57% | 0,57 | 0% |
| MLP rica | 51% | 47% (14 meses) | 59% | 0,58 | −8% |

### Como ler

1. **Nenhum modelo ordena bem os convênios.** Todos ficam entre 0,55 e 0,58, um pouco acima do sorteio. Saber o ministério e o porte ajuda pouco a dizer *qual* convênio recebe antes.
2. **O SVC parece o melhor, mas por um motivo enganoso.**
   - Ele prevê prazos um pouco mais curtos para todos. Isso coincidiu com 2023 e 2024, anos em que a União pagou mais rápido.
   - Os 94% de acerto da faixa vêm de uma faixa de quase 3 anos.
   - Em 2022 ele foi pior que a média.
3. **A rede neural (MLP) não trouxe ganho.** Na versão rica, chegou a errar 26% mais que a média em 2023: aprendeu padrões do passado que não se repetiram.
4. **A média simples empata com tudo**, e os 68% de acerto em 24 meses dela são em parte sorte: a chance prevista ficou perto de 50%, e um pequeno desvio decide o "sim" ou o "não".
5. **A regressão logística é a escolha final.** Não por ser muito melhor que a média, e sim porque:
   - acerta tanto quanto as outras;
   - é estável entre os anos;
   - dá uma resposta que o gestor entende: "convênios do Ministério X em municípios do porte Y costumam receber em Z meses".

### Testes extras

- **Incluir o município como variável:** testado de três formas, todas regularizadas, ou seja, desenhadas para lidar com poucos casos por município (ridge, lasso, elastic net).
  - Quando o modelo pôde escolher, **zerou o efeito de todos os municípios** em 2 dos 3 anos.
  - Com cerca de 2 convênios por município por ano, não há informação suficiente para diferenciar um município do outro.
- **O ano pesa mais que qualquer variável:**
  - a chance de receber em até 24 meses variou de 51% (convênios de 2022) a 72% (2023 e 2024);
  - todos os modelos previram cerca de 50% nos três anos.

  O ritmo de pagamento depende do orçamento da União em cada ano (limites de pagamento, cortes de gastos, emendas, eleições), e isso não está nos nossos dados.

---

## 6. O que o modelo entrega ao gestor

Uma **tabela de referência por ministério e porte do município**, com o prazo provável até o 1º pagamento:

| Ministério | Prazo provável |
|---|---|
| Educação, Cidades | 21–24 meses |
| Agricultura, Integração | 24–30 meses |
| Esporte, Turismo | 27–30 meses |
| Saúde | 33–48 meses |

Municípios maiores esperam mais: cerca de 24 meses até 50 mil habitantes, 27 meses entre 50 e 100 mil e 30 meses acima de 100 mil.

**Exemplo: Pombal (34 mil habitantes, Ministério das Cidades)**
- Prazo provável de 24 meses, com faixa de 18 a 30.
- Cerca de 61% de chance de receber em até 2 anos.
- Para um convênio já assinado e ainda sem pagamento, o modelo diz a chance de o dinheiro chegar nos próximos 6 ou 12 meses. Também aponta se a espera já está fora do normal: nenhum dos 6 pendentes de Pombal está.

---

## 7. Limites (o que o modelo **não** faz)

- **Não diz qual convênio específico vai atrasar.** Ele dá uma expectativa média para o grupo, com margem de erro de cerca de ±6 meses na metade dos casos.
- **Não prevê o ritmo do ano.** Se a União acelerar ou travar pagamentos, todos os prazos mudam juntos. Em 2023 e 2024 os pagamentos vieram mais rápido do que o previsto.
- **Não qualifica o risco do município.** Os dados mostram que o prazo depende de **quem paga** (o ministério) muito mais do que de **quem recebe** (o município).
- **Para melhorar, o caminho é trazer dados novos, não um modelo mais complexo.** O mais promissor é o orçamento da União por ministério em cada ano.

---

## 8. Arquivos

Código em `src/e05_tempo_desembolso/`; documentos e resultados nesta pasta (`docs/e05/tempo_desembolso/`).

| Arquivo | Conteúdo |
|---|---|
| `MODELO_PRIMEIRO_DESEMBOLSO.md` | Documentação detalhada do modelo final |
| `modelo_primeiro_desembolso.py` | Regressão logística final, validação e tabelas de referência |
| `svc_mlp_desembolso.py`, `acerto_svc_mlp.py` | SVC e MLP no mesmo alvo e as taxas de acerto |
| `acerto_medias.py` | Acerto da média simples, da média por ministério e do modelo final |
| `regularizacao_desembolso.py` | Teste com o município (ridge, lasso, elastic net) |
| `resultados/*.csv` | Números de cada teste |
