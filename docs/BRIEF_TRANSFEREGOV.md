# Brief de negócio — Transferegov

Atualizado em 2026-10-26. Para quem precisa entender o Transferegov antes de usá-lo no índice de contexto municipal ou em modelos de risco de execução. Detalhes técnicos de carga e cobertura estão em [MAPEAMENTO_FONTES.md](MAPEAMENTO_FONTES.md); a decisão sobre o recorte no Bronze, na [ADR 0002](adr/0002-bronze-recorte-pb-transferegov.md).

## 1. O que é

O Transferegov.br é a plataforma do Governo Federal (Ministério da Gestão e da Inovação) por onde passam as transferências da União para estados, municípios e organizações. Sucedeu o SICONV em 2023 e manteve o histórico. Tudo o que acontece com o recurso — proposta, análise, assinatura, liberação, execução, prestação de contas — é registrado ali, com data. Por isso ele é, ao mesmo tempo, um sistema operacional e uma fonte de dados abertos.

Não passam pelo Transferegov as transferências constitucionais e automáticas (FPM, cota-parte de ICMS, royalties). Nos módulos usados aqui, ele cobre o dinheiro que o município precisa **conquistar**: por projeto ou por emenda parlamentar.

## 2. Como se divide

| Módulo | O que transfere | Usado neste projeto |
|---|---|---|
| **Discricionárias e Legais** | Convênios, contratos de repasse e termos de compromisso: programas dos ministérios e emendas com finalidade definida | Sim |
| **Transferências Especiais** | Emendas parlamentares individuais transferidas direto ao ente ("emendas Pix") | Sim |
| Gestão de Parcerias, Fundo a Fundo, Termos de Execução Descentralizada, entre outros | Parcerias com organizações da sociedade civil, repasses entre fundos e entre órgãos federais | Não: fora do escopo municipal ou sem o município como executor |

As duas modalidades usadas aparecem lado a lado na Constituição: emendas individuais podem ir ao município por **transferência especial** ou por **transferência com finalidade definida** (CF, art. 166-A, I e II).

## 3. Como funciona cada modalidade

### Discricionárias e Legais

1. **Programa:** o ministério abre um programa com regras, valores e critérios.
2. **Proposta:** a prefeitura cadastra a proposta e o plano de trabalho. Na PB, há 54 mil propostas de administrações municipais na base.
3. **Análise e celebração:** o concedente analisa; aprovada, o instrumento é assinado e publicado. Contrato de repasse tem uma **mandatária** (em regra a Caixa) que analisa projeto e acompanha a obra.
4. **Cláusula suspensiva:** o instrumento pode ser assinado antes de projeto, licença ou titularidade estarem prontos; o dinheiro só é liberado depois que a condição é cumprida.
5. **Execução:** a prefeitura licita, contrata e executa; o recurso é liberado em parcelas na conta específica, conforme o andamento.
6. **Alterações:** valor e prazo mudam por termo aditivo; o concedente prorroga de ofício quando atrasou a liberação.
7. **Prestação de contas:** ao final, a prefeitura comprova a execução; as contas são aprovadas, aprovadas com ressalvas ou rejeitadas.

Na PB, 6.182 instrumentos de prefeituras foram assinados; 3.580 estiveram vigentes em algum momento de 2020–2024.

### Transferências Especiais (emendas Pix)

1. O parlamentar indica a emenda e o município beneficiário.
2. A prefeitura registra um **plano de ação** (conta bancária, custeio ou investimento).
3. A União empenha e paga — na PB, sempre no mesmo ano do plano; o pagamento pode cair no ano seguinte.
4. O recurso passa a pertencer ao município no ato da transferência; a execução e o controle ficam com o ente e os órgãos de controle.

Na PB, passaram de 17 municípios e R$ 9 mi pagos em 2020 para 206 municípios e R$ 208 mi em 2024.

## 4. Regras que seguem

### Comuns

- **Emendas individuais impositivas:** até 2% da receita corrente líquida da União, metade para saúde, com execução obrigatória (CF, art. 166, §§ 9º e 11).
- **Lei de Responsabilidade Fiscal, art. 25:** transferência voluntária exige, entre outros, adimplência do município com a União, cumprimento dos limites de pessoal e dívida e dos mínimos de saúde e educação, e previsão de contrapartida; as exigências são verificadas no CAUC, do Tesouro Nacional.

### Discricionárias e Legais

- **Decreto 11.531/2023 e Portaria Conjunta MGI/MF/CGU 33/2023**, para instrumentos celebrados a partir de setembro de 2023. Os anteriores seguem as regras da época da celebração (Decreto 6.170/2007 e Portaria Interministerial 424/2016) — PC 33/2023, art. 2º, I.
- **Cláusula suspensiva:** até 9 meses da assinatura, prorrogável até 18 meses no total (art. 24, § 3º); o recurso só é transferido depois de retirada a condição (art. 24, § 8º). Sem repasse e com a condição descumprida, o instrumento é extinto (art. 91, III).
- **Contrapartida:** calculada sobre o valor global do objeto (art. 32).
- **Conta específica** em instituição financeira oficial (art. 35, XVII).
- **Alteração de prazo ou valor:** proposta justificada pelo convenente com pelo menos 60 dias de antecedência do fim da vigência (art. 46); prorrogação de ofício pelo concedente **antes do término**, quando houver atraso na liberação (art. 35, XXIV).
- **Prestação de contas:** até 60 dias após o fim da vigência ou a conclusão do objeto (art. 96); análise em 60 dias, se informatizada, ou 180, se convencional (art. 97).
- **Contas rejeitadas:** notificação para devolver os recursos em 30 dias; sem devolução, impugnação das contas e Tomada de Contas Especial (arts. 103 a 105).

