"""MUNIC (IBGE): base de dados de cada edição, como publicada no FTP.

O IBGE substitui a base de uma edição por versões revisadas com outro nome
(`Base_MUNIC_2021_20240425.xlsx`). Cada execução relê as listagens; uma revisão
nova entra no Bronze sem apagar a anterior, que permanece no histórico do índice.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from etl_confiabilidade import salvar_json_atomico
from ..core.armazenamento import preservar, sha256
from ..core.contratos import ViolacaoContrato
from ..core.http import obter_bytes

FONTE = 'munic'
BASE_URL = 'https://ftp.ibge.gov.br/Perfil_Municipios/'
# A edição 2019 é a última publicada antes de 2021; serve à fotografia de 2020.
ANO_MINIMO = 2019
CONFIG = {'max_tentativas': 4, 'timeout_segundos': 600, 'backoff_base_segundos': 5}


def _indice(raiz: Path) -> Path:
    return raiz / 'ref' / f'{FONTE}_bronze.json'


def _hrefs(html: bytes):
    return re.findall(r'href="([^"?/][^"]*)"', html.decode('utf-8', errors='replace'))


def edicoes(listagem: bytes):
    return sorted(int(h[:4]) for h in _hrefs(listagem) if re.fullmatch(r'\d{4}/', h) and int(h[:4]) >= ANO_MINIMO)


def base_da_edicao(listagem: bytes, ano: int) -> str:
    """Nome da base xlsx; mais de uma ou nenhuma bloqueia, sem escolher por conta própria."""
    nomes = [h for h in _hrefs(listagem) if re.fullmatch(rf'Base_MUNIC_{ano}(_\d{{8}})?\.xlsx', h)]
    if len(nomes) != 1:
        raise ViolacaoContrato(f'MUNIC {ano}: esperada uma base xlsx, encontradas {nomes}')
    return nomes[0]


def _verificado(raiz, rel):
    caminho = raiz / rel
    if not caminho.exists() or sha256(caminho.read_bytes()) != caminho.parent.name:
        raise ViolacaoContrato(f'Bronze {FONTE} corrompido: {caminho}; investigar antes de --refresh')
    return caminho


def extrair(sessao, raiz: Path, *, refresh=False):
    indice = _indice(raiz)
    estado = json.loads(indice.read_text(encoding='utf-8')) if indice.exists() else {'edicoes': {}, 'historico': []}
    raiz_listagem = obter_bytes(sessao, BASE_URL, CONFIG)
    preservar(raiz, FONTE, 'listagem_perfil_municipios.html', raiz_listagem, BASE_URL)
    anos = edicoes(raiz_listagem)
    if not anos:
        raise ViolacaoContrato('Nenhuma edição MUNIC encontrada na listagem oficial')
    for ano in anos:
        url_pasta = f'{BASE_URL}{ano}/Base_de_Dados/'
        listagem = obter_bytes(sessao, url_pasta, CONFIG)
        caminho_listagem = preservar(raiz, FONTE, f'listagem_{ano}.html', listagem, url_pasta)
        nome = base_da_edicao(listagem, ano)
        atual = estado['edicoes'].get(str(ano))
        if atual and atual['nome'] == nome and not refresh:
            _verificado(raiz, atual['arquivo'])
            continue
        destino = preservar(raiz, FONTE, nome, obter_bytes(sessao, url_pasta + nome, CONFIG), url_pasta + nome)
        if atual and atual['arquivo'] != destino.relative_to(raiz).as_posix():
            estado['historico'].append({**atual, 'substituido_em_utc': datetime.now(timezone.utc).isoformat(timespec='seconds')})
        estado['edicoes'][str(ano)] = {
            'nome': nome, 'url': url_pasta + nome, 'arquivo': destino.relative_to(raiz).as_posix(),
            'listagem': caminho_listagem.relative_to(raiz).as_posix(),
            'verificado_em_utc': datetime.now(timezone.utc).isoformat(timespec='seconds')}
        salvar_json_atomico(indice, estado)
    salvar_json_atomico(indice, estado)
    return verificar(raiz)


def verificar(raiz: Path) -> dict:
    """Base atual de cada edição, conferida pelo hash, sem rede."""
    indice = _indice(raiz)
    if not indice.exists():
        raise ViolacaoContrato(f'Sem Bronze {FONTE}; execute sem --offline')
    estado = json.loads(indice.read_text(encoding='utf-8'))
    if not estado['edicoes']:
        raise ViolacaoContrato(f'Bronze {FONTE} sem edições; execute sem --offline')
    return {f'edicao_{ano}': _verificado(raiz, e['arquivo']) for ano, e in sorted(estado['edicoes'].items())}
