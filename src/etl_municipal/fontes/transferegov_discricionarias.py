"""Transferegov Discricionárias e Legais: CSV nacionais preservados como publicados.

O repositório oficial publica somente a carga mais recente e não oferece filtro
municipal. O recorte da PB acontece no Silver; o Bronze guarda os zips inteiros
para que o recorte possa ser conferido e refeito.
"""
import io
import json
import zipfile
from pathlib import Path
from etl_confiabilidade import salvar_json_atomico
from ..core.armazenamento import preservar, sha256
from ..core.contratos import ViolacaoContrato
from ..core.http import obter_bytes

FONTE = 'transferegov_discricionarias'
BASE_URL = 'https://repositorio.dados.gov.br/seges/detru/'
DATA_CARGA = 'data_carga_siconv.csv.zip'
# Tabelas com escopo municipal: a proposta leva o código IBGE; as demais ligam-se a ela.
TABELAS = ('siconv_proposta.csv.zip', 'siconv_convenio.csv.zip',
           'siconv_desembolso.csv.zip', 'siconv_emenda.csv.zip')
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


def _verificados(raiz: Path, geracao: dict) -> dict | None:
    caminhos = {nome: raiz / rel for nome, rel in geracao['arquivos'].items()}
    if set(caminhos) != {DATA_CARGA, *TABELAS}:
        return None
    for p in caminhos.values():
        if not p.exists() or sha256(p.read_bytes()) != p.parent.name:
            raise ViolacaoContrato(f'Bronze {FONTE} corrompido: {p}; investigar antes de --refresh')
    return caminhos


def verificar(raiz: Path) -> dict:
    """Carga mais recente já completa no Bronze, sem rede."""
    indice = _indice(raiz)
    if not indice.exists():
        raise ViolacaoContrato(f'Sem Bronze {FONTE}; execute sem --offline')
    estado = json.loads(indice.read_text(encoding='utf-8'))
    caminhos = _verificados(raiz, estado['cargas'][estado['atual']]) if estado.get('atual') else None
    if caminhos is None:
        raise ViolacaoContrato(f'Bronze {FONTE} incompleto; execute sem --offline')
    return caminhos


def extrair(sessao, raiz: Path, *, refresh=False):
    """Uma geração por `data_carga` publicada; arquivos já preservados não são baixados de novo."""
    indice = _indice(raiz)
    estado = json.loads(indice.read_text(encoding='utf-8')) if indice.exists() else {'atual': None, 'cargas': {}}
    conteudo = obter_bytes(sessao, BASE_URL + DATA_CARGA, CONFIG)
    data_carga = ler_data_carga(conteudo)
    geracao = estado['cargas'].setdefault(data_carga, {'data_carga': data_carga, 'arquivos': {}})
    if not refresh and (caminhos := _verificados(raiz, geracao)) is not None:
        return caminhos
    marcador = preservar(raiz, FONTE, DATA_CARGA, conteudo, BASE_URL + DATA_CARGA)
    geracao['arquivos'][DATA_CARGA] = marcador.relative_to(raiz).as_posix()
    for nome in TABELAS:
        anterior = geracao['arquivos'].get(nome)
        if anterior and not refresh and (raiz / anterior).exists():
            continue
        destino = preservar(raiz, FONTE, nome, obter_bytes(sessao, BASE_URL + nome, CONFIG), BASE_URL + nome)
        geracao['arquivos'][nome] = destino.relative_to(raiz).as_posix()
        salvar_json_atomico(indice, estado)
    # A carga publicada pode mudar durante um download longo: só aceita se a data continuar a mesma.
    if ler_data_carga(obter_bytes(sessao, BASE_URL + DATA_CARGA, CONFIG)) != data_carga:
        # Arquivos de cargas diferentes não formam uma geração; os bytes seguem no Bronze, sem índice.
        estado['cargas'].pop(data_carga)
        salvar_json_atomico(indice, estado)
        raise ViolacaoContrato('data_carga mudou durante a extração; repetir a extração')
    estado['atual'] = data_carga
    salvar_json_atomico(indice, estado)
    return _verificados(raiz, geracao)
