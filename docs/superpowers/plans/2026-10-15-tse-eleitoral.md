# ETL Político-Eleitoral do TSE — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task after explicit authorization. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar uma fonte eleitoral oficial, auditável e temporalmente segura para os 223 municípios da Paraíba, produzindo eventos, mandatos e fotografias anuais de 2020 a 2024 sem vazamento futuro.

**Architecture:** Toda a coleta e transformação eleitoral ficará isolada em `etl_tse_eleitoral.py`. O módulo validará artefatos do TSE, normalizará chaves e produzirá três tabelas antes de expor um adaptador município-ano ao ETL existente. `etl_primario.py` receberá somente seleção da fonte, chamada do adaptador, gravação das saídas e merge por `codigo_ibge + ano`.

**Tech Stack:** Python 3.12, biblioteca padrão (`csv`, `dataclasses`, `datetime`, `hashlib`, `io`, `json`, `pathlib`, `tempfile`, `zipfile`, `zlib`), pandas 2.2+, requests 2.32+, unittest e unittest.mock.

**Spec:** `docs/superpowers/specs/2026-10-15-tse-eleitoral-design.md`

## Global Constraints

- Usar somente fontes oficiais para resultados, correspondência territorial e evidência de posse.
- Preservar `codigo_ibge` como texto de sete dígitos.
- Não introduzir dependência nova sem interromper e pedir orientação.
- Não expor dados pessoais desnecessários; `SQ_CANDIDATO` é identificador restrito à eleição.
- Não inferir vencedor por votação, posse pela data da eleição ou partido em cobertura pendente.
- Não produzir score, rótulo causal ou pontuação de risco eleitoral.
- Não transformar falha, pendência ou cobertura parcial em zero.
- Não alterar o significado ou remover colunas existentes de `base_municipio_ano.csv`.
- Não criar regra específica por município.
- Não executar `--refresh`, coleta estadual completa, commit ou push.
- Durante a implementação, substituir cada passo de commit normalmente previsto pelo skill por `git diff --check` e `git status --short`.
- Escrever testes antes do código de cada tarefa e observar a falha esperada antes da implementação mínima.
- Parar antes da integração se qualquer teste isolado do módulo falhar.
- Parar antes do smoke real e pedir autorização específica, mesmo que todas as suítes passem.

## File Structure

**Criar**

- `etl_tse_eleitoral.py`: contratos, coleta, checkpoints, normalização, eventos, mandatos, fotografia e orquestração da fonte.
- `tests/test_tse_eleitoral.py`: testes unitários isolados do módulo; ZIPs e DataFrames mínimos serão construídos em memória.
- `tests/test_tse_integracao.py`: testes do adaptador para `etl_primario.py`, CLI, merge, saídas e isolamento do smoke.
- `data/reference/tse_eleitoral/situacao_totalizacao.json`: mapa versionado do código oficial `CD_SIT_TOT_TURNO` por edição.
- `data/reference/tse_eleitoral/esquemas_tse.json`: mapa versionado de encoding, separador, aliases, campos obrigatórios e sentinelas por conjunto e edição.
- `data/reference/tse_eleitoral/evidencias_posse.csv`: referência versionada e curada manualmente, contendo somente evidências oficiais auditáveis de posse suplementar.

**Modificar somente depois do Checkpoint 5**

- `etl_primario.py`: importar adaptador, aceitar `tse_eleitoral`, salvar saídas e anexar a fotografia anual.
- `config.json`: adicionar parâmetros TSE sem acrescentar a fonte à lista padrão `fontes`.
- `catalogo_fontes.csv`: registrar a fonte TSE e os conjuntos oficiais usados.
- `catalogo_variaveis.csv`: documentar somente variáveis políticas efetivamente integradas.
- `README.md` ou `ENTREGA.md`: documentar comandos e limitações confirmados pelo comportamento implementado.

**Gerar apenas por execução autorizada**

- `data/raw/tse_eleitoral/**`
- `data/staging/tse_eleitoral/**`
- `output/eventos_eleitorais_tse.csv`
- `output/mandatos_municipais.csv`
- `output/municipio_ano_politico.csv`
- `output/qualidade_tse_eleitoral.csv`
- `output/manifesto_tse_eleitoral.json`

## Interfaces compartilhadas

Estas assinaturas devem permanecer estáveis entre as tarefas:

