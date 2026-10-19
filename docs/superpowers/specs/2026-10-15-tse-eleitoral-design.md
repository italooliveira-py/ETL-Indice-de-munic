# ETL Político-Eleitoral do TSE — Especificação de desenho

**Data:** 2026-10-15
**Escopo:** municípios da Paraíba, eleições municipais ligadas aos ciclos de 2016, 2020 e 2024, com fotografias anuais de 2020 a 2024
**Estado:** desenho aprovado para especificação; implementação ainda não iniciada

## Objetivo

Adicionar ao projeto um módulo isolado e retrocompatível para coletar, validar e transformar dados oficiais do Tribunal Superior Eleitoral em eventos eleitorais, mandatos municipais e contexto político anual. A fonte será descritiva e auditável: não produzirá score de risco, rótulo causal ou pontuação derivada da existência de eleição suplementar.

O módulo atenderá os 223 municípios da Paraíba obtidos por correspondência oficial TSE–IBGE. A integração estadual com o ETL principal só ocorrerá depois que os testes próprios do módulo passarem e a correspondência contiver exatamente os 223 municípios da Paraíba, com códigos TSE e IBGE únicos. A fonte permanecerá desabilitada na configuração padrão até ser solicitada explicitamente.

## Princípios obrigatórios

- Usar somente dados oficiais do TSE para resultados eleitorais e correspondência territorial.
- Preservar o código IBGE como texto de sete dígitos e usar `codigo_ibge + ano` na integração anual.
- Tratar `SQ_CANDIDATO` como identificador daquela eleição, nunca como identidade pessoal persistente.
- Não publicar dados pessoais de candidatos que não sejam necessários aos indicadores municipais.
- Não inferir vencedor, posse, continuidade ou `partido_prefeito_no_pleito_origem` quando a evidência oficial for insuficiente.
- Não permitir informação futura na fotografia anual nem substituir ausência por zero.
- Preservar a eleição regular quando houver suplementar; cada pleito permanece um evento separado.
- Não criar regra específica para Cabedelo ou qualquer outro município.
- Não executar coleta estadual completa, `--refresh`, commit ou push durante implementação e validação inicial.

## Fontes oficiais e edições

O coletor usará os arquivos de dados abertos do TSE para:

1. consulta de candidaturas;
2. votação nominal por município e zona;
3. detalhe da votação por município e zona;
4. correspondência oficial de códigos TSE e IBGE;
5. listas oficiais de eleições suplementares dos ciclos municipais.

Os arquivos de perfil de comparecimento e abstenção não serão usados no primeiro corte. Comparecimento e abstenção serão derivados do detalhe da votação, no mesmo pleito, município, cargo e turno, evitando misturar versões, cargos ou eleições regulares e suplementares.

Cada edição terá metadados versionados com URL oficial, ano do arquivo, nome do membro ZIP, tamanho comprimido e descomprimido, CRC, ETag e `Last-Modified` quando fornecidos. Se o TSE publicar hash oficial, ele será preservado e validado com algoritmo e origem explícitos. Independentemente disso, o coletor calculará `sha256_local` como impressão digital do artefato persistido para detectar alteração posterior e reutilizar checkpoints; esse valor local não será descrito como validação oficial. O mapeamento do código oficial de situação totalizadora será versionado por edição em configuração declarativa. A descrição textual original será preservada para auditoria.

## Coleta, cache e integridade

HTTP Range será o método preferencial para localizar e extrair o membro da Paraíba dentro dos ZIPs nacionais. O coletor validará o suporte real a intervalos e não confiará apenas no cabeçalho anunciado pelo servidor.

O fluxo por artefato será:

