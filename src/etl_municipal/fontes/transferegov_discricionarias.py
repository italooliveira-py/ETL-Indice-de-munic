"""Transferegov Discricionárias e Legais: recorte PB dos CSV nacionais no Bronze.

O repositório oficial publica somente a carga mais recente e não oferece filtro
municipal. Por decisão registrada na ADR 0002, o Bronze guarda o recorte PB de
cada tabela, e não o zip nacional; o índice registra SHA-256, tamanho e linhas
do arquivo de origem e o critério aplicado.
"""
import gzip
import io
import json
import zipfile
from pathlib import Path
import pandas as pd
from etl_confiabilidade import salvar_json_atomico
from ..core.armazenamento import preservar, sha256
from ..core.contratos import ViolacaoContrato, validar_numerica
from ..core.http import obter_bytes

FONTE = 'transferegov_discricionarias'
BASE_URL = 'https://repositorio.dados.gov.br/seges/detru/'
DATA_CARGA = 'data_carga_siconv.csv.zip'
VERSAO_INDICE = 2
# (arquivo oficial, arquivo no Bronze, coluna filtrada, origem dos valores aceitos)
# A proposta define a PB; as demais tabelas ligam-se a ela pelos identificadores.
RECORTES = (
    ('siconv_proposta.csv.zip', 'siconv_proposta_pb.csv.gz', 'UF_PROPONENTE', None),
    ('siconv_convenio.csv.zip', 'siconv_convenio_pb.csv.gz', 'ID_PROPOSTA', ('siconv_proposta_pb.csv.gz', 'ID_PROPOSTA')),
    ('siconv_emenda.csv.zip', 'siconv_emenda_pb.csv.gz', 'ID_PROPOSTA', ('siconv_proposta_pb.csv.gz', 'ID_PROPOSTA')),
    ('siconv_desembolso.csv.zip', 'siconv_desembolso_pb.csv.gz', 'NR_CONVENIO', ('siconv_convenio_pb.csv.gz', 'NR_CONVENIO')),
)
TABELAS = tuple(saida for _, saida, _, _ in RECORTES)
CONFIG = {'max_tentativas': 4, 'timeout_segundos': 600, 'backoff_base_segundos': 5}


def _indice(raiz: Path) -> Path:
    return raiz / 'ref' / f'{FONTE}_bronze.json'


def ler_data_carga(conteudo: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(conteudo)) as arquivo:
        membros = arquivo.namelist()
        if len(membros) != 1:
            raise ViolacaoContrato('data_carga deve conter um único CSV')
        linhas = arquivo.read(membros[0]).decode('utf-8-sig').split()
    if len(linhas) < 3 or linhas[0] != 'data_carga':
        raise ViolacaoContrato('Leiaute inesperado em data_carga')
    return ' '.join(linhas[1:3])


def _ler_zip_csv(conteudo: bytes, colunas=None):
    with zipfile.ZipFile(io.BytesIO(conteudo)) as arquivo:
        membros = arquivo.namelist()
        if len(membros) != 1:
            raise ViolacaoContrato('Arquivo oficial deve conter um único CSV')
        with arquivo.open(membros[0]) as csv:
            return pd.read_csv(csv, sep=';', dtype=str, encoding='utf-8', usecols=colunas, keep_default_na=False)


def ler_recorte(caminho: Path, colunas=None):
    """CSV do Bronze com textos exatamente como publicados; vazio vira ausente, nunca zero."""
    quadro = pd.read_csv(caminho, sep=';', dtype=str, encoding='utf-8', usecols=colunas,
                         keep_default_na=False, compression='gzip')
    return quadro.replace('', pd.NA)