```python
class FalhaTSE(RuntimeError): ...

@dataclass(frozen=True)
class EspecificacaoArtefato:
    nome: str
    edicao: int
    url: str
    membro_zip: str
    sha256_oficial: str | None = None
    algoritmo_hash_oficial: str | None = None

@dataclass(frozen=True)
class ResultadoArtefato:
    caminho: Path
    metodo: str
    estado: str
    tamanho_comprimido: int
    tamanho_descomprimido: int
    crc32_zip: str
    sha256_local: str
    cache_reutilizado: bool

@dataclass
class ResultadoTSE:
    eventos: pd.DataFrame
    mandatos: pd.DataFrame
    municipio_ano: pd.DataFrame
    qualidade: pd.DataFrame
    manifesto: list[dict[str, Any]]

def coletar_membro_zip_tse(
    sessao: requests.Session,
    especificacao: EspecificacaoArtefato,
    destino: Path,
    config: dict[str, Any],
) -> ResultadoArtefato: ...

def validar_catalogo_tse_ibge(
    catalogo: pd.DataFrame,
    uf: str = "PB",
    quantidade_esperada: int = 223,
) -> pd.DataFrame: ...

def ler_csv_tse(
    caminho: Path,
    conjunto: str,
    edicao: int,
    mapa_esquemas: dict[str, Any],
) -> pd.DataFrame: ...

def ler_evidencias_posse(caminho: Path) -> pd.DataFrame: ...

def construir_eventos_eleitorais(
    candidaturas: pd.DataFrame,
    votos: pd.DataFrame,
    detalhes: pd.DataFrame,
    correspondencia: pd.DataFrame,
    suplementares: pd.DataFrame,
    mapa_situacao: dict[int, dict[str, str]],
) -> pd.DataFrame: ...

def construir_mandatos_municipais(
    eventos: pd.DataFrame,
    evidencias_posse: pd.DataFrame,
) -> pd.DataFrame: ...

def construir_municipio_ano_politico(
    catalogo: pd.DataFrame,
    eventos: pd.DataFrame,
    mandatos: pd.DataFrame,
    ano_inicial: int = 2020,
    ano_final: int = 2024,
) -> pd.DataFrame: ...

def executar_tse_eleitoral(
    sessao: requests.Session,
    config: dict[str, Any],
    raw_dir: Path,
    output_dir: Path,
) -> ResultadoTSE: ...

def adaptar_municipio_ano_para_base(municipio_ano: pd.DataFrame) -> pd.DataFrame: ...
```

## Review Focus

- Servidor responde `200` a um pedido Range ou devolve `Content-Range` incompatível: fazer fallback integral e nunca declarar o parcial completo; Task 2 testa ambos.
- ZIP muda entre requisições ou checkpoint tem `sha256_local` divergente: invalidar somente o artefato afetado e preservar os demais; Task 2 testa a invalidação.
- Código totalizador desconhecido ou conflitante com descrição: evento pendente, sem vencedor inferido; Task 3 testa os dois casos.
- Eleição suplementar tem data de eleição ou diplomação, mas não posse diária validada: preservar evento e não substituir mandato; Task 5 testa essa fronteira.
- Resultado do próprio ano aparece antes de `data_disponibilidade_adotada`: fotografia deve permanecer com o estado anterior; Task 6 testa 2020 e 2024.
- Duas candidaturas da mesma zona multiplicam aptos, comparecimento ou abstenções depois de um merge: agregar o detalhe eleitoral separadamente antes da junção; Task 4 fixa essa regressão.

---

### Task 1: Contratos, mapa oficial e correspondência territorial

**Files:**
- Create: `etl_tse_eleitoral.py`
- Create: `tests/test_tse_eleitoral.py`
- Create: `data/reference/tse_eleitoral/situacao_totalizacao.json`
- Create: `data/reference/tse_eleitoral/esquemas_tse.json`

**Interfaces:**
- Produces: `FalhaTSE`, constantes `CHAVE_CANDIDATURA_TURNO` e `CHAVE_EVENTO`, `carregar_mapa_situacao(caminho)`, `carregar_mapa_esquemas(caminho)`, `normalizar_codigo_municipio_tse(df, campo)`, `validar_catalogo_tse_ibge(...)`.
- Consumes: nenhuma interface nova.

- [ ] **Step 1: Escrever testes inicialmente falhando**

Adicionar `TestContratosTerritoriais` com:

