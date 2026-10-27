"""SICONFI: extrato de entregas, DCA e RGF do Executivo municipal, como a API responde.

O extrato de entregas é a evidência de disponibilidade (periodicidade, status e
data de envio). Ele também decide qual RGF consultar: quadrimestral (Q3) ou
Simplificado semestral (S2), conforme o que a prefeitura entregou no exercício.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
import pandas as pd
from etl_confiabilidade import FalhaConsulta, salvar_json_atomico
from ..core.armazenamento import preservar, sha256
from ..core.contratos import ViolacaoContrato, validar_numerica
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


# --- Silver: RGF, Anexo 1 (despesa com pessoal) --------------------------------
# Contas novas a partir do leiaute de 2024 (CF, art. 198, § 11, agentes comunitários; piso da
# enfermagem). A harmonização devolve essas deduções para manter a regra de 2020–2023 (ADR 0003).
DEDUCAO_ACS = 'AgentesComunitariosDeSaudeEDeCombateAsEndemiasComRecursosVinculados'
DEDUCAO_ENFERMAGEM = 'ParcelaDedutivelReferenteAoPisoSalarialDoEnfermeiroTecnicoDeEnfermagemAuxiliarDeEnfermagemEParteira'
RCL_ACS = 'TransferenciasDaUniaoRelativasARemuneracaoDosAgentesComunitariosDeSaude'
TOTAL_12_MESES = 'TOTAL (ÚLTIMOS 12 MESES)'
TOLERANCIA_PP = 0.01


def _itens(caminhos, recurso):
    return [item for p in sorted(caminhos[recurso]) for item in json.loads(p.read_bytes())['items']]


def _entregas_rgf(caminhos):
    """Data e status do envio do RGF do último período do Executivo, pelo extrato de entregas."""
    linhas = []
    for item in _itens(caminhos, 'extrato_entregas'):
        entregavel, instituicao = item.get('entregavel') or '', item.get('instituicao') or ''
        periodicidade = item.get('periodicidade')
        if (entregavel.startswith('Relatório de Gestão Fiscal') and instituicao.startswith('Prefeitura')
                and ULTIMO_PERIODO.get(periodicidade) == item.get('periodo')):
            linhas.append({'codigo_ibge': str(item['cod_ibge']), 'ano': int(item['exercicio']),
                           'periodicidade': periodicidade, 'status_relatorio': item.get('status_relatorio'),
                           'data_envio': pd.to_datetime(item.get('data_status'), utc=True)})
    return pd.DataFrame(linhas, columns=['codigo_ibge', 'ano', 'periodicidade', 'status_relatorio', 'data_envio'])


def transformar_rgf(caminhos):
    """Componentes do Anexo 1 por município e exercício, com a razão declarada e a harmonizada."""
    itens = [i for i in _itens(caminhos, 'rgf') if i['anexo'] == 'RGF-Anexo 01']
    a1 = pd.DataFrame(itens, columns=['cod_ibge', 'exercicio', 'periodicidade', 'cod_conta', 'coluna', 'valor'])
    a1['codigo_ibge'], a1['ano'] = a1.cod_ibge.astype(str), a1.exercicio.astype(int)
    chaves = ['codigo_ibge', 'ano']
    if a1.groupby(chaves).periodicidade.nunique().gt(1).any():
        raise ViolacaoContrato('Município-ano com mais de um RGF do último período')

    def componente(cod, coluna, *, total=False):
        filtro = a1.coluna.str.startswith(TOTAL_12_MESES) if total else a1.coluna == coluna
        linhas = a1[(a1.cod_conta == cod) & filtro]
        if linhas.duplicated(chaves).any():
            raise ViolacaoContrato(f'Conta {cod} repetida no mesmo RGF')
        return linhas.set_index(chaves).valor

    base = a1.drop_duplicates(chaves).set_index(chaves)[['periodicidade']]
    silver = base.assign(
        despesa_pessoal_bruta=componente('DespesaComPessoalBruta', None, total=True),
        despesa_pessoal_total=componente('DespesaComPessoalTotal', 'Valor'),
        razao_declarada_publicada=componente('DespesaComPessoalTotal', '% sobre a RCL Ajustada'),
        rcl_legal=componente('ReceitaCorrenteLiquidaLimiteLegal', 'Valor'),
        rcl_ajustada=componente('ReceitaCorrenteLiquidaAjustada', 'Valor'),
        deducao_acs=componente(DEDUCAO_ACS, None, total=True),
        deducao_piso_enfermagem=componente(DEDUCAO_ENFERMAGEM, None, total=True),
        rcl_excluida_repasse_acs=componente(RCL_ACS, 'Valor'),
    ).reset_index()
    if silver[['despesa_pessoal_total', 'rcl_ajustada']].isna().any().any() or (silver.rcl_ajustada <= 0).any():
        raise ViolacaoContrato('RGF sem despesa total com pessoal ou RCL ajustada válida')
    # Conta ausente no leiaute do ano não é dedução: vale zero para a harmonização.
    novas = ['deducao_acs', 'deducao_piso_enfermagem', 'rcl_excluida_repasse_acs']
    silver[novas] = silver[novas].fillna(0.0)
    silver['razao_declarada'] = silver.despesa_pessoal_total / silver.rcl_ajustada * 100
    if ((silver.razao_declarada - silver.razao_declarada_publicada).abs() > TOLERANCIA_PP).any():
        raise ViolacaoContrato('Razão calculada difere do percentual publicado no RGF')
    silver['razao_harmonizada'] = ((silver.despesa_pessoal_total + silver.deducao_acs + silver.deducao_piso_enfermagem)
                                   / (silver.rcl_ajustada + silver.rcl_excluida_repasse_acs) * 100)
    silver = silver.merge(_entregas_rgf(caminhos), on=['codigo_ibge', 'ano', 'periodicidade'],
                          how='left', validate='one_to_one')
    for coluna in ['despesa_pessoal_total', 'rcl_ajustada', *novas, 'razao_declarada', 'razao_harmonizada']:
        validar_numerica(silver, coluna)
    silver = silver.sort_values(chaves).reset_index(drop=True)
    silver.attrs['chave'] = chaves
    return {'silver/siconfi_rgf_pessoal': silver}


TEMPORALIDADE_RGF = {
    'rgf_pessoal_rcl_declarada': (
        'apta_defasagem_t_mais_1', 'RGF do último período enviado em jan/t+1; data em silver.data_envio (retificação substitui)'),
    'rgf_pessoal_rcl_harmonizada': (
        'apta_defasagem_t_mais_1', 'regra de 2020–2023: devolve deduções de ACS/ACE e piso da enfermagem (ADR 0003)'),
    'rgf_deducoes_novas_pp': (
        'apta_defasagem_t_mais_1', 'harmonizada menos declarada; zero antes de 2024, quando as contas não existiam'),
}


def painel_rgf(silver, codigos, anos):
    """Município × ano; RGF não entregue fica nulo (indisponível), nunca zero."""
    rgf = silver['silver/siconfi_rgf_pessoal'].set_index(['codigo_ibge', 'ano'])
    chaves = pd.MultiIndex.from_product([sorted(codigos), anos], names=['codigo_ibge', 'ano'])
    quadro = pd.DataFrame({
        'rgf_pessoal_rcl_declarada': rgf.razao_declarada,
        'rgf_pessoal_rcl_harmonizada': rgf.razao_harmonizada,
        'rgf_deducoes_novas_pp': rgf.razao_harmonizada - rgf.razao_declarada,
    }).reindex(chaves)
    for coluna in ['rgf_pessoal_rcl_declarada', 'rgf_pessoal_rcl_harmonizada']:
        validar_numerica(quadro, coluna)
    return quadro.reset_index()


# --- Silver: DCA, Anexo I-C, no recorte de apoio ao Transferegov ---------------
# Contas agregadoras por leiaute da natureza de receita (o ementário mudou em 2022).
# Na PB, a agregadora está sempre presente quando há contas-filhas: soma-se só a agregadora.
MAPA_RECEITA = (
    ('convenios_uniao', 'corrente', '2020-2021', '1.7.1.8.10.0.0'),
    ('convenios_uniao', 'capital', '2020-2021', '2.4.1.8.10.0.0'),
    ('convenios_uniao', 'corrente', '2022+', '1.7.1.7.00.0.0'),
    ('convenios_uniao', 'capital', '2022+', '2.4.1.4.00.0.0'),
    ('convenios_estado', 'corrente', '2020-2021', '1.7.2.8.10.0.0'),
    ('convenios_estado', 'capital', '2020-2021', '2.4.2.8.10.0.0'),
    ('convenios_estado', 'corrente', '2022+', '1.7.2.4.00.0.0'),
    ('convenios_estado', 'capital', '2022+', '2.4.2.2.00.0.0'),
    ('transferencia_especial', 'corrente', '2022+', '1.7.1.9.57.0.0'),
    ('transferencia_especial', 'capital', '2022+', '2.4.1.9.51.0.0'),
)
RECEITA_TOTAL = 'ReceitasExcetoIntraOrcamentarias'
RECEITA_BRUTA = 'Receitas Brutas Realizadas'
GRUPOS_RECEITA = ('convenios_uniao', 'convenios_estado', 'transferencia_especial')


def leiaute_receita(ano):
    return '2020-2021' if ano <= 2021 else '2022+'


def _entregas_dca(caminhos):
    linhas = [{'codigo_ibge': str(i['cod_ibge']), 'ano': int(i['exercicio']), 'status_relatorio': i.get('status_relatorio'),
               'data_envio': pd.to_datetime(i.get('data_status'), utc=True)}
              for i in _itens(caminhos, 'extrato_entregas')
              if i.get('entregavel') == 'Balanço Anual (DCA)' and (i.get('instituicao') or '').startswith('Prefeitura')]
    quadro = pd.DataFrame(linhas, columns=['codigo_ibge', 'ano', 'status_relatorio', 'data_envio'])
    if quadro.duplicated(['codigo_ibge', 'ano']).any():
        raise ViolacaoContrato('Mais de uma DCA da prefeitura no mesmo exercício')
    return quadro


def transformar_dca(caminhos):
    """Receita total e transferências de convênios e especiais declaradas na DCA, por município e exercício."""
    mapa = pd.DataFrame(MAPA_RECEITA, columns=['grupo', 'categoria', 'leiaute', 'natureza'])
    mapa['cod_conta'] = 'RO' + mapa.natureza
    itens = [i for i in _itens(caminhos, 'dca') if i['anexo'] == 'DCA-Anexo I-C']
    ic = pd.DataFrame(itens, columns=['cod_ibge', 'exercicio', 'cod_conta', 'conta', 'coluna', 'valor'])
    ic['codigo_ibge'], ic['ano'] = ic.cod_ibge.astype(str), ic.exercicio.astype(int)
    chave = ['codigo_ibge', 'ano', 'cod_conta', 'coluna']
    if ic.duplicated(chave).any():
        raise ViolacaoContrato('Conta e coluna repetidas na DCA, Anexo I-C')
    # Código do leiaute errado para o ano indica mudança de ementário não mapeada.
    mapeadas = ic.merge(mapa, on='cod_conta')
    if (mapeadas.ano.map(leiaute_receita) != mapeadas.leiaute).any():
        raise ViolacaoContrato('Natureza de receita fora do leiaute do exercício')
    apoio = ic[ic.cod_conta.isin(mapa.cod_conta) | (ic.cod_conta == RECEITA_TOTAL)] \
        .merge(mapa[['cod_conta', 'grupo', 'categoria']], on='cod_conta', how='left')
    apoio = apoio[['codigo_ibge', 'ano', 'cod_conta', 'conta', 'coluna', 'valor', 'grupo', 'categoria']] \
        .sort_values(chave).reset_index(drop=True)
    apoio.attrs['chave'] = chave

    total = ic[ic.cod_conta == RECEITA_TOTAL]
    bruta = total[total.coluna == RECEITA_BRUTA].set_index(['codigo_ibge', 'ano']).valor
    deducoes = total[total.coluna.str.contains('Dedu', case=False)].groupby(['codigo_ibge', 'ano']).valor.sum()
    municipio = pd.DataFrame({'receita_bruta': bruta}).assign(
        deducoes=deducoes.reindex(bruta.index).fillna(0.0))
    municipio['receita_liquida'] = municipio.receita_bruta - municipio.deducoes
    valores = apoio[apoio.grupo.notna() & (apoio.coluna == RECEITA_BRUTA)]
    for (grupo, categoria), parte in valores.groupby(['grupo', 'categoria']):
        municipio[f'{grupo}_{categoria}'] = parte.set_index(['codigo_ibge', 'ano']).valor
    for grupo in GRUPOS_RECEITA:
        colunas = [f'{grupo}_{c}' for c in ('corrente', 'capital')]
        for coluna in colunas:
            if coluna not in municipio:
                municipio[coluna] = float('nan')
        # DCA entregue sem a conta: zero declarado; conta inexistente no leiaute do ano: nulo.
        existe = municipio.index.get_level_values('ano').map(leiaute_receita).isin(mapa[mapa.grupo == grupo].leiaute)
        municipio.loc[existe, colunas] = municipio.loc[existe, colunas].fillna(0.0)
        municipio[grupo] = municipio[colunas].sum(axis=1, min_count=1)
    municipio = municipio.reset_index().merge(_entregas_dca(caminhos), on=['codigo_ibge', 'ano'], how='left',
                                               validate='one_to_one')
    if municipio.receita_liquida.isna().any() or (municipio.receita_liquida <= 0).any():
        raise ViolacaoContrato('DCA sem receita líquida positiva')
    for coluna in ['receita_bruta', 'receita_liquida', *GRUPOS_RECEITA]:
        validar_numerica(municipio, coluna)
    municipio = municipio.sort_values(['codigo_ibge', 'ano']).reset_index(drop=True)
    municipio.attrs['chave'] = ['codigo_ibge', 'ano']
    mapa_ref = mapa[['natureza', 'grupo', 'categoria', 'leiaute']].sort_values('natureza').reset_index(drop=True)
    return {'silver/siconfi_dca_receita_apoio': apoio, 'silver/siconfi_dca_receita_municipio': municipio,
            'ref/siconfi_mapa_receita': mapa_ref}


TEMPORALIDADE_DCA = {
    'dca_receita_liquida_total': (
        'apta_defasagem_t_mais_1', 'DCA enviada até abr/t+1; data em silver.data_envio (retificação substitui)'),
    'dca_convenios_uniao': ('apta_defasagem_t_mais_1', 'receita de convênios da União declarada na DCA'),
    'dca_convenios_estado': ('apta_defasagem_t_mais_1', 'receita de convênios do Estado declarada na DCA'),
    'dca_dependencia_convenios_uniao': ('apta_defasagem_t_mais_1', 'convênios da União ÷ receita líquida'),
    'dca_transferencia_especial': (
        'somente_descritiva', 'conta só existe desde 2022 e há Pix contabilizado em outra natureza; nulo em 2020–2021'),
}
TEMPORALIDADE_DCA_TRANSFEREGOV = {
    'dca_convenios_uniao_fora_transferegov': (
        'apta_defasagem_t_mais_1', 'DCA menos desembolsos do Transferegov; pode ser negativo por diferença de data'),
    'dca_pix_divergente': (
        'somente_descritiva', '1 quando recebeu Pix no Transferegov e declarou zero na conta própria da DCA; nulo antes de 2022'),
}


def painel_dca(silver, codigos, anos, transferegov=None):
    """Município × ano; DCA não entregue fica nula. `transferegov`: painel com desembolsos e Pix pagos."""
    dca = silver['silver/siconfi_dca_receita_municipio'].set_index(['codigo_ibge', 'ano'])
    chaves = pd.MultiIndex.from_product([sorted(codigos), anos], names=['codigo_ibge', 'ano'])
    quadro = pd.DataFrame({
        'dca_receita_liquida_total': dca.receita_liquida,
        'dca_convenios_uniao': dca.convenios_uniao,
        'dca_convenios_estado': dca.convenios_estado,
        'dca_dependencia_convenios_uniao': dca.convenios_uniao / dca.receita_liquida,
        'dca_transferencia_especial': dca.transferencia_especial,
    }).reindex(chaves)
    if transferegov is not None:
        tg = transferegov.set_index(['codigo_ibge', 'ano']).reindex(chaves)
        quadro['dca_convenios_uniao_fora_transferegov'] = quadro.dca_convenios_uniao - tg.transferegov_valor_desembolsado
        divergente = (tg.transferegov_especiais_valor_pago > 0) & (quadro.dca_transferencia_especial == 0)
        quadro['dca_pix_divergente'] = divergente.astype(float).where(quadro.dca_transferencia_especial.notna())
    for coluna in ['dca_receita_liquida_total', 'dca_convenios_uniao', 'dca_convenios_estado', 'dca_transferencia_especial']:
        validar_numerica(quadro, coluna)
    validar_numerica(quadro, 'dca_dependencia_convenios_uniao', maximo=1)
    return quadro.reset_index()