def recortar(conteudo: bytes, coluna: str, aceitos: set):
    """Mantém colunas e textos originais; gzip sem data no cabeçalho para bytes determinísticos."""
    quadro = _ler_zip_csv(conteudo)
    if coluna not in quadro:
        raise ViolacaoContrato(f'Coluna de recorte ausente: {coluna}')
    recorte = quadro[quadro[coluna].isin(aceitos)]
    texto = recorte.to_csv(sep=';', index=False, lineterminator='\n').encode('utf-8')
    return gzip.compress(texto, mtime=0), len(quadro), len(recorte)


def _verificados(raiz: Path, geracao: dict) -> dict | None:
    caminhos = {nome: raiz / rel for nome, rel in geracao['arquivos'].items()}
    if set(caminhos) != {DATA_CARGA, *TABELAS}:
        return None
    for p in caminhos.values():
        if not p.exists() or sha256(p.read_bytes()) != p.parent.name:
            raise ViolacaoContrato(f'Bronze {FONTE} corrompido: {p}; investigar antes de --refresh')
    return caminhos


def _estado(raiz: Path):
    indice = _indice(raiz)
    novo = {'versao_indice': VERSAO_INDICE, 'recorte': 'UF_PROPONENTE = PB', 'atual': None, 'cargas': {}}
    if not indice.exists():
        return novo
    estado = json.loads(indice.read_text(encoding='utf-8'))
    if estado.get('versao_indice') != VERSAO_INDICE:
        # Índice dos zips nacionais (versão 1): arquivado, os bytes continuam no Bronze.
        salvar_json_atomico(raiz / 'ref' / 'historico' / f'{FONTE}_bronze_v1.json', estado)
        return novo
    return estado


def verificar(raiz: Path) -> dict:
    """Carga mais recente já completa no Bronze, sem rede."""
    if not _indice(raiz).exists():
        raise ViolacaoContrato(f'Sem Bronze {FONTE}; execute sem --offline')
    estado = json.loads(_indice(raiz).read_text(encoding='utf-8'))
    caminhos = None
    if estado.get('versao_indice') == VERSAO_INDICE and estado.get('atual'):
        caminhos = _verificados(raiz, estado['cargas'][estado['atual']])
    if caminhos is None:
        raise ViolacaoContrato(f'Bronze {FONTE} incompleto ou sem recorte PB; execute sem --offline')
    return caminhos


def extrair(sessao, raiz: Path, *, refresh=False):
    """Uma geração por `data_carga`; cada tabela é baixada, recortada e somente o recorte é preservado."""
    indice = _indice(raiz)
    estado = _estado(raiz)
    conteudo = obter_bytes(sessao, BASE_URL + DATA_CARGA, CONFIG)
    data_carga = ler_data_carga(conteudo)
    geracao = estado['cargas'].setdefault(data_carga, {'data_carga': data_carga, 'arquivos': {}, 'origem': {}})
    if not refresh and (caminhos := _verificados(raiz, geracao)) is not None:
        return caminhos
    marcador = preservar(raiz, FONTE, DATA_CARGA, conteudo, BASE_URL + DATA_CARGA)
    geracao['arquivos'][DATA_CARGA] = marcador.relative_to(raiz).as_posix()
    for oficial, saida, coluna, chave in RECORTES:
        anterior = geracao['arquivos'].get(saida)
        if anterior and not refresh and (raiz / anterior).exists():
            continue
        aceitos = {'PB'} if chave is None else set(ler_recorte(raiz / geracao['arquivos'][chave[0]], [chave[1]])[chave[1]].dropna())
        original = obter_bytes(sessao, BASE_URL + oficial, CONFIG)
        conteudo_pb, linhas, linhas_pb = recortar(original, coluna, aceitos)
        criterio = f'{coluna} = PB' if chave is None else f'{coluna} em {chave[0]}.{chave[1]}'
        destino = preservar(raiz, FONTE, saida, conteudo_pb, f'recorte_pb:{BASE_URL + oficial}')
        geracao['arquivos'][saida] = destino.relative_to(raiz).as_posix()
        geracao['origem'][saida] = {'url': BASE_URL + oficial, 'sha256_original': sha256(original),
                                    'tamanho_original_bytes': len(original), 'linhas_originais': linhas,
                                    'linhas_recorte': linhas_pb, 'criterio': criterio}
        salvar_json_atomico(indice, estado)
    # A carga publicada pode mudar durante um download longo: só aceita se a data continuar a mesma.
    if ler_data_carga(obter_bytes(sessao, BASE_URL + DATA_CARGA, CONFIG)) != data_carga:
        # Recortes de cargas diferentes não formam uma geração; os bytes seguem no Bronze, sem índice.
        estado['cargas'].pop(data_carga)
        salvar_json_atomico(indice, estado)
        raise ViolacaoContrato('data_carga mudou durante a extração; repetir a extração')
    estado['atual'] = data_carga
    salvar_json_atomico(indice, estado)
    return _verificados(raiz, geracao)


