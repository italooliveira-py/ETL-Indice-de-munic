# Metodologia inicial para escolher as variáveis

## 1. O que o artigo fez

O artigo partiu de 44 variáveis distribuídas em quatro dimensões. Em cada dimensão, escolheu três variáveis-âncora fundamentadas na literatura, estimou três modelos Elastic Net e manteve variáveis relevantes em pelo menos dois modelos. Depois reduziu o conjunto para 33 variáveis e calculou os pesos internos com os dois primeiros componentes da PCA. Os municípios foram comparados em grupos mais homogêneos, considerando bioma e classificação urbano/rural.

Essa sequência tem quatro ideias úteis:

1. coletar um conjunto mais amplo que o índice final;
2. não selecionar apenas por opinião;
3. tratar colinearidade;
4. calcular pesos somente depois da seleção.

O limite é que a relevância em relação a uma âncora não demonstra capacidade de prever falha futura. Por isso a adaptação deve separar os dois trabalhos acadêmicos.

## 2. Dois processos de seleção, não um só

### Índice de oportunidade - Visualização de Dados

Objetivo: sintetizar dimensões atuais e apoiar comparação/decisão.

Método possível:

```text
teoria -> qualidade e cobertura -> redundância -> Elastic Net com âncoras -> PCA -> subíndices
```

O Elastic Net com âncoras pode ser usado como no artigo, desde que as âncoras sejam justificadas e que os resultados sejam apresentados como estrutura estatística do índice, não como causalidade.

### Predição de risco - Aprendizagem Supervisionada

Objetivo: prever um evento público observável no período seguinte.

Método correto:

```text
X(t) -> Y(t+1)
```

Aqui a variável-alvo substitui as âncoras. A seleção por Elastic Net deve acontecer dentro de cada divisão temporal de treino, para evitar vazamento. O conjunto de teste precisa ser formado por anos posteriores aos anos de treino.

## 3. Filtros iniciais para cada candidata

| Etapa | Pergunta | Regra inicial |
|---|---|---|
| Relevância | Existe mecanismo plausível ligando a variável à decisão? | excluir sem hipótese documentada |
| Temporalidade | O valor estaria disponível antes do evento? | excluir qualquer informação posterior |
| Granularidade | É município-ano, evento ou área do projeto? | não misturar níveis sem agregação explícita |
| Cobertura | Quantos municípios-ano possuem valor? | manter >=70%; revisar 50%-70%; abaixo disso, fase 2 |
| Variação | A variável muda entre municípios/anos? | excluir constantes e quase constantes |
| Redundância | Repete a informação de outra variável? | investigar correlação absoluta de Spearman >=0,85; não excluir automaticamente |
| Estabilidade | A definição mudou ao longo do tempo? | marcar metodologia/fonte e testar quebra de série |
| Interpretabilidade | A persona entende o sentido do valor? | preferir proporções, per capita e denominadores explícitos |

## 4. Núcleo mínimo recomendado

### Fiscal-institucional

- dependência de transferências;
- investimento per capita;
- restos a pagar sobre receita;
- caixa sobre receita;
- resultado orçamentário;
- despesa com pessoal/RCL, depois de integrar o RGF.

As variáveis absolutas continuam no ETL, mas o índice deve privilegiar razões e valores per capita para evitar que o porte domine o resultado.

### Recursos e captação

- número de instrumentos ativos;
- valor liberado per capita;
- saldo a executar relativo;
- instrumentos próximos do vencimento;
- baixa execução financeira dentro da vigência.

Saldo elevado pode significar oportunidade e risco ao mesmo tempo. Ele não deve receber sentido único antes de ser cruzado com vigência e ritmo de execução.

### Execução e patrimônio

- taxa de obras paradas;
- valor de obras paradas;
- execução física média;
- atraso em dias em relação ao cronograma;
- histórico de paralisação/cancelamento;
- ausência de estudo de viabilidade.