```python
def test_chaves_candidatura_e_evento_sao_distintas(self):
    self.assertIn("SQ_CANDIDATO", tse.CHAVE_CANDIDATURA_TURNO)
    self.assertIn("NR_TURNO", tse.CHAVE_CANDIDATURA_TURNO)
    self.assertNotIn("SQ_CANDIDATO", tse.CHAVE_EVENTO)
    self.assertNotIn("NR_TURNO", tse.CHAVE_EVENTO)

def test_catalogo_pb_exige_223_codigos_unicos(self):
    catalogo = catalogo_sintetico_pb(223)
    validado = tse.validar_catalogo_tse_ibge(catalogo)
    self.assertEqual(len(validado), 223)
    with self.assertRaises(tse.FalhaTSE):
        tse.validar_catalogo_tse_ibge(catalogo.iloc[:-1])

def test_catalogo_rejeita_duplicidade_e_uf_divergente(self):
    ...

def test_normaliza_sg_ue_e_cd_municipio_sem_converter_em_numero(self):
    ...

def test_mapa_de_esquema_exige_todos_os_conjuntos_e_edicoes(self):
    ...
```

O fixture `catalogo_sintetico_pb` deve gerar 223 códigos distintos sem codificar nomes reais.

- [ ] **Step 2: Confirmar a falha**

Run:

```powershell
python -m unittest discover -s tests -p "test_tse_eleitoral.py" -v
```

Expected: `ERROR` por ausência de `etl_tse_eleitoral` ou das interfaces da Task 1.

- [ ] **Step 3: Implementar contratos mínimos e validação territorial**

Criar as constantes com as chaves aprovadas, preservar zeros à esquerda e fazer `validar_catalogo_tse_ibge` exigir 223 linhas PB, unicidade TSE/IBGE e códigos IBGE com sete dígitos. Criar o mapa de situação com entradas separadas para 2016, 2020 e 2024; o status vencedor será associado ao código oficial validado na edição e as descrições originais não serão descartadas.

Criar `esquemas_tse.json` com entradas para `consulta_cand`, `votacao_candidato_munzona`, `detalhe_votacao_munzona`, `municipio_tse_ibge` e `eleicoes_suplementares`. Cada conjunto/edição declarará `encoding`, `separador`, aliases do campo canônico para nomes oficiais aceitos, campos obrigatórios e sentinelas por campo. Um conjunto ou edição ausente deve provocar `FalhaTSE`, nunca reutilização silenciosa do esquema de outro ano.

- [ ] **Step 4: Rodar testes isolados e validações documentais**

Run:

```powershell
python -m unittest discover -s tests -p "test_tse_eleitoral.py" -v
python -m json.tool data/reference/tse_eleitoral/situacao_totalizacao.json > $null
python -m json.tool data/reference/tse_eleitoral/esquemas_tse.json > $null
git diff --check
git status --short
```

Expected: testes da Task 1 `OK`; os dois JSONs válidos; nenhum erro em `git diff --check`.

**Checkpoint 1:** mostrar diff das interfaces e resultados. Interromper se o mapa oficial não puder ser sustentado por edição ou se o catálogo oficial não oferecer ambos os códigos.

### Task 2: HTTP Range, fallback integral e checkpoints verificáveis

**Files:**
- Modify: `etl_tse_eleitoral.py`
- Modify: `tests/test_tse_eleitoral.py`

**Interfaces:**
- Consumes: `FalhaTSE`, `EspecificacaoArtefato`.
- Produces: `ResultadoArtefato`, `coletar_membro_zip_tse(...)`, `validar_checkpoint_artefato(caminho, metadados) -> bool`.

- [ ] **Step 1: Escrever testes inicialmente falhando**

Adicionar `TestArtefatosTSE` com ZIP mínimo criado em memória e respostas HTTP mockadas:

```python
def test_range_valido_confere_tamanho_crc_e_sha_local(self): ...
def test_range_ignorado_faz_fallback_para_zip_integral(self): ...
def test_content_range_inconsistente_faz_fallback_integral(self): ...
def test_crc_ou_tamanho_invalido_nunca_retorna_completa(self): ...
def test_hash_oficial_so_e_validado_quando_publicado(self): ...
def test_checkpoint_valido_e_reutilizado_sem_http(self): ...
def test_checkpoint_com_sha_local_divergente_e_recoletado(self): ...
def test_escrita_atomica_preserva_arquivo_anterior(self): ...
```

Asserções mínimas: `metodo` é `http_range` ou `zip_integral`; `estado == "completa"` somente depois das validações; `sha256_local` é calculado; temporários não sobrevivem a falha; cache válido produz zero chamadas HTTP.

- [ ] **Step 2: Confirmar a falha**

Run: `python -m unittest discover -s tests -p "test_tse_eleitoral.py" -v`

Expected: novos testes falham por ausência do coletor; testes da Task 1 continuam passando.