# --- Silver -------------------------------------------------------------------
NATUREZA_MUNICIPAL = 'Administração Pública Municipal'
COLUNAS_PROPOSTA = ['ID_PROPOSTA', 'UF_PROPONENTE', 'COD_MUNIC_IBGE', 'NATUREZA_JURIDICA', 'IDENTIF_PROPONENTE',
                    'NM_PROPONENTE', 'MODALIDADE', 'DESC_ORGAO_SUP', 'DESC_ORGAO', 'DIA_PROPOSTA']
DATAS_CONVENIO = {'DIA_ASSIN_CONV': 'data_assinatura', 'DIA_PUBL_CONV': 'data_publicacao',
                  'DIA_INIC_VIGENC_CONV': 'data_inicio_vigencia', 'DIA_FIM_VIGENC_CONV': 'data_fim_vigencia',
                  'DIA_FIM_VIGENC_ORIGINAL_CONV': 'data_fim_vigencia_original'}
VALORES_CONVENIO = {'VL_GLOBAL_CONV': 'valor_global', 'VALOR_GLOBAL_ORIGINAL_CONV': 'valor_global_original',
                    'VL_REPASSE_CONV': 'valor_repasse', 'VL_CONTRAPARTIDA_CONV': 'valor_contrapartida',
                    'VL_EMPENHADO_CONV': 'valor_empenhado', 'VL_DESEMBOLSADO_CONV': 'valor_desembolsado'}


def _numero(serie, nome):
    # Publicação oficial: vírgula decimal, sem separador de milhar.
    valores = pd.to_numeric(serie.str.replace(',', '.', regex=False), errors='coerce')
    if (serie.notna() & valores.isna()).any():
        raise ViolacaoContrato(f'{nome}: número fora do padrão oficial')
    return valores


def _reais(serie, nome):
    # Centavos: a origem publica resíduos de ponto flutuante (ex.: -7,45e-09 em empenho zerado).
    return _numero(serie, nome).round(2) + 0.0


def _data(serie, nome):
    datas = pd.to_datetime(serie, format='%d/%m/%Y', errors='coerce')
    if (serie.notna() & datas.isna()).any():
        raise ViolacaoContrato(f'{nome}: data fora do padrão dd/mm/aaaa')
    return datas


