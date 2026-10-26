"""Transferegov Transferências Especiais (emendas Pix): cadeia financeira da PB.

O filtro `eq.PB` é aplicado pela própria API; cada página preservada é a resposta
original dessa consulta. As tabelas sem UF são consultadas pelos identificadores
lidos das páginas já preservadas da tabela-mãe.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from etl_confiabilidade import salvar_json_atomico
from ..core.armazenamento import preservar, sha256
from ..core.contratos import ViolacaoContrato
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
