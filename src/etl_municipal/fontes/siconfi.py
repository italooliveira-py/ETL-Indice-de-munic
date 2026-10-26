"""SICONFI: extrato de entregas, DCA e RGF do Executivo municipal, como a API responde.

O extrato de entregas é a evidência de disponibilidade (periodicidade, status e
data de envio). Ele também decide qual RGF consultar: quadrimestral (Q3) ou
Simplificado semestral (S2), conforme o que a prefeitura entregou no exercício.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from etl_confiabilidade import FalhaConsulta, salvar_json_atomico
from ..core.armazenamento import preservar, sha256
from ..core.contratos import ViolacaoContrato
from ..core.http import obter_json
from .ibge_territorial import CATALOGO_URL

FONTE = 'siconfi'
BASE_URL = 'https://apidatalake.tesouro.gov.br/ords/siconfi/tt/'
ROOT = Path(__file__).resolve().parents[3]
CONFIG = {'max_tentativas': 4, 'timeout_segundos': 60, 'intervalo_requisicoes_segundos': 0.3}
SALVAR_A_CADA = 20
ULTIMO_PERIODO = {'Q': 3, 'S': 2}


def anos_configurados(caminho=ROOT / 'config.json'):
    config = json.loads(Path(caminho).read_text(encoding='utf-8'))
    inicio = max(int(config['ano_inicial']), int(config.get('siconfi_ano_inicial', config['ano_inicial'])))
    fim = min(int(config['ano_final']), int(config.get('siconfi_ano_final', config['ano_final'])))
    return list(range(inicio, fim + 1))


def _indice(raiz: Path) -> Path:
    return raiz / 'ref' / f'{FONTE}_bronze.json'


def _ler(raiz, registro):
    caminho = raiz / registro['arquivo']
    if not caminho.exists() or sha256(caminho.read_bytes()) != caminho.parent.name:
        raise ViolacaoContrato(f'Bronze {FONTE} corrompido: {caminho}; investigar antes de --refresh')
    return caminho, json.loads(caminho.read_bytes())


class _Coleta:
    def __init__(self, sessao, raiz, estado):
        self.sessao, self.raiz, self.estado = sessao, raiz, estado
        self.indice, self.estado_http, self.novas = _indice(raiz), {}, 0

    def salvar(self, forcar=False):
        if forcar or self.novas >= SALVAR_A_CADA:
            salvar_json_atomico(self.indice, self.estado)
            self.novas = 0

    def paginas(self, recurso, filtro, codigo):
        """Todas as páginas ORDS de uma consulta; `hasMore` decide o fim, nunca o tamanho."""
        itens, offset = [], 0
        while True:
            params = {**filtro, 'offset': offset}
            chave = f'{recurso}?{urlencode(sorted(params.items()))}'
            if chave in self.estado['paginas']:
                _, dados = _ler(self.raiz, self.estado['paginas'][chave])
            else:
                dados, conteudo = obter_json(self.sessao, BASE_URL + recurso, CONFIG, params=params,
                                             fonte='SICONFI', contexto=chave, estado=self.estado_http)
                if not isinstance(dados, dict) or not isinstance(dados.get('items'), list) \
                        or not isinstance(dados.get('hasMore'), bool):
                    raise ViolacaoContrato(f'Resposta sem items/hasMore em {chave}')
                if any(str(i.get('cod_ibge', codigo)) != codigo for i in dados['items']):
                    raise ViolacaoContrato(f'Resposta de outro ente em {chave}')
                nome = f'{recurso}_{codigo}_{sha256(chave.encode())[:12]}.json'
                caminho = preservar(self.raiz, FONTE, nome, conteudo, BASE_URL + recurso + '?' + urlencode(params))
                self.estado['paginas'][chave] = {'recurso': recurso, 'params': params, 'itens': len(dados['items']),
                                                 'arquivo': caminho.relative_to(self.raiz).as_posix()}
                self.novas += 1
                self.salvar()
            itens += dados['items']
            if not dados['hasMore']:
                return itens
            limite = dados.get('limit')
            if not isinstance(limite, int) or limite <= 0 or not dados['items']:
                raise FalhaConsulta(f'Paginação inconsistente em {chave}')
            offset += limite


def _rgfs_entregues(extrato):
    """(tipo, periodicidade) dos RGF do Executivo informados no extrato do exercício."""
    tipos = set()
    for item in extrato:
        entregavel, instituicao = item.get('entregavel') or '', item.get('instituicao') or ''
        if entregavel.startswith('Relatório de Gestão Fiscal') and instituicao.startswith('Prefeitura'):
            tipo = 'RGF Simplificado' if 'Simplificado' in entregavel else 'RGF'
            if item.get('periodicidade') in ULTIMO_PERIODO:
                tipos.add((tipo, item['periodicidade']))
    return sorted(tipos)


def extrair(sessao, raiz: Path, *, refresh=False, anos=None):
    """Retoma pela última página preservada; consultas que falharam são repetidas na próxima execução."""
    anos = anos or anos_configurados()
    indice = _indice(raiz)
    estado = json.loads(indice.read_text(encoding='utf-8')) if indice.exists() else None
    if estado and (refresh or estado['anos'] != anos):
        historico = raiz / 'ref' / 'historico' / f"{FONTE}_bronze_{estado['iniciado_em_utc'].replace(':', '')}.json"
        salvar_json_atomico(historico, estado)
        estado = None
    if estado and estado['completo']:
        return verificar(raiz)
    estado = estado or {'iniciado_em_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                        'anos': anos, 'completo': False, 'municipios': None, 'paginas': {}, 'falhas': {}}
    estado['falhas'] = {}
    if estado['municipios'] is None:
        catalogo, conteudo = obter_json(sessao, CATALOGO_URL, CONFIG, fonte='IBGE', contexto='catálogo PB')
        caminho = preservar(raiz, FONTE, 'municipios_pb.json', conteudo, CATALOGO_URL)
        estado['municipios'] = caminho.relative_to(raiz).as_posix()
    catalogo = json.loads((raiz / estado['municipios']).read_bytes())
    codigos = sorted(str(m['id']) for m in catalogo)
    if len(codigos) != 223:
        raise ViolacaoContrato('Catálogo oficial deve conter 223 municípios da PB')
    coleta = _Coleta(sessao, raiz, estado)
    try:
        for codigo in codigos:
            for ano in anos:
                try:
                    extrato = coleta.paginas('extrato_entregas', {'id_ente': codigo, 'an_referencia': ano}, codigo)
                    coleta.paginas('dca', {'an_exercicio': ano, 'id_ente': codigo}, codigo)
                    for tipo, periodicidade in _rgfs_entregues(extrato):
                        coleta.paginas('rgf', {'an_exercicio': ano, 'in_periodicidade': periodicidade,
                                               'nr_periodo': ULTIMO_PERIODO[periodicidade],
                                               'co_tipo_demonstrativo': tipo, 'co_esfera': 'M',
                                               'co_poder': 'E', 'id_ente': codigo}, codigo)
                except (FalhaConsulta, ViolacaoContrato) as exc:
                    # Falha nunca equivale a ausência: fica registrada e bloqueia a conclusão.
                    estado['falhas'][f'{codigo}-{ano}'] = str(exc)
    finally:
        coleta.salvar(forcar=True)
    if estado['falhas']:
        raise ViolacaoContrato(f"{len(estado['falhas'])} consultas SICONFI falharam; repetir para retomar")
    estado['completo'] = True
    estado['concluido_em_utc'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    coleta.salvar(forcar=True)
    return verificar(raiz)


def verificar(raiz: Path) -> dict:
    """Páginas da última extração completa, conferidas pelo hash, sem rede."""
    indice = _indice(raiz)
    if not indice.exists():
        raise ViolacaoContrato(f'Sem Bronze {FONTE}; execute sem --offline')
    estado = json.loads(indice.read_text(encoding='utf-8'))
    if not estado['completo']:
        raise ViolacaoContrato(f'Bronze {FONTE} incompleto; execute sem --offline para retomar')
    caminhos = {'extrato_entregas': [], 'dca': [], 'rgf': []}
    for registro in estado['paginas'].values():
        caminhos[registro['recurso']].append(_ler(raiz, registro)[0])
    municipios = raiz / estado['municipios']
    if sha256(municipios.read_bytes()) != municipios.parent.name:
        raise ViolacaoContrato(f'Bronze {FONTE} corrompido: {municipios}')
    return {'municipios': municipios, **caminhos}