- [ ] **Step 3: Implementar obtenção resiliente**

Implementar leitor remoto seekable por intervalos ou localização explícita do diretório central, validar `206`, `Content-Range`, tamanho e identidade do objeto remoto entre requisições. O sidecar `<arquivo>.meta.json` conterá especificação, método, tamanhos, CRC, `sha256_local`, hash oficial, ETag e `Last-Modified`. Qualquer falha do caminho Range tenta uma vez o ZIP integral; falha do integral levanta `FalhaTSE` e registra estado incompleto.

- [ ] **Step 4: Rodar os testes e checks**

Run:

```powershell
python -m unittest discover -s tests -p "test_tse_eleitoral.py" -v
git diff --check
git status --short
```

Expected: Tasks 1–2 `OK`; nenhuma chamada de rede real.

**Checkpoint 2:** interromper se o CDN não permitir verificar tamanho e CRC do membro nem no ZIP integral, se o artefato mudar durante a leitura ou se a escrita atômica não puder preservar o arquivo anterior.

### Task 3: Normalização eleitoral, chaves, vencedor e disponibilidade

**Files:**
- Modify: `etl_tse_eleitoral.py`
- Modify: `tests/test_tse_eleitoral.py`

**Interfaces:**
- Consumes: chaves e mapa versionado da Task 1.
- Produces: `ler_csv_tse(...)`, `normalizar_candidaturas(df, edicao)`, `normalizar_votos(df, edicao)`, `normalizar_detalhes(df, edicao)`, `resolver_vencedor(grupo, mapa_edicao)`, `definir_disponibilidade(data_pleito, data_oficial) -> tuple[date, str, str]`.

- [ ] **Step 1: Escrever testes inicialmente falhando**

Adicionar `TestNormalizacaoEleitoral`:

```python
def test_eleicao_regular_e_suplementar_nao_se_misturam(self): ...
def test_sq_candidato_identifica_candidatura_mas_nao_evento(self): ...
def test_vencedor_usa_cd_sit_tot_turno_e_preserva_descricao(self): ...
def test_codigo_desconhecido_nao_infere_vencedor_por_votos(self): ...
def test_codigo_e_descricao_contraditorios_deixam_evento_pendente(self): ...
def test_disponibilidade_oficial_tem_precisao_dia(self): ...
def test_sem_data_historica_adota_primeiro_de_janeiro_seguinte(self): ...
def test_ler_csv_aplica_aliases_e_sentinelas_da_edicao(self): ...
def test_ler_csv_rejeita_campo_obrigatorio_ausente(self): ...
def test_ler_csv_rejeita_conjunto_ou_edicao_sem_esquema(self): ...
```

Asserções de fallback: pleito em `15/11/2020` sem data oficial produz `2021-01-01`, precisão `ano_regra_conservadora` e regra `primeiro_dia_ano_seguinte`.

- [ ] **Step 2: Confirmar a falha**

Run: `python -m unittest discover -s tests -p "test_tse_eleitoral.py" -v`

Expected: somente os novos testes falham.

- [ ] **Step 3: Implementar normalização mínima**

Implementar `ler_csv_tse` usando exclusivamente encoding, separador, aliases, campos obrigatórios e sentinelas declarados para aquele conjunto/edição em `esquemas_tse.json`, sempre com `dtype=str`. Tratar `#NULO#`, `#NULO`, `#NE`, `-1`, `-3` e `-4` como ausentes somente nos campos em que o mapa da edição assim determinar. Filtrar prefeito pelo código oficial de cargo, separar tipo por `CD_TIPO_ELEICAO` e preservar códigos e descrições originais.

- [ ] **Step 4: Verificar**

Run: `python -m unittest discover -s tests -p "test_tse_eleitoral.py" -v`

Expected: Tasks 1–3 `OK`.

**Checkpoint 3:** interromper se uma edição não trouxer `CD_SIT_TOT_TURNO`, se os códigos oficiais divergirem do mapa versionado ou se for necessária correspondência textual para distinguir eleição regular de extraordinária.

### Task 4: Eventos, votação decisiva e comparecimento

**Files:**
- Modify: `etl_tse_eleitoral.py`
- Modify: `tests/test_tse_eleitoral.py`

**Interfaces:**
- Consumes: normalizadores, chaves, vencedor e disponibilidade da Task 3; catálogo validado da Task 1.
- Produces: `construir_eventos_eleitorais(...)` e esquema estável de `eventos_eleitorais_tse.csv`.

- [ ] **Step 1: Escrever testes inicialmente falhando**

