"""Contexto territorial do Censo 2022, sem extrapolar área para outros anos."""
import json
from pathlib import Path
import pandas as pd
from etl_confiabilidade import requisitar_json, salvar_json_atomico
from ..core.armazenamento import preservar, sha256
from ..core.contratos import ViolacaoContrato, validar_numerica, validar_tabela

CATALOGO_URL = 'https://servicodados.ibge.gov.br/api/v1/localidades/estados/25/municipios'
DADOS_URL = ('https://servicodados.ibge.gov.br/api/v3/agregados/4714/periodos/2022/'
             'variaveis/93|6318|614?localidades=N6[N3[25]]')
METADADOS_URL = 'https://servicodados.ibge.gov.br/api/v3/agregados/4714/metadados'
VARIAVEIS = {'93': 'populacao_censo_2022', '6318': 'area_km2', '614': 'densidade_censo_2022'}


class _CapturarResposta:
    def __init__(self, sessao):
        self.sessao = sessao
        self.resposta = None

    def get(self, *args, **kwargs):
        self.resposta = self.sessao.get(*args, **kwargs)
        return self.resposta


def extrair(sessao, raiz: Path, *, refresh=False):
    indice = raiz / 'ref' / 'ibge_territorial_bronze.json'
    if indice.exists() and not refresh:
        caminhos = {k: raiz / v for k, v in json.loads(indice.read_text(encoding='utf-8')).items()}
        if all(p.exists() and sha256(p.read_bytes()) == p.parent.name for p in caminhos.values()):
            return caminhos
        raise ViolacaoContrato('Cache territorial corrompido; investigar antes de --refresh')
    caminhos = {}
    for nome, url in [('municipios', CATALOGO_URL), ('metadados', METADADOS_URL), ('dados', DADOS_URL)]:
        captura = _CapturarResposta(sessao)
        requisitar_json(captura, url, {'max_tentativas': 4, 'timeout_segundos': 60})
        conteudo = captura.resposta.content
        caminhos[nome] = preservar(raiz, 'ibge_territorial', nome + '.json', conteudo, url)
    salvar_json_atomico(indice, {k: str(v.relative_to(raiz)) for k, v in caminhos.items()})
    return caminhos


def transformar(caminhos):
    catalogo = json.loads(caminhos['municipios'].read_text(encoding='utf-8'))
    referencia = pd.DataFrame([{'codigo_ibge': str(m['id']), 'municipio': m['nome'], 'uf': 'PB'} for m in catalogo])
    universo = set(referencia.codigo_ibge)
    if len(referencia) != 223:
        raise ViolacaoContrato('Catálogo oficial deve conter 223 municípios da PB')
    validar_tabela(referencia, ['codigo_ibge'], universo, completa=True)
    dados = json.loads(caminhos['dados'].read_text(encoding='utf-8'))
    resultado = referencia.copy()
    for identificador, coluna in VARIAVEIS.items():
        blocos = [b for b in dados if str(b['id']) == identificador]
        if len(blocos) != 1 or len(blocos[0]['resultados']) != 1:
            raise ViolacaoContrato(f'Leiaute territorial inesperado: {identificador}')
        valores = pd.DataFrame([
            {'codigo_ibge': str(s['localidade']['id']), coluna: s['serie'].get('2022')}
            for s in blocos[0]['resultados'][0]['series']])
        validar_tabela(valores, ['codigo_ibge'], universo, completa=True)
        validar_numerica(valores, coluna, minimo=0.000001, nulos=False)
        valores[coluna] = pd.to_numeric(valores[coluna])
        resultado = resultado.merge(valores, on='codigo_ibge', validate='one_to_one')
    calculada = resultado.populacao_censo_2022 / resultado.area_km2
    if ((calculada - resultado.densidade_censo_2022).abs() > 0.02).any():
        raise ViolacaoContrato('Densidade incompatível com população / área')
    resultado['ano_referencia_territorial'] = 2022
    resultado['status_ibge_territorial'] = 'observado'
    resultado['data_disponibilidade_territorial'] = pd.Series(pd.NA, index=resultado.index, dtype='string')
    resultado['bioma_predominante'] = pd.Series(pd.NA, index=resultado.index, dtype='string')
    resultado['percentual_bioma_predominante'] = float('nan')
    resultado['status_bioma'] = 'indisponivel'
    resultado['tipologia_rural_urbana'] = pd.Series(pd.NA, index=resultado.index, dtype='string')
    resultado['status_tipologia'] = 'indisponivel'
    return referencia, resultado.sort_values('codigo_ibge').reset_index(drop=True)