1. consultar metadados remotos e localizar o membro esperado;
2. tentar obter o membro por intervalos HTTP;
3. validar o membro pelo tamanho registrado no diretório do ZIP e pelo CRC do ZIP, além de calcular a impressão digital `sha256_local` do artefato persistido;
4. se existir hash oficial publicado, validá-lo separadamente; se o servidor ignorar intervalos, responder intervalos inconsistentes ou qualquer validação aplicável falhar, descartar somente o temporário incompleto e baixar o ZIP integral;
5. extrair, validar e gravar atomicamente o membro da Paraíba;
6. registrar método efetivo (`http_range` ou `zip_integral`) e resultado no manifesto.

Arquivos serão escritos em temporário e promovidos por renomeação atômica somente após validação. Resposta parcial, ZIP truncado, membro ausente, CRC inválido, tamanho divergente, hash oficial divergente quando disponível ou alteração posterior do `sha256_local` produzirão estado `parcial` ou `falhou`; nunca `completa`. Checkpoints válidos serão reutilizados por padrão. A área existente de dados e caches não será apagada.

Estrutura proposta:

```text
data/raw/tse_eleitoral/
  metadados/
  correspondencia_tse_ibge/
  consulta_cand/
  votacao_candidato_munzona/
  detalhe_votacao_munzona/
  eleicoes_suplementares/
data/staging/tse_eleitoral/
output/eventos_eleitorais_tse.csv
output/mandatos_municipais.csv
output/municipio_ano_politico.csv
output/qualidade_tse_eleitoral.csv
output/manifesto_tse_eleitoral.json
```

O manifesto registrará fonte, edição, URL, membro, escopo, método de obtenção, tamanho comprimido e descomprimido, CRC do ZIP, `sha256_local`, hash oficial e algoritmo quando disponíveis, horário UTC, estado, número de linhas lidas/rejeitadas e erro final.

## Normalização territorial

A correspondência oficial TSE–IBGE será a única ponte entre códigos eleitorais e `codigo_ibge`. Para a integração estadual de PB, o catálogo deverá conter exatamente 223 municípios, 223 códigos TSE únicos e 223 códigos IBGE únicos, todos com UF igual a PB. Qualquer divergência bloqueará a integração estadual e será registrada no manifesto; não será reduzida a aviso. A contagem é um requisito de completude deste recorte, enquanto a unicidade e a UF continuam sendo validações estruturais independentes.

Os campos territoriais diferem entre arquivos: candidaturas municipais usam `SG_UE`, enquanto votação e detalhe podem usar `CD_MUNICIPIO` e `SG_UE`. O estágio normalizará esses campos explicitamente para `codigo_municipio_tse`; não fará correspondência aproximada por nome. Registros sem correspondência oficial serão rejeitados e contabilizados.

## Identificação dos pleitos e vencedores

As linhas de candidatura por turno usarão uma chave própria, que inclua, no mínimo:

```text
ano_eleicao_origem_ciclo
CD_ELEICAO
CD_TIPO_ELEICAO
DT_ELEICAO
NR_TURNO
codigo_municipio_tse
CD_CARGO
SQ_CANDIDATO
```

O evento eleitoral agregado terá outra chave, sem identificador de candidato e sem turno:

```text
ano_eleicao_origem_ciclo
CD_ELEICAO
CD_TIPO_ELEICAO
DT_ELEICAO
codigo_municipio_tse
CD_CARGO
```

`NR_TURNO` será atributo das observações de candidatura e originará `numero_turno_decisivo` no evento agregado. `SQ_CANDIDATO` nunca fará parte da chave do evento. Essa separação permite agregar zonas e turnos sem transformar uma candidatura em identidade do pleito.

`ano_eleicao_origem_ciclo` será o ano da eleição municipal regular que abriu o ciclo administrativo. Um evento suplementar manterá o ano da eleição regular à qual está vinculado, ainda que a suplementar ocorra em ano posterior.

O filtro de prefeito usará o código oficial do cargo. Eleições ordinárias e extraordinárias serão distinguidas pelo código oficial do tipo de eleição; descrições textuais não serão usadas por correspondência parcial.