def transformar(caminhos):
    """Propostas de administração municipal da PB; instrumentos assinados e seus desembolsos.

    Situação, vigência atual e valores do convênio são a fotografia da `data_carga`,
    não o estado em cada ano; datas de assinatura e desembolso são do próprio evento.
    """
    data_carga = ler_data_carga(caminhos[DATA_CARGA].read_bytes())
    proposta = ler_recorte(caminhos['siconv_proposta_pb.csv.gz'], COLUNAS_PROPOSTA)
    proposta = proposta[(proposta.UF_PROPONENTE == 'PB') & (proposta.NATUREZA_JURIDICA == NATUREZA_MUNICIPAL)]
    if proposta.COD_MUNIC_IBGE.isna().any() or not proposta.COD_MUNIC_IBGE.str.fullmatch(r'25\d{5}').all():
        raise ViolacaoContrato('Proposta municipal da PB sem código IBGE válido')
    if proposta.ID_PROPOSTA.duplicated().any():
        raise ViolacaoContrato('ID_PROPOSTA duplicado')
    mapa = proposta[['IDENTIF_PROPONENTE', 'COD_MUNIC_IBGE', 'NM_PROPONENTE']].drop_duplicates(['IDENTIF_PROPONENTE', 'COD_MUNIC_IBGE'])
    if mapa.IDENTIF_PROPONENTE.duplicated().any():
        raise ViolacaoContrato('CNPJ proponente associado a mais de um município')
    mapa = mapa.rename(columns={'IDENTIF_PROPONENTE': 'cnpj', 'COD_MUNIC_IBGE': 'codigo_ibge', 'NM_PROPONENTE': 'nome_proponente'})

    convenio = ler_recorte(caminhos['siconv_convenio_pb.csv.gz'],
                           ['NR_CONVENIO', 'ID_PROPOSTA', 'SIT_CONVENIO', 'SUBSITUACAO_CONV', 'INSTRUMENTO_ATIVO',
                            'IND_ASSINADO', 'QTD_TA', 'QTD_PRORROGA', *DATAS_CONVENIO, *VALORES_CONVENIO])
    # Pré-convênios (IND_ASSINADO = NÃO) não são instrumentos celebrados.
    convenio = convenio[convenio.IND_ASSINADO == 'SIM'].merge(proposta, on='ID_PROPOSTA', validate='many_to_one')
    if convenio.NR_CONVENIO.duplicated().any():
        raise ViolacaoContrato('NR_CONVENIO duplicado entre instrumentos assinados')
    instrumentos = pd.DataFrame({
        'nr_convenio': convenio.NR_CONVENIO, 'id_proposta': convenio.ID_PROPOSTA,
        'codigo_ibge': convenio.COD_MUNIC_IBGE, 'cnpj_proponente': convenio.IDENTIF_PROPONENTE,
        'nome_proponente': convenio.NM_PROPONENTE, 'modalidade': convenio.MODALIDADE,
        'orgao_superior': convenio.DESC_ORGAO_SUP, 'orgao': convenio.DESC_ORGAO,
        'data_proposta': _data(convenio.DIA_PROPOSTA, 'DIA_PROPOSTA'),
        **{novo: _data(convenio[antigo], antigo) for antigo, novo in DATAS_CONVENIO.items()},
        'situacao': convenio.SIT_CONVENIO, 'subsituacao': convenio.SUBSITUACAO_CONV,
        'instrumento_ativo': convenio.INSTRUMENTO_ATIVO.map({'SIM': True, 'NÃO': False}).astype('boolean'),
        **{novo: _reais(convenio[antigo], antigo) for antigo, novo in VALORES_CONVENIO.items()},
        'qtd_termos_aditivos': _numero(convenio.QTD_TA, 'QTD_TA').astype('Int64'),
        'qtd_prorrogacoes': _numero(convenio.QTD_PRORROGA, 'QTD_PRORROGA').astype('Int64'),
    })
    if instrumentos.data_assinatura.isna().any():
        raise ViolacaoContrato('Instrumento assinado sem data de assinatura')

    emenda = ler_recorte(caminhos['siconv_emenda_pb.csv.gz'], ['ID_PROPOSTA', 'TIPO_PARLAMENTAR', 'IND_IMPOSITIVO'])
    emenda = emenda[emenda.ID_PROPOSTA.isin(instrumentos.id_proposta)]
    # A tabela de emendas repete proposta × emenda por programa: só indicadores, nunca soma de valores.
    indicadores = emenda.assign(individual=emenda.TIPO_PARLAMENTAR == 'INDIVIDUAL',
                                impositiva=emenda.IND_IMPOSITIVO == 'SIM').groupby('ID_PROPOSTA')[['individual', 'impositiva']].any()
    instrumentos['origem_emenda'] = instrumentos.id_proposta.isin(indicadores.index)
    instrumentos['emenda_individual'] = instrumentos.id_proposta.map(indicadores.individual).fillna(False).astype(bool)
    instrumentos['emenda_impositiva'] = instrumentos.id_proposta.map(indicadores.impositiva).fillna(False).astype(bool)
    instrumentos['data_carga'] = data_carga

    desembolso = ler_recorte(caminhos['siconv_desembolso_pb.csv.gz'], ['ID_DESEMBOLSO', 'NR_CONVENIO', 'DATA_DESEMBOLSO', 'VL_DESEMBOLSADO'])
    desembolso = desembolso.merge(instrumentos[['nr_convenio', 'codigo_ibge']], left_on='NR_CONVENIO',
                                  right_on='nr_convenio', validate='many_to_one')
    desembolsos = pd.DataFrame({
        'id_desembolso': desembolso.ID_DESEMBOLSO, 'nr_convenio': desembolso.nr_convenio,
        'codigo_ibge': desembolso.codigo_ibge,
        'data_desembolso': _data(desembolso.DATA_DESEMBOLSO, 'DATA_DESEMBOLSO'),
        'valor_desembolsado': _reais(desembolso.VL_DESEMBOLSADO, 'VL_DESEMBOLSADO')})
    if desembolsos.id_desembolso.duplicated().any() or desembolsos.data_desembolso.isna().any():
        raise ViolacaoContrato('Desembolso duplicado ou sem data')
    for quadro, colunas in [(instrumentos, list(VALORES_CONVENIO.values())), (desembolsos, ['valor_desembolsado'])]:
        for coluna in colunas:
            validar_numerica(quadro, coluna)
    return {
        'silver/transferegov_instrumentos': instrumentos.sort_values('nr_convenio').reset_index(drop=True),
        'silver/transferegov_desembolsos': desembolsos.sort_values('id_desembolso').reset_index(drop=True),
        'ref/transferegov_cnpj_municipio': mapa.sort_values('cnpj').reset_index(drop=True),
    }