Adicionar `TestEventosEleitorais`:

```python
def test_soma_zonas_sem_somar_turnos(self): ...
def test_turno_decisivo_e_o_turno_do_vencedor_oficial(self): ...
def test_percentual_usa_validos_do_mesmo_evento_e_turno(self): ...
def test_candidatura_unica_tem_margem_ausente(self): ...
def test_comparecimento_valida_aptos_igual_comparecimento_mais_abstencao(self): ...
def test_divergencia_de_comparecimento_deixa_taxas_ausentes(self): ...
def test_totais_da_zona_nao_sao_multiplicados_por_candidaturas(self): ...
def test_registro_sem_correspondencia_ibge_e_rejeitado(self): ...
def test_evento_nao_expoe_dados_pessoais_nem_score(self): ...
```

- [ ] **Step 2: Confirmar a falha**

Run: `python -m unittest discover -s tests -p "test_tse_eleitoral.py" -v`

Expected: testes de eventos falham; Tasks 1–3 permanecem verdes.

- [ ] **Step 3: Implementar agregação de eventos**

Agrupar votos somente pela chave candidatura-turno; escolher o turno decisivo pelo vencedor oficial; então reduzir para `CHAVE_EVENTO`. Agregar aptos, comparecimento e abstenções do detalhe por zona e depois por evento, município, cargo e turno decisivo antes de qualquer junção com candidaturas. O teste deve usar pelo menos duas candidaturas na mesma zona e comprovar que cada total zonal entra uma única vez. Publicar estado e motivo de pendência sem zerar métricas inválidas. Manter regular e suplementar em linhas distintas.

- [ ] **Step 4: Verificar esquema e testes**

Run: `python -m unittest discover -s tests -p "test_tse_eleitoral.py" -v`

Expected: Tasks 1–4 `OK`; chave de evento única; nenhum campo pessoal fora da lista aprovada.

**Checkpoint 4:** interromper se votos, aptos ou situação totalizadora não puderem ser ligados pela chave oficial completa, ou se houver mais de um vencedor oficial para o mesmo evento sem explicação documental.

### Task 5: Mandatos regulares, suplementares e evidência de posse

**Files:**
- Modify: `etl_tse_eleitoral.py`
- Modify: `tests/test_tse_eleitoral.py`
- Create: `data/reference/tse_eleitoral/evidencias_posse.csv`

**Interfaces:**
- Consumes: eventos da Task 4.
- Produces: `ler_evidencias_posse(caminho)`, `classificar_fonte_posse(linha) -> int | None`, `validar_evidencia_posse(linha) -> dict[str, Any]`, `construir_mandatos_municipais(...)`.

- [ ] **Step 1: Escrever testes inicialmente falhando**

Adicionar `TestMandatosMunicipais`:

```python
def test_regular_e_suplementar_permanecem_eventos_distintos(self): ...
def test_suplementar_ciclo_2016_herda_ano_eleicao_origem(self): ...
def test_posse_dia_oficial_substitui_mandato_na_data_validada(self): ...
def test_eleicao_ou_diplomacao_nao_substitui_posse(self): ...
def test_posse_sem_dia_exato_permanece_pendente(self): ...
def test_fontes_oficiais_conflitantes_permanecem_pendentes(self): ...
def test_hierarquia_prefere_ato_formal_a_noticia_institucional(self): ...
def test_pendente_nao_atribui_partido_prefeito_no_pleito_origem(self): ...
def test_csv_evidencias_exige_origem_oficial_auditavel(self): ...
def test_csv_evidencias_rejeita_chave_duplicada_ou_url_nao_oficial(self): ...
```

Os níveis aceitos são 1: ato/termo/ata municipal; 2: ato processual TRE/TSE explícito; 3: diário oficial/judicial explícito; 4: notícia institucional oficial explícita. Somente precisão `dia_oficial` altera vigência.

O CSV de referência terá este contrato estável:

```text
id_evidencia
codigo_ibge
cd_eleicao
ano_eleicao_origem_ciclo
data_posse
precisao_data_posse
tipo_fonte_oficial
nivel_hierarquia_fonte
orgao_publicador
url_fonte_oficial
data_publicacao_fonte
titulo_documento
identificador_documento
data_verificacao_utc
status_validacao
observacao
```

`id_evidencia` será único e a chave eleitoral será `codigo_ibge + cd_eleicao + ano_eleicao_origem_ciclo`. Cada linha deverá apontar para uma origem oficial verificável e registrar quem publicou, URL, data de publicação quando disponível, data da verificação e status. A curadoria manual será versionada no repositório; ela não poderá conter regra de código para município específico. URL ausente ou sem órgão oficial identificado mantém `status_validacao=pendente` e não abre mandato.