### Transferências Especiais

- Repasse direto, **sem convênio**; o recurso pertence ao ente no ato da transferência e deve ir para programações finalísticas (CF, art. 166-A, § 2º).
- **Pelo menos 70% em despesas de capital** (art. 166-A, § 5º); vedado pagar pessoal, encargos e dívida (art. 166-A, § 1º).
- Até 2023 não havia prazo de execução nem obrigação de prestar contas detalhada. A partir de 2024, a decisão do STF na ADPF 854, a Lei Complementar 210/2024 e portarias conjuntas (dez/2024; MF/MGI 15/2025) passaram a exigir plano de trabalho registrado no Transferegov e regras de transparência e rastreabilidade.

## 5. Como usar para qualificar a execução de projetos nos municípios

O valor do Transferegov para o projeto está em ser um **registro processual datado**: ele mostra não só quanto dinheiro chega, mas como a prefeitura conduz um projeto do pedido à prestação de contas.

### 5.1 Indicadores de contexto (painel município × ano, já no Gold)

| Indicador | Lê | Uso temporal |
|---|---|---|
| Instrumentos assinados e valor global na assinatura | capacidade de captar recursos por projeto | apto (data da assinatura) |
| Valor desembolsado | recurso que efetivamente chegou para executar | apto (data do desembolso) |
| Instrumentos vigentes | tamanho da carteira em execução simultânea | apto (regra legal de prorrogação) |
| Planos e valor pago das Especiais | peso das emendas Pix | apto (ano do plano e data da ordem bancária) |
| Repasse atual e valor planejado das Especiais | fotografia de hoje, inclui ajustes posteriores | só descritivo |

### 5.2 Indicadores a derivar do Silver

- **Conversão de propostas:** propostas que viram instrumentos — capacidade técnica de elaborar projetos aceitos.
- **Ritmo de execução:** desembolsado sobre pactuado ao longo da vigência; anos sem desembolso em instrumento vigente.
- **Peso da cláusula suspensiva:** tempo entre assinatura e primeiro desembolso — proxy de maturidade do projeto (projeto, licença, terreno).
- **Dependência de emendas:** parcela da carteira vinda de emendas, e de emendas Pix em relação ao total federal.
- **Concentração:** número de concedentes e áreas; carteira dominada por um único órgão ou parlamentar.
- **Histórico de desfechos:** anulações, rescisões, prorrogações e contas rejeitadas em instrumentos **já encerrados antes do ano t**.

### 5.3 Desfechos que servem de alvo (não de preditor)

No Silver, `resultado_*` registra a situação final de cada instrumento. Em 2020–2024, na PB:

| Desfecho | % dos instrumentos | Leitura |
|---|---|---|
| Prorrogado (vigência atual maior que a original) | 48,2% | atraso de execução — o mais frequente e o mais informativo |
| Anulado | 1,9% | projeto que não saiu do papel, em geral por cláusula suspensiva não cumprida |
| Rescindido | 1,0% | interrupção depois de iniciado |
| Contas rejeitadas | 0,1% | falha grave; raro e ainda incompleto, porque muitas contas estão em análise |

Duas formas de modelar:

- **Por instrumento (recomendado):** ~6 mil linhas na PB. Alvo: o instrumento terá desfecho adverso (prorrogação relevante, anulação ou rescisão)? Preditores: o que se sabia na assinatura — modalidade, órgão, valor, contrapartida, origem em emenda — e o histórico do município até aquela data.
- **Por município-ano:** 1.115 linhas. Alvo: taxa de desfechos adversos dos instrumentos do município em t+1. Mais próximo do índice, mas com amostra pequena.

### 5.4 Cuidados

- **Situação, vigência e valores são a fotografia da data de carga.** Desfechos entram como alvo, nunca no `X(t)`; anulados continuam contados como vigentes no contexto.
- **Desfechos recentes estão censurados:** instrumentos de 2023–2024 ainda estão em execução; comparar só coortes com tempo de observação equivalente.
- **Discricionárias e Especiais não se somam como "recurso federal" sem identificar a modalidade:** têm controle e risco diferentes.
- **Valores das emendas na tabela de emendas não se somam:** a mesma emenda se repete por programa.
- **Não há data de publicação no portal:** a defasagem entre o evento e o registro público é desconhecida; é ruído aceito e documentado.
- **O repositório oficial está parado desde 17/07/2026**, enquanto as APIs das Discricionárias são lançadas (instrumentos: nov/2026–fev/2027); cargas futuras devem migrar para elas.

## Fontes

Constituição Federal, arts. 166 e 166-A ([Planalto](https://www.planalto.gov.br/ccivil_03/constituicao/constituicao.htm)); [Portaria Conjunta MGI/MF/CGU 33/2023](https://www.lex.com.br/portaria-conjunta-mgi-e-mf-e-cgu-no-33-de-30-de-agosto-de-2023/); [API de dados abertos do Transferegov](https://www.gov.br/transferegov/pt-br/ferramentas-gestao/api-de-dados-abertos-transferegov.br); [Portaria Conjunta de dez/2024 sobre plano de trabalho das emendas Pix](https://static.poder360.com.br/2024/12/DOU-portaria-conjunta-emendas-10-dez-2024.pdf); [TCU — Transferências especiais, Diálogo Público 2025](https://dialogopublico.tcu.gov.br/wp-content/uploads/sites/20/2025/10/1TCU-Waldemir-Transferencias-especiais-Dialogo-Publico-GO-2025.pdf). Números da PB: Gold `255610c10e212fc13e0e` e Silver desta mesma geração.
