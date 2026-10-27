"""Transferegov Transferências Especiais (emendas Pix): cadeia financeira da PB.

O filtro `eq.PB` é aplicado pela própria API; cada página preservada é a resposta
original dessa consulta. As tabelas sem UF são consultadas pelos identificadores
lidos das páginas já preservadas da tabela-mãe.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
import pandas as pd
from etl_confiabilidade import salvar_json_atomico
from ..core.armazenamento import preservar, sha256
from ..core.contratos import ViolacaoContrato, validar_numerica
from ..core.http import obter_json

FONTE = 'transferegov_especiais'
BASE_URL = 'https://api.transferegov.gestao.gov.br/transferenciasespeciais/'
LIMITE = 1000  # máximo de linhas por resposta observado na API
LOTE_IDS = 150
CONFIG = {'max_tentativas': 4, 'timeout_segundos': 120, 'intervalo_requisicoes_segundos': 0.2}
# (recurso, filtro direto, coluna de ordenação, (recurso-mãe, coluna de ligação))
CADEIA = (
    ('plano_acao_especial', {'uf_beneficiario_plano_acao': 'eq.PB'}, 'id_plano_acao', None),
    ('empenho_especial', {'uf_beneficiario_empenho': 'eq.PB'}, 'id_empenho', None),
    ('documento_habil_especial', None, 'id_dh', ('empenho_especial', 'id_empenho')),
    ('ordem_pagamento_ordem_bancaria_especial', None, 'id_op_ob', ('documento_habil_especial', 'id_dh')),
)


def _indice(raiz: Path) -> Path:
    return raiz / 'ref' / f'{FONTE}_bronze.json'


def _chave(recurso, params):
    return f'{recurso}?{urlencode(sorted(params.items()))}'


def _ler(raiz, registro):
    caminho = raiz / registro['arquivo']
    if not caminho.exists() or sha256(caminho.read_bytes()) != caminho.parent.name:
        raise ViolacaoContrato(f'Bronze {FONTE} corrompido: {caminho}; investigar antes de --refresh')
    return caminho, json.loads(caminho.read_bytes())


def _paginas(sessao, raiz, estado, indice, recurso, filtro, ordem, estado_http):
    linhas, offset = [], 0
    while True:
        params = {**filtro, 'order': ordem, 'offset': offset, 'limit': LIMITE}
        chave = _chave(recurso, params)
        if chave in estado['paginas']:
            _, dados = _ler(raiz, estado['paginas'][chave])
        else:
            dados, conteudo = obter_json(sessao, BASE_URL + recurso, CONFIG, params=params,
                                         fonte='TRANSFEREGOV', contexto=chave,
                                         estado=estado_http)
            if not isinstance(dados, list) or len(dados) > LIMITE:
                raise ViolacaoContrato(f'Resposta inesperada em {chave}')
            nome = f'{recurso}_{sha256(chave.encode())[:16]}.json'
            caminho = preservar(raiz, FONTE, nome, conteudo, BASE_URL + recurso + '?' + urlencode(params))
            estado['paginas'][chave] = {'recurso': recurso, 'params': params, 'linhas': len(dados),
                                        'arquivo': caminho.relative_to(raiz).as_posix()}
            salvar_json_atomico(indice, estado)
        linhas += dados
        if len(dados) < LIMITE:
            return linhas
        offset += LIMITE


def extrair(sessao, raiz: Path, *, refresh=False):
    """Retoma pela última página preservada; `refresh` inicia nova extração sem apagar a anterior."""
    indice = _indice(raiz)
    estado = json.loads(indice.read_text(encoding='utf-8')) if indice.exists() else None
    if estado and refresh:
        historico = raiz / 'ref' / 'historico' / f"{FONTE}_bronze_{estado['iniciado_em_utc'].replace(':', '')}.json"
        salvar_json_atomico(historico, estado)
        estado = None
    if estado and estado['completo']:
        return verificar(raiz)
    estado = estado or {'iniciado_em_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                        'completo': False, 'paginas': {}}
    lidos, estado_http = {}, {}
    for recurso, filtro, ordem, mae in CADEIA:
        if mae is None:
            lidos[recurso] = _paginas(sessao, raiz, estado, indice, recurso, filtro, ordem, estado_http)
            continue
        origem, coluna = mae
        ids = sorted({linha[coluna] for linha in lidos[origem]})
        lidos[recurso] = []
        for i in range(0, len(ids), LOTE_IDS):
            filtro_lote = {coluna: f"in.({','.join(map(str, ids[i:i + LOTE_IDS]))})"}
            lidos[recurso] += _paginas(sessao, raiz, estado, indice, recurso, filtro_lote, ordem, estado_http)
    estado['completo'] = True
    estado['concluido_em_utc'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    estado['linhas'] = {recurso: len(linhas) for recurso, linhas in lidos.items()}
    salvar_json_atomico(indice, estado)
    return verificar(raiz)


def verificar(raiz: Path) -> dict:
    """Páginas da última extração completa, conferidas pelo hash, sem rede."""
    indice = _indice(raiz)
    if not indice.exists():
        raise ViolacaoContrato(f'Sem Bronze {FONTE}; execute sem --offline')
    estado = json.loads(indice.read_text(encoding='utf-8'))
    if not estado['completo']:
        raise ViolacaoContrato(f'Bronze {FONTE} incompleto; execute sem --offline para retomar')
    caminhos = {recurso: [] for recurso, *_ in CADEIA}
    for registro in estado['paginas'].values():
        caminhos[registro['recurso']].append(_ler(raiz, registro)[0])
    return caminhos


# --- Silver -------------------------------------------------------------------
def _registros(caminhos, recurso):
    linhas = [linha for p in sorted(caminhos[recurso]) for linha in json.loads(p.read_bytes())]
    return pd.DataFrame(linhas)


def transformar(caminhos, mapa_cnpj):
    """Cadeia financeira dos municípios da PB; o CNPJ é ligado ao IBGE pelas propostas oficiais.

    Beneficiário fora do mapa municipal só é aceito quando é o próprio Estado.
    """
    mapa = dict(zip(mapa_cnpj.cnpj, mapa_cnpj.codigo_ibge))
    planos = _registros(caminhos, 'plano_acao_especial')
    if planos.id_plano_acao.duplicated().any():
        raise ViolacaoContrato('id_plano_acao duplicado')
    planos['codigo_ibge'] = planos.cnpj_beneficiario_plano_acao.map(mapa)
    sem_municipio = planos[planos.codigo_ibge.isna()]
    if not sem_municipio.nome_beneficiario_plano_acao.str.contains('ESTADO', case=False).all():
        raise ViolacaoContrato('Beneficiário municipal sem CNPJ correspondente nas propostas oficiais')
    planos = planos[planos.codigo_ibge.notna()]
    planos_silver = pd.DataFrame({
        'id_plano_acao': planos.id_plano_acao.astype('int64'), 'codigo_plano_acao': planos.codigo_plano_acao,
        'ano_plano_acao': planos.ano_plano_acao.astype('int64'), 'codigo_ibge': planos.codigo_ibge,
        'cnpj_beneficiario': planos.cnpj_beneficiario_plano_acao, 'situacao': planos.situacao_plano_acao,
        'parlamentar': planos.nome_parlamentar_emenda_plano_acao,
        'numero_emenda': planos.numero_emenda_parlamentar_plano_acao,
        'area_politica_publica': planos.codigo_descricao_areas_politicas_publicas_plano_acao,
        'motivo_impedimento': planos.motivo_impedimento_plano_acao,
        'valor_custeio': pd.to_numeric(planos.valor_custeio_plano_acao),
        'valor_investimento': pd.to_numeric(planos.valor_investimento_plano_acao)})

    empenhos = _registros(caminhos, 'empenho_especial')
    empenhos = empenhos[empenhos.id_plano_acao.isin(planos_silver.id_plano_acao)]
    if empenhos.id_empenho.duplicated().any():
        raise ViolacaoContrato('id_empenho duplicado')
    plano_municipio = dict(zip(planos_silver.id_plano_acao, planos_silver.codigo_ibge))
    empenhos_silver = pd.DataFrame({
        'id_empenho': empenhos.id_empenho.astype('int64'), 'id_plano_acao': empenhos.id_plano_acao.astype('int64'),
        'codigo_ibge': empenhos.id_plano_acao.map(plano_municipio), 'numero_empenho': empenhos.numero_empenho,
        'situacao_empenho': empenhos.situacao_empenho.astype('int64'),
        'data_emissao_empenho': pd.to_datetime(empenhos.data_emissao_empenho, format='%Y-%m-%d'),
        'valor_empenho': pd.to_numeric(empenhos.valor_empenho)})

    documentos = _registros(caminhos, 'documento_habil_especial')
    ordens = _registros(caminhos, 'ordem_pagamento_ordem_bancaria_especial')
    if documentos.id_dh.duplicated().any() or ordens.id_op_ob.duplicated().any() or ordens.id_dh.duplicated().any():
        raise ViolacaoContrato('Documento hábil ou ordem bancária duplicados')
    # Pagamento = documento hábil com ordem bancária emitida; documento sem ordem ainda não é pagamento.
    pagos = ordens.merge(documentos, on='id_dh', validate='one_to_one').merge(
        empenhos_silver[['id_empenho', 'id_plano_acao', 'codigo_ibge']], on='id_empenho', validate='many_to_one')
    pagamentos = pd.DataFrame({
        'id_op_ob': pagos.id_op_ob.astype('int64'), 'id_dh': pagos.id_dh.astype('int64'),
        'id_empenho': pagos.id_empenho.astype('int64'), 'id_plano_acao': pagos.id_plano_acao.astype('int64'),
        'codigo_ibge': pagos.codigo_ibge, 'situacao_op': pagos.situacao_op.astype('int64'),
        'data_emissao_ob': pd.to_datetime(pagos.data_emissao_ob, format='%Y-%m-%d'),
        'valor_pago': pd.to_numeric(pagos.valor_dh)})
    for quadro, colunas in [(planos_silver, ['valor_custeio', 'valor_investimento']),
                            (empenhos_silver, ['valor_empenho']), (pagamentos, ['valor_pago'])]:
        for coluna in colunas:
            validar_numerica(quadro, coluna)
    return {
        'silver/transferegov_especiais_planos': planos_silver.sort_values('id_plano_acao').reset_index(drop=True),
        'silver/transferegov_especiais_empenhos': empenhos_silver.sort_values('id_empenho').reset_index(drop=True),
        'silver/transferegov_especiais_pagamentos': pagamentos.sort_values('id_op_ob').reset_index(drop=True),
    }


TEMPORALIDADE = {
    'transferegov_especiais_planos': ('apta_data_do_evento', 'contagem pelo ano do plano de ação'),
    'transferegov_especiais_valor_planejado': (
        'somente_descritiva', 'valores do plano na data da extração, podem ter sido ajustados depois'),
    'transferegov_especiais_valor_pago': ('apta_data_do_evento', 'soma pela data da ordem bancária'),
}


def painel(silver, codigos, anos):
    """Município × ano: planos pelo ano do plano; pagamentos pela data da ordem bancária."""
    planos, pagamentos = silver['silver/transferegov_especiais_planos'], silver['silver/transferegov_especiais_pagamentos']
    chaves = pd.MultiIndex.from_product([sorted(codigos), anos], names=['codigo_ibge', 'ano'])
    planejado = planos.assign(ano=planos.ano_plano_acao, valor=planos.valor_custeio + planos.valor_investimento) \
        .groupby(['codigo_ibge', 'ano']).agg(transferegov_especiais_planos=('id_plano_acao', 'size'),
                                             transferegov_especiais_valor_planejado=('valor', 'sum'))
    pago = pagamentos.assign(ano=pagamentos.data_emissao_ob.dt.year).groupby(['codigo_ibge', 'ano']).agg(
        transferegov_especiais_valor_pago=('valor_pago', 'sum'))
    quadro = pd.concat([planejado, pago], axis=1).reindex(chaves).fillna(0)
    quadro['transferegov_especiais_planos'] = quadro.transferegov_especiais_planos.astype('int64')
    for coluna in TEMPORALIDADE:
        validar_numerica(quadro, coluna, nulos=False)
    quadro['cobertura_transferegov_especiais'] = 'completa'
    return quadro.reset_index()