- [ ] **Step 2: Confirmar a falha**

Run: `python -m unittest discover -s tests -p "test_tse_eleitoral.py" -v`

Expected: novos testes falham sem quebrar eventos.

- [ ] **Step 3: Implementar intervalos de mandato**

Implementar `ler_evidencias_posse` com `dtype=str`, validar o contrato, unicidade, hierarquia e rastreabilidade, e manter o registro original para auditoria. Criar mandato regular com origem no pleito validado e datas constitucionais do ciclo. Fechar e substituir o intervalo somente na data diária validada da posse suplementar. Preservar `origem_gestao`, `partido_prefeito_no_pleito_origem`, fonte, precisão e estado. Não incluir condição baseada em nome ou código de município específico.

- [ ] **Step 4: Verificar suíte isolada antes de integração**

Run:

```powershell
python -m unittest discover -s tests -p "test_tse_eleitoral.py" -v
python -m unittest discover -s tests -p 'test_*.py' -q
git diff --check
git status --short
```

Expected: suíte TSE isolada e suíte legada completas em `OK`.

**Checkpoint 5 — bloqueio obrigatório:** não modificar `etl_primario.py`, `config.json` ou catálogos enquanto qualquer teste das Tasks 1–5 falhar. Interromper se a data efetiva de posse depender de fonte não oficial ou inferência.

### Task 6: Fotografia em 1º de janeiro e junção temporal

**Files:**
- Modify: `etl_tse_eleitoral.py`
- Modify: `tests/test_tse_eleitoral.py`

**Interfaces:**
- Consumes: eventos e mandatos validados.
- Produces: `construir_municipio_ano_politico(...)` e `adaptar_municipio_ano_para_base(...)`.

- [ ] **Step 1: Escrever testes inicialmente falhando**

Adicionar `TestFotografiaPolitica`:

```python
def test_pb_2020_2024_tem_1115_chaves_unicas(self): ...
def test_fotografia_2020_usa_ciclo_2016(self): ...
def test_resultado_2020_nao_aparece_na_fotografia_2020(self): ...
def test_continuidade_2020_so_aparece_em_2021(self): ...
def test_resultado_2024_nao_altera_fotografia_2024(self): ...
def test_suplementar_validada_antes_do_corte_altera_fotografia(self): ...
def test_suplementar_pendente_nao_altera_fotografia(self): ...
def test_quatro_campos_temporais_nao_sao_fundidos(self): ...
def test_adaptador_cria_ano_sem_remover_ano_fotografia(self): ...
```

Asserções temporais: `numero_ano_ciclo_eleitoral == ano_fotografia - ano_eleicao_origem_ciclo`; `numero_ano_gestao_atual == ano_fotografia - ano(data_inicio_vigencia) + 1` somente com início diário validado.

- [ ] **Step 2: Confirmar a falha**

Run: `python -m unittest discover -s tests -p "test_tse_eleitoral.py" -v`

Expected: testes da fotografia falham; Tasks 1–5 continuam verdes.

- [ ] **Step 3: Implementar fotografia e adaptador**

Gerar esqueleto territorial 223 × 5; executar junção temporal com corte `YYYY-01-01T00:00:00`; exigir `data_disponibilidade_adotada <= corte` para resultados e continuidade. O adaptador conservará `ano_fotografia` e acrescentará `ano = ano_fotografia` para o merge legado.

- [ ] **Step 4: Verificar invariantes**

Run: `python -m unittest discover -s tests -p "test_tse_eleitoral.py" -v`

Expected: exatamente 1.115 linhas e chaves únicas; Tasks 1–6 `OK`.

**Checkpoint 6:** interromper se o catálogo não tiver exatamente 223 municípios ou se algum resultado posterior ao corte aparecer na fotografia.

### Task 7: Orquestração isolada, saídas, qualidade e manifesto

**Files:**
- Modify: `etl_tse_eleitoral.py`
- Modify: `tests/test_tse_eleitoral.py`

**Interfaces:**
- Consumes: todas as interfaces isoladas anteriores.
- Produces: `ResultadoTSE`, `executar_tse_eleitoral(...)`, `gravar_resultado_tse(resultado, output_dir)`.

- [ ] **Step 1: Escrever testes inicialmente falhando**

Adicionar `TestOrquestracaoTSE`:

```python
def test_execucao_grava_cinco_saidas_atomicas(self): ...
def test_manifesto_distingue_completa_parcial_falhou_e_cache(self): ...
def test_falha_de_edicao_nao_vira_zero_ou_ausencia_confirmada(self): ...
def test_qualidade_registra_cobertura_periodo_e_pendencias(self): ...
def test_resume_reutiliza_artefatos_sem_requisicao(self): ...
def test_smoke_configura_dois_municipios_e_edicoes_2016_2020(self): ...
```

Mockar `coletar_membro_zip_tse`; nenhum teste desta tarefa pode acessar a internet ou as pastas reais `data/` e `output/`.

- [ ] **Step 2: Confirmar a falha**

Run: `python -m unittest discover -s tests -p "test_tse_eleitoral.py" -v`

Expected: somente testes de orquestração falham.

- [ ] **Step 3: Implementar orquestração**

Declarar especificações oficiais para correspondência e edições 2016/2020/2024; coletar em sequência, sem paralelismo; produzir manifesto por artefato e etapa; gravar CSV com `utf-8-sig` e JSON UTF-8 por temporário mais `os.replace`. Em `_smoke_test`, limitar o catálogo a dois municípios e as edições a 2016/2020 sem alterar o arquivo de configuração.

- [ ] **Step 4: Executar gate isolado completo**

Run:

```powershell
python -m unittest discover -s tests -p "test_tse_eleitoral.py" -v
python -m unittest discover -s tests -p 'test_*.py' -q
git diff --check
git status --short
```

Expected: ambas as suítes `OK`; nenhuma requisição real; nenhuma alteração em `data/`, `output/` ou `config.json` causada pelos testes.

**Checkpoint 7 — autorização para integração:** apresentar resultados e lista de arquivos. Só iniciar Task 8 se a suíte isolada e a legada estiverem verdes.

### Task 8: Integração localizada no ETL principal

**Files:**
- Create: `tests/test_tse_integracao.py`
- Modify: `etl_primario.py:9-42,1237-1251,1259-1370`
- Modify: `config.json`
- Modify: `catalogo_fontes.csv`
- Modify: `catalogo_variaveis.csv`

**Interfaces:**
- Consumes: `executar_tse_eleitoral(...)`, `adaptar_municipio_ano_para_base(...)`, `ResultadoTSE`.
- Produces: fonte CLI `tse_eleitoral`, saídas TSE e colunas políticas em `base_municipio_ano.csv`.

- [ ] **Step 1: Escrever testes de integração inicialmente falhando**

Adicionar:

```python
def test_cli_aceita_tse_eleitoral_explicitamente(self): ...
def test_config_padrao_nao_seleciona_tse_eleitoral(self): ...
def test_integracao_chama_fonte_uma_vez_e_nao_por_municipio(self): ...
def test_merge_usa_codigo_ibge_e_ano_derivado_da_fotografia(self): ...
def test_merge_preserva_1115_linhas_e_colunas_existentes(self): ...
def test_catalogo_incompleto_bloqueia_integracao_antes_de_gravar(self): ...
def test_saidas_eventos_mandatos_fotografia_qualidade_e_manifesto(self): ...
def test_cobertura_fontes_inclui_tse_eleitoral(self): ...
def test_smoke_cli_nao_altera_config_nem_saida_producao(self): ...
def test_falha_tse_nao_interrompe_fontes_ja_coletadas_nem_cria_zero(self): ...
```

Mockar `etl_tse_eleitoral.executar_tse_eleitoral` com resultado pequeno para o CLI e resultado sintético de 1.115 linhas para o merge estadual.

- [ ] **Step 2: Confirmar a falha de integração**

Run: `python -m unittest discover -s tests -p "test_tse_integracao.py" -v`

Expected: falha porque `tse_eleitoral` ainda não é aceito no CLI nem chamado por `main`.

- [ ] **Step 3: Implementar adaptador mínimo em `etl_primario.py`**

Adicionar a opção às `choices`, inicializar resultado TSE vazio, chamar uma vez por execução, anexar somente o DataFrame adaptado às `bases`, salvar as cinco saídas específicas e incluir contagens no resumo. Estender `cobertura_fontes` para a nova fonte. Capturar `FalhaTSE` como erro controlado; não criar linhas políticas com zero.

- [ ] **Step 4: Adicionar configuração opt-in e catálogos**

Adicionar ao `config.json`, sem modificar a lista existente `fontes`:

```json
{
  "tse_eleitoral_uf": "PB",
  "tse_eleitoral_edicoes": [2016, 2020, 2024],
  "tse_eleitoral_ano_inicial": 2020,
  "tse_eleitoral_ano_final": 2024,
  "tse_eleitoral_timeout_segundos": 60,
  "tse_eleitoral_max_tentativas": 4
}
```