A identificação do vencedor usará prioritariamente `CD_SIT_TOT_TURNO`, interpretado por mapeamento versionado para cada edição. `DS_SIT_TOT_TURNO` será preservado sem alteração para auditoria. Se o código estiver ausente, desconhecido ou contradizer a descrição de modo material, o pleito ficará pendente e não haverá vencedor inferido por maior votação.

Cada evento terá `data_disponibilidade_adotada`, `precisao_data_disponibilidade` e `regra_data_disponibilidade`. Quando uma fonte oficial histórica informar a data de totalização ou de publicação do resultado, essa data será usada com precisão `dia_oficial`. Quando não houver data histórica de totalização disponível, será adotada conservadoramente a data de 1º de janeiro do ano seguinte ao pleito, com precisão `ano_regra_conservadora` e regra documentada como `primeiro_dia_ano_seguinte`. A data da eleição não será usada como substituta da disponibilidade. Um resultado só poderá entrar em fotografia ou junção temporal em corte igual ou posterior a `data_disponibilidade_adotada`.

A votação do candidato será somada entre zonas somente dentro da mesma eleição, tipo, data, turno, município e candidato. O turno decisivo será o turno oficial em que o vencedor for totalizado. Votos de turnos diferentes nunca serão somados. O percentual do vencedor usará `QT_TOTAL_VOTOS_VALIDOS` do mesmo pleito, município e turno decisivo. Em pleito com apenas uma candidatura válida, a margem para o segundo colocado será nula, não 100 pontos percentuais.

## Eventos eleitorais

`output/eventos_eleitorais_tse.csv` terá uma linha por pleito municipal de prefeito, regular ou suplementar. Campos mínimos:

- identificadores do ciclo, eleição, tipo, data e município, além de `numero_turno_decisivo` como atributo;
- `codigo_ibge`, nome do município e UF;
- código e descrição originais da situação totalizadora;
- partido do vencedor, votos, percentual e margem, quando validados;
- aptos, comparecimento, abstenções e respectivas taxas;
- `origem_evento=regular|suplementar`;
- `data_disponibilidade_adotada`, sua precisão e a regra aplicada;
- estado de validação do resultado e motivo de pendência;
- metadados de origem e edição.

Taxas de comparecimento e abstenção serão calculadas a partir do detalhe da votação, filtrado pelo mesmo pleito, município, cargo e turno. A identidade `aptos = comparecimento + abstenções` deverá ser validada antes da publicação. Divergência não explicada deixará os indicadores pendentes.

Uma eleição suplementar será sempre registrada como evento próprio. Sua ocorrência não produzirá pontuação de risco nem substituirá automaticamente a eleição regular.

## Mandatos e transições

`output/mandatos_municipais.csv` representará intervalos temporais de gestão. A eleição regular abre o mandato regular segundo a regra constitucional do ciclo. Uma eleição suplementar só poderá encerrar o mandato vigente e abrir um mandato suplementar após validação, em fonte oficial, da data efetiva de posse ou transição.

A hierarquia de fontes para validar posse suplementar será:

1. termo, ata ou ato de posse publicado pela Câmara Municipal, prefeitura ou diário oficial competente;
2. decisão, acórdão, certidão ou comunicação processual oficial do TRE-PB ou TSE que declare explicitamente a data efetiva de assunção ao cargo;
3. publicação no Diário da Justiça Eletrônico ou diário oficial que declare explicitamente que a posse ocorreu em determinada data;
4. notícia institucional do TSE, TRE-PB, Câmara Municipal ou prefeitura que informe explicitamente a data da posse, usada somente quando não houver documento formal acessível e sem conflito com outra fonte oficial.

Diplomação, proclamação do resultado e data da eleição não equivalem à posse, salvo se o próprio documento oficial declarar expressamente a data de assunção. Havendo conflito entre fontes oficiais, ausência de dia exato ou apenas mês/ano, a transição permanecerá `pendente_data_posse`; para alterar intervalos de mandato, a precisão exigida será `dia_oficial`.