def painel(silver, codigos, anos):
    """Município × ano pela data do evento; sem registro no recorte completo da PB é zero confirmado."""
    instrumentos, desembolsos = silver['silver/transferegov_instrumentos'], silver['silver/transferegov_desembolsos']
    chaves = pd.MultiIndex.from_product([sorted(codigos), anos], names=['codigo_ibge', 'ano'])
    assinados = instrumentos.assign(ano=instrumentos.data_assinatura.dt.year).groupby(['codigo_ibge', 'ano']).agg(
        transferegov_instrumentos_assinados=('nr_convenio', 'size'),
        transferegov_valor_repasse_assinado=('valor_repasse', 'sum'))
    liberado = desembolsos.assign(ano=desembolsos.data_desembolso.dt.year).groupby(['codigo_ibge', 'ano']).agg(
        transferegov_valor_desembolsado=('valor_desembolsado', 'sum'))
    validos = instrumentos[instrumentos.situacao != 'Convênio Anulado']
    vigentes = pd.concat([
        validos[(validos.data_inicio_vigencia <= pd.Timestamp(ano, 12, 31)) & (validos.data_fim_vigencia >= pd.Timestamp(ano, 1, 1))]
        .groupby('codigo_ibge').size().rename('transferegov_instrumentos_vigentes').reset_index().assign(ano=ano)
        for ano in anos]).set_index(['codigo_ibge', 'ano'])
    quadro = pd.concat([assinados, liberado, vigentes], axis=1).reindex(chaves).fillna(0)
    for coluna in ['transferegov_instrumentos_assinados', 'transferegov_instrumentos_vigentes']:
        quadro[coluna] = quadro[coluna].astype('int64')
    quadro['cobertura_transferegov_discricionarias'] = 'completa'
    return quadro.reset_index()