Registrar no catálogo somente URLs oficiais e documentar os quatro campos temporais, comparecimento, abstenção, margem, continuidade, origem e estados de validação.

- [ ] **Step 5: Verificar integração e regressões**

Run:

```powershell
python -m unittest discover -s tests -p "test_tse_integracao.py" -v
python -m unittest discover -s tests -p "test_tse_eleitoral.py" -v
python -m unittest discover -s tests -p 'test_*.py' -q
python -m json.tool config.json > $null
git diff --check
git status --short
```

Expected: todas as suítes `OK`; `fontes` padrão continua `ibge`, `siconfi`, `pncp`, `obrasgov`; nenhum acesso real à rede.

**Checkpoint 8:** interromper se integrar exigir mudar nomes ou formatos existentes, se o merge alterar a cardinalidade da base ou se a fonte for ativada implicitamente.

### Task 9: Documentação, verificação final e gate do smoke

**Files:**
- Modify: `README.md` ou `ENTREGA.md`
- Verify: todos os arquivos das Tasks 1–8

**Interfaces:**
- Consumes: comportamento final comprovado pelas suítes.
- Produces: instruções operacionais e relatório para autorização do smoke.

- [ ] **Step 1: Atualizar documentação somente com comportamento validado**

Documentar fonte opt-in, saídas, temporalidade, retomada, limites, hierarquia de posse e comandos:

```powershell
# Testes isolados
python -m unittest discover -s tests -p "test_tse_eleitoral.py" -v

# Integração mockada
python -m unittest discover -s tests -p "test_tse_integracao.py" -v

# Regressão completa
python -m unittest discover -s tests -p 'test_*.py' -q

# Smoke proposto — não executar sem autorização
python etl_primario.py --sources tse_eleitoral --resume --smoke-test

# Coleta estadual proposta — não executar sem autorização posterior ao smoke
python etl_primario.py --sources tse_eleitoral --resume
```

- [ ] **Step 2: Executar verificação final sem rede**

Run:

```powershell
python -m unittest discover -s tests -p "test_tse_eleitoral.py" -v
python -m unittest discover -s tests -p "test_tse_integracao.py" -v
python -m unittest discover -s tests -p 'test_*.py' -q
python -m json.tool config.json > $null
git diff --check
git status --short
```

Expected: todos os testes `OK`; JSON válido; somente arquivos previstos alterados; nenhum arquivo novo em `data/raw/tse_eleitoral` ou `output` decorrente da verificação mockada.

- [ ] **Step 3: Apresentar relatório e interromper antes do smoke**

Apresentar testes, contagens, arquivos, diff, estado do repositório e comando exato do smoke. Não executar o comando até nova autorização explícita.

**Checkpoint 9 — interrupção obrigatória:** aguardar autorização do usuário para o smoke real. Depois do smoke, apresentar manifesto, método Range/fallback, municípios/edições efetivos e qualquer pendência. A coleta estadual completa exigirá outra autorização explícita.

## Critérios gerais de interrupção

Interromper a implementação e pedir orientação se ocorrer qualquer uma destas condições:

1. alteração necessária no formato ou significado de saída existente;
2. necessidade de credencial, fonte não oficial ou nova dependência;
3. ausência de código TSE–IBGE oficial ou catálogo PB diferente de 223 vínculos válidos;
4. ausência ou ambiguidade do código oficial de vencedor por edição;
5. necessidade de inferir posse, vencedor, município ou partido;
6. inconsistência entre tamanho, CRC, hash oficial ou `sha256_local` que persista após fallback integral;
7. mistura inevitável de eleição regular, suplementar ou turnos;
8. cardinalidade diferente de 1.115 para PB 2020–2024;
9. vazamento de resultado posterior ao corte anual;
10. falha de qualquer teste isolado antes da integração;
11. falha da suíte completa antes do smoke;
12. tentativa de smoke fora de diretório isolado ou coleta além de dois municípios e edições 2016/2020;
13. necessidade de `--refresh`, remoção de cache ou alteração de dados existentes;
14. qualquer solicitação de commit ou push antes da revisão final do usuário.

## Handoff de execução

Este plano não autoriza implementação. O método futuro já escolhido é **Nativo**, usando `superpowers:executing-plans`, mas sua execução depende de autorização explícita posterior. O executor deve ler primeiro a especificação e este plano, usar TDD e respeitar todos os checkpoints de interrupção.