Cada mandato terá, no mínimo:

- `codigo_ibge`;
- `ano_eleicao_origem_ciclo`;
- eleição de origem;
- `partido_prefeito_no_pleito_origem`;
- `origem_gestao=regular|suplementar` para atribuições validadas;
- início e fim de vigência, com precisão declarada;
- fonte oficial da transição;
- `status_transicao=validada|pendente_data_posse`;
- motivo de pendência.

`partido_prefeito_no_pleito_origem` é o partido do candidato a prefeito cuja eleição validada originou aquele intervalo de mandato. O campo descreve a origem eleitoral do prefeito vigente e não será renomeado ou reinterpretado como partido genérico da administração municipal.

Suplementares vinculadas ao ciclo municipal de 2016 que afetem a gestão vigente em 2020 serão abrangidas para toda a Paraíba. Não haverá lista ou desvio específico para Cabedelo. Se a data efetiva de posse não puder ser confirmada por fonte oficial, o evento permanecerá registrado, a transição ficará `pendente_data_posse` e nenhuma atribuição silenciosa será feita. `partido_prefeito_no_pleito_origem` ficará ausente no intervalo cuja titularidade não possa ser sustentada.

## Fotografia município-ano

`output/municipio_ano_politico.csv` terá exatamente uma linha por `codigo_ibge + ano_fotografia` para os anos de 2020 a 2024. A integração estadual só será permitida com os 223 municípios oficialmente correspondidos e, portanto, deverá produzir exatamente 1.115 linhas e 1.115 chaves únicas.

Cada linha é uma fotografia às 00:00 de 1º de janeiro do ano. O estado político será obtido por junção temporal *as of* com os intervalos validados de `mandatos_municipais.csv`, usando apenas fatos disponíveis até o corte. Resultados realizados durante o próprio ano não aparecerão nessa fotografia.

Os quatro campos temporais terão significados distintos:

- `ano_eleicao_origem_ciclo`: ano da eleição municipal regular que originou o ciclo administrativo, como 2016 para a gestão vigente em 2020 e 2020 para as gestões de 2021 a 2024;
- `numero_ano_ciclo_eleitoral`: posição civil da fotografia dentro do ciclo, calculada como `ano_fotografia - ano_eleicao_origem_ciclo`, resultando em 4 para 2020 e em 1, 2, 3 e 4 para 2021 a 2024;
- `ano_fotografia`: ano civil cujo estado é observado às 00:00 de 1º de janeiro;
- `numero_ano_gestao_atual`: ordinal do ano civil do mandato efetivamente vigente, calculado como `ano_fotografia - ano(data_inicio_vigencia) + 1`; uma gestão suplementar iniciada em 2019 estará no número 2 na fotografia de 2020.

`numero_ano_gestao_atual` só será preenchido quando `data_inicio_vigencia` tiver precisão diária validada. Uma suplementar não reinicia `numero_ano_ciclo_eleitoral`, pois continua vinculada ao ciclo regular de origem.

Consequências obrigatórias:

- a fotografia de 2020 representa a gestão do ciclo de 2016 vigente em 2020, inclusive suplementar anterior a 1º de janeiro de 2020 cuja transição tenha sido validada;
- o resultado regular de 2020 não aparece na fotografia de 2020;
- a continuidade partidária do pleito de 2020 só pode aparecer a partir da fotografia de 2021;
- o resultado de 2024 permanece como evento e não altera a fotografia de 2024;
- projetos ou análises com data de início durante o ano deverão usar posteriormente uma junção temporal *as of* diretamente com `mandatos_municipais.csv` e `eventos_eleitorais_tse.csv`, em vez da fotografia anual.