O estado atual de uma obra não pode ser usado para prever um ano passado. Para o modelo supervisionado, deve-se reconstruir a data em que a paralisação ocorreu.

### Contratação pública

- número de contratações;
- contratações similares ao produto analisado;
- valor de contratações similares;
- licitações desertas, fracassadas ou revogadas, quando a situação estiver disponível;
- tempo entre publicação e resultado, se as datas permitirem.

Ausência no PNCP não prova ausência de contratação, especialmente nos primeiros anos de operação do portal.

### Territorial-socioambiental

- crescimento da área urbanizada;
- perda de vegetação nativa;
- superfície de água e mudança recente;
- anomalia de precipitação;
- cobertura de esgoto;
- cobertura de drenagem;
- domicílios/áreas sob risco de inundação;
- tipologia rural/urbana e bioma como controles de comparação.

## 5. Variáveis ambientais específicas de REURB

O problema de Lucas do Rio Verde mostra que o agregado municipal não basta. Devem existir duas tabelas separadas:

```text
municipio_ano
area_projeto_data
```

Na tabela da área do projeto, as candidatas prioritárias são:

- interseção com APP;
- distância a rios, córregos, nascentes e áreas alagáveis;
- cobertura e uso da terra no polígono e em uma faixa de entorno;
- perda de vegetação antes do contrato;
- área impermeabilizada e expansão urbana;
- restrições ambientais e unidades de conservação;
- existência de rede de drenagem, esgoto e destinação de resíduos;
- passivos, autos, licenças ou exigências ambientais documentadas.

Sem o polígono ou coordenadas do núcleo REURB, o ETL municipal só consegue avaliar risco ambiental estrutural, não confirmar o risco localizado que efetivamente causou o problema.

## 6. Âncoras candidatas para reproduzir a lógica do artigo

Estas âncoras são hipóteses para validação, não uma decisão fechada:

| Dimensão | Âncora 1 | Âncora 2 | Âncora 3 |
|---|---|---|---|
| Fiscal | dependência de transferências | caixa sobre receita | resultado orçamentário |
| Recursos | saldo a executar relativo | recursos liberados per capita | proximidade do vencimento |
| Execução | taxa de obras paradas | atraso médio | execução física média |
| Contratação | contratações similares | valor similar | resultado problemático de licitação |
| Socioambiental | expansão urbana | perda de vegetação | déficit de drenagem/esgoto |

Em cada dimensão:

1. padronizar apenas com dados de treino;
2. prever cada âncora pelas demais variáveis da dimensão;
3. repetir a validação por ano e por recortes de municípios;
4. registrar a frequência com que cada variável recebe coeficiente diferente de zero;
5. manter a candidata apenas se houver estabilidade, cobertura e sentido teórico.

Uma variável não deve permanecer só porque apareceu em dois modelos. O critério estatístico complementa, mas não substitui, a lógica do problema.

## 7. Tamanho do recorte

Lucas do Rio Verde, isoladamente, serve para teste retrospectivo e descoberta de falhas na hipótese. Não serve para estimar Elastic Net, PCA ou correlação estável.

Para a etapa estatística, monte vários municípios e anos. Um recorte inicial viável é:

```text
municípios da Paraíba x 2018-2024
```

Se a cobertura das fontes for insuficiente, amplie para o Nordeste. Preserve o ano como dimensão temporal e mantenha código IBGE como chave territorial.

## 8. Ordem prática

1. Rodar o ETL com IBGE e SICONFI.
2. Baixar e perfilar Transferegov, MapBiomas, SNIS/SINISA e ANA.
3. Revisar `status_variaveis.csv` e `qualidade_variaveis.csv`.
4. Fechar a definição de `evento_risco_t1`.
5. Construir uma matriz município-ano sem informação futura.
6. Fazer análise de faltantes, estabilidade temporal e redundância.
7. Rodar seleção com Elastic Net adequada a cada disciplina.
8. Calcular pesos e construir subíndices somente depois.