`continuidade_partidaria_pleito` compara o partido vencedor com `partido_prefeito_no_pleito_origem`, correspondente ao prefeito vigente na data do pleito de origem, somente quando ambos estiverem validados e o resultado já estiver disponível segundo `data_disponibilidade_adotada`. O valor ficará ausente em caso de transição, vencedor, disponibilidade ou partido pendente. A variável é descritiva e não será convertida em risco.

## Integração retrocompatível

O núcleo novo ficará em `etl_tse_eleitoral.py`, com funções puras para normalização e construção das três tabelas e uma fronteira de I/O para coleta e checkpoints. O arquivo `etl_primario.py` receberá apenas um adaptador localizado depois que os testes do módulo passarem.

A linha de comando aceitará `tse_eleitoral` em `--sources`. A fonte não será incluída automaticamente no `config.json` durante a validação; execução explícita sugerida:

```powershell
python etl_primario.py --sources tse_eleitoral --resume
```

`--resume` reutilizará artefatos válidos. O smoke test usará diretório isolado e não modificará configuração de produção. A integração preservará as colunas existentes de `base_municipio_ano.csv`; colunas políticas serão anexadas por `codigo_ibge + ano`. O catálogo de fontes, catálogo de variáveis, cobertura e manifesto principal serão atualizados somente na etapa de integração.

## Tratamento de falhas

O módulo interromperá a partição afetada, preservará progresso válido e registrará estado pendente ou falho quando ocorrer:

- falha de tamanho ou CRC do membro, divergência de hash oficial quando disponível ou inconsistência do `sha256_local` após fallback integral;
- membro PB ausente ou esquema obrigatório incompatível;
- edição sem mapeamento conhecido de `CD_SIT_TOT_TURNO`;
- contradição material entre código e descrição da totalização;
- duplicidade territorial na correspondência TSE–IBGE;
- catálogo estadual diferente de 223 correspondências válidas e únicas para PB;
- pleito sem chave unívoca ou mistura de eleição regular e suplementar;
- divergência não explicada nos totais de comparecimento;
- suplementar sem data oficial validada de posse;
- qualquer mudança necessária no significado ou formato das saídas já existentes.

Falha em uma edição não será convertida em ausência de evento, zero ou continuidade partidária. A integração no ETL principal não ocorrerá enquanto os testes isolados estiverem falhando.

## Estratégia de testes

Os testes serão escritos antes da implementação e usarão fixtures pequenas, sem baixar as bases nacionais. A suíte isolada cobrirá:

1. HTTP Range válido com tamanho e CRC confirmados e `sha256_local` registrado;
2. servidor que ignora ou devolve intervalos inconsistentes e aciona fallback integral;
3. falha de validação do download integral registrada como incompleta;
4. escrita atômica e reutilização de checkpoint válido;
5. correspondência TSE–IBGE, preservação do código IBGE textual e bloqueio estadual quando o catálogo não tiver exatamente 223 vínculos válidos e únicos;
6. normalização de `SG_UE` e `CD_MUNICIPIO`;
7. separação por código de eleição e tipo oficial, sem busca textual ambígua;
8. vencedor por `CD_SIT_TOT_TURNO` com mapa versionado e descrição auditável;
9. código desconhecido ou contraditório sem inferência de vencedor;
10. chaves distintas para candidatura-turno e evento agregado, com `SQ_CANDIDATO` somente na primeira;
11. soma entre zonas sem mistura de turnos;
12. margem nula para candidatura única;
13. comparecimento e abstenção no mesmo pleito/turno e validação da identidade;
14. eleição regular preservada e suplementar registrada separadamente;
15. suplementar do ciclo de 2016 com transição validada antes de 2020;
16. hierarquia oficial de posse, conflito de fontes e posse sem dia exato mantidos pendentes;
17. suplementar sem posse oficial mantida pendente e sem substituição;
18. cobertura estadual sem regra específica por município;
19. `data_disponibilidade_adotada` oficial e fallback conservador para 1º de janeiro do ano seguinte;
20. fotografia em 1º de janeiro sem resultado ocorrido durante o ano;
21. continuidade de 2020 ausente em 2020 e disponível, quando validada, em 2021;
22. distinção entre `ano_eleicao_origem_ciclo`, `numero_ano_ciclo_eleitoral`, `ano_fotografia` e `numero_ano_gestao_atual`;
23. 1.115 chaves únicas no quadro PB 2020–2024 com fixture territorial completa sintética;
24. ausência de score, rótulo causal e dados pessoais desnecessários;
25. integração por `codigo_ibge + ano_fotografia` sem alterar semântica das colunas existentes;
26. fonte desabilitada por padrão e seleção explícita por CLI;
27. falha da suíte isolada impedindo a integração.

Depois da suíte isolada, o smoke real ficará limitado a dois municípios da Paraíba e aos ciclos de 2016 e 2020, em diretório de saída isolado, com checkpoints reutilizáveis e sem `--refresh`. O smoke validará esquema, correspondência, resultado, comparecimento e pelo menos um caminho regular. Ele não será apresentado como validação de cobertura estadual nem autorizará uma coleta completa.

## Checkpoints de entrega

1. **Contratos e testes isolados:** esquemas, chaves, temporalidade, vencedores e integridade de download definidos em testes falhando.
2. **Coletor e cache:** HTTP Range, fallback integral, checksums, escrita atômica e manifesto passam nos testes.
3. **Transformações eleitorais:** correspondência, eventos, resultados e comparecimento passam nos testes.
4. **Mandatos e temporalidade:** regular, suplementar, transição pendente e fotografia em 1º de janeiro passam nos testes.
5. **Validação isolada:** suíte nova e suíte legada completas passam antes de qualquer integração.
6. **Integração localizada:** CLI, configuração opt-in, catálogos, cobertura e merge anual são adicionados e testados.
7. **Smoke pequeno:** dois municípios, ciclos 2016/2020, sem `--refresh`, em saída isolada.
8. **Revisão antes da coleta:** apresentar status, testes, manifesto e limitações; a coleta TSE estadual só será executada mediante autorização posterior.

## Critérios de aceite

- Todo membro bruto publicado como completo possui tamanho e CRC do ZIP validados, `sha256_local` registrado e hash oficial validado quando o TSE o disponibilizar.
- Falha de HTTP Range aciona fallback integral; falha do fallback permanece incompleta.
- Vencedores decorrem do código oficial versionado, com descrição original auditável.
- Regular e suplementar coexistem como eventos distintos.
- Uma suplementar só altera mandato após data oficial de transição validada.
- A fotografia anual usa 1º de janeiro e não contém resultado ocorrido depois do corte.
- O contexto de 2020 decorre do ciclo de 2016; o resultado de 2020 só pode afetar 2021.
- `ano_eleicao_origem_ciclo`, `numero_ano_ciclo_eleitoral`, `ano_fotografia`, `numero_ano_gestao_atual` e `origem_gestao` mantêm significados distintos.
- O quadro PB 2020–2024 só é integrado com 223 correspondências territoriais válidas e possui 1.115 chaves únicas por `codigo_ibge + ano_fotografia`.
- Não há score, imputação silenciosa, regra hard-coded municipal ou exposição de dados pessoais desnecessários.
- Os testes do módulo e a suíte legada passam antes da integração; o smoke permanece pequeno e isolado.

## Arquivos previstos

Criação:

- `etl_tse_eleitoral.py`
- `tests/test_tse_eleitoral.py`
- `tests/test_tse_integracao.py`
- artefatos TSE nas pastas de dados e saída descritas, somente durante testes/smoke autorizados

Alteração localizada após os testes isolados:

- `etl_primario.py`
- `config.json`
- `catalogo_fontes.csv`
- `catalogo_variaveis.csv`
- `README.md` ou `ENTREGA.md`, conforme o comportamento implementado

Nenhum arquivo principal será reescrito e nenhuma arquitetura existente será substituída.
