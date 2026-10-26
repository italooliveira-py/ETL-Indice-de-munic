"""Transferegov sem rede: recorte PB no Bronze, retomada, Silver, painéis e publicação."""
import gzip
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd
import requests

from etl_confiabilidade import FalhaConsulta
from src.etl_municipal.core.armazenamento import sha256
from src.etl_municipal.core.contratos import ViolacaoContrato
from src.etl_municipal.fontes import snapshot
from src.etl_municipal.fontes import transferegov_discricionarias as disc
from src.etl_municipal.fontes import transferegov_especiais as esp
from src.etl_municipal.publicacao import construir, publicar
from src.etl_municipal.__main__ import main

ROOT = Path(__file__).resolve().parents[1]
JP, CONDE, AGUA_BRANCA = '2507507', '2504603', '2500106'
MUNICIPAL = 'Administração Pública Municipal'


def zip_texto(nome, texto):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as arquivo:
        arquivo.writestr(zipfile.ZipInfo(nome, date_time=(2026, 7, 17, 6, 30, 0)), texto)
    return buffer.getvalue()


def csv(linhas):
    return '\n'.join(';'.join(campos) for campos in linhas) + '\n'


TABELAS = {
    'siconv_proposta.csv.zip': csv([
        ['ID_PROPOSTA', 'UF_PROPONENTE', 'COD_MUNIC_IBGE', 'NATUREZA_JURIDICA', 'IDENTIF_PROPONENTE', 'NM_PROPONENTE',
         'MODALIDADE', 'DESC_ORGAO_SUP', 'DESC_ORGAO', 'DIA_PROPOSTA', 'OBJETO_PROPOSTA'],
        ['1', 'PB', JP, MUNICIPAL, '08778326000156', 'MUNICIPIO DE JOAO PESSOA', 'CONVENIO', 'MIN A', 'ORG A', '10/01/2021', '"Praça; reforma"'],
        ['2', 'SP', '3550308', MUNICIPAL, '46395000000139', 'MUNICIPIO DE SAO PAULO', 'CONVENIO', 'MIN A', 'ORG A', '10/01/2021', 'x'],
        ['3', 'PB', CONDE, MUNICIPAL, '08924037000118', 'MUNICIPIO DO CONDE', 'CONTRATO DE REPASSE', 'MIN B', 'ORG B', '05/06/2021', 'y'],
        ['4', 'PB', '', 'Organização da Sociedade Civil', '11111111000111', 'ASSOCIACAO', 'CONVENIO', 'MIN A', 'ORG A', '01/02/2021', 'z'],
    ]),
    'siconv_convenio.csv.zip': csv([
        ['NR_CONVENIO', 'ID_PROPOSTA', 'SIT_CONVENIO', 'SUBSITUACAO_CONV', 'INSTRUMENTO_ATIVO', 'IND_ASSINADO', 'QTD_TA',
         'QTD_PRORROGA', 'DIA_ASSIN_CONV', 'DIA_PUBL_CONV', 'DIA_INIC_VIGENC_CONV', 'DIA_FIM_VIGENC_CONV',
         'DIA_FIM_VIGENC_ORIGINAL_CONV', 'VL_GLOBAL_CONV', 'VALOR_GLOBAL_ORIGINAL_CONV', 'VL_REPASSE_CONV',
         'VL_CONTRAPARTIDA_CONV', 'VL_EMPENHADO_CONV', 'VL_DESEMBOLSADO_CONV'],
        ['10', '1', 'Em execução', '', 'SIM', 'SIM', '1', '0', '15/03/2021', '20/03/2021', '15/03/2021', '31/12/2023',
         '31/12/2022', '120000,50', '120000,50', '100000', '20000,50', '100000', '75000,25'],
        ['11', '1', 'Proposta', '', 'NÃO', 'NÃO', '0', '0', '', '', '', '', '', '0', '0', '0', '0', '0', '0'],
        ['20', '2', 'Em execução', '', 'SIM', 'SIM', '0', '0', '01/01/2021', '', '01/01/2021', '31/12/2025', '', '1', '1', '1', '0', '0', '0'],
        ['30', '3', 'Convênio Anulado', '', 'NÃO', 'SIM', '0', '0', '01/02/2022', '05/02/2022', '01/02/2022', '31/12/2024',
         '31/12/2024', '500000', '500000', '480000', '20000', '0', '0'],
    ]),
    'siconv_emenda.csv.zip': csv([
        ['ID_PROPOSTA', 'NR_EMENDA', 'TIPO_PARLAMENTAR', 'IND_IMPOSITIVO'],
        ['1', '123', 'INDIVIDUAL', 'SIM'], ['1', '123', 'INDIVIDUAL', 'SIM'], ['2', '9', 'BANCADA', 'NÃO'],
    ]),
    'siconv_desembolso.csv.zip': csv([
        ['ID_DESEMBOLSO', 'NR_CONVENIO', 'DATA_DESEMBOLSO', 'VL_DESEMBOLSADO'],
        ['100', '10', '05/05/2021', '50000,25'], ['101', '10', '10/01/2022', '25000'], ['200', '20', '01/03/2021', '1'],
    ]),
}


def resposta(conteudo, headers=None):
    r = Mock(status_code=200, content=conteudo, headers=headers or {})
    r.json.side_effect = lambda: json.loads(conteudo)
    return r


class PortalCsv:
    """Repositório de downloads com a carga publicada trocável."""

    def __init__(self, carga='17/07/2026 06:30:47'):
        self.carga, self.urls = carga, []

    def conteudo(self, nome):
        if nome == disc.DATA_CARGA:
            return zip_texto('data_carga_siconv.csv', f'﻿data_carga\n{self.carga}\n')
        return zip_texto(nome[:-4], TABELAS[nome])

    def get(self, url, timeout=None):
        self.urls.append(url)
        return resposta(self.conteudo(url.rsplit('/', 1)[1]))


def recorte(caminho):
    return pd.read_csv(caminho, sep=';', dtype=str, keep_default_na=False, compression='gzip')


class BronzeDiscricionarias(unittest.TestCase):
    def test_preserva_somente_o_recorte_pb_com_origem_rastreavel(self):
        portal = PortalCsv()
        with tempfile.TemporaryDirectory() as temp:
            caminhos = disc.extrair(portal, Path(temp))
            self.assertEqual(set(caminhos), {disc.DATA_CARGA, *disc.TABELAS})
            self.assertEqual(list(recorte(caminhos['siconv_proposta_pb.csv.gz']).ID_PROPOSTA), ['1', '3', '4'])
            self.assertEqual(list(recorte(caminhos['siconv_convenio_pb.csv.gz']).NR_CONVENIO), ['10', '11', '30'])
            self.assertEqual(list(recorte(caminhos['siconv_desembolso_pb.csv.gz']).ID_DESEMBOLSO), ['100', '101'])
            self.assertEqual(recorte(caminhos['siconv_proposta_pb.csv.gz']).OBJETO_PROPOSTA[0], 'Praça; reforma')
            indice = json.loads((Path(temp) / 'ref' / f'{disc.FONTE}_bronze.json').read_text(encoding='utf-8'))
            origem = indice['cargas'][indice['atual']]['origem']['siconv_proposta_pb.csv.gz']
            self.assertEqual(origem['sha256_original'], sha256(portal.conteudo('siconv_proposta.csv.zip')))
            self.assertEqual((origem['linhas_originais'], origem['linhas_recorte']), (4, 3))
            p = caminhos['siconv_proposta_pb.csv.gz']
            manifesto = json.loads(p.with_name(p.name + '.manifesto.json').read_text(encoding='utf-8'))
            self.assertTrue(manifesto['origem'].startswith('recorte_pb:'))

    def test_recorte_e_deterministico(self):
        original = PortalCsv().conteudo('siconv_proposta.csv.zip')
        self.assertEqual(disc.recortar(original, 'UF_PROPONENTE', {'PB'}), disc.recortar(original, 'UF_PROPONENTE', {'PB'}))
        self.assertEqual(gzip.decompress(disc.recortar(original, 'UF_PROPONENTE', {'PB'})[0]).count(b'\n'), 4)

    def test_mesma_carga_nao_baixa_tabelas_de_novo(self):
        portal = PortalCsv()
        with tempfile.TemporaryDirectory() as temp:
            disc.extrair(portal, Path(temp))
            portal.urls.clear()
            disc.extrair(portal, Path(temp))
            self.assertEqual(portal.urls, [disc.BASE_URL + disc.DATA_CARGA])

    def test_nova_carga_gera_nova_geracao_e_preserva_anterior(self):
        portal = PortalCsv()
        with tempfile.TemporaryDirectory() as temp:
            antiga = disc.extrair(portal, Path(temp))
            portal.carga = '20/11/2026 06:30:00'
            nova = disc.extrair(portal, Path(temp))
            self.assertTrue(antiga['siconv_convenio_pb.csv.gz'].exists())
            self.assertNotEqual(antiga[disc.DATA_CARGA], nova[disc.DATA_CARGA])
            indice = json.loads((Path(temp) / 'ref' / f'{disc.FONTE}_bronze.json').read_text(encoding='utf-8'))
            self.assertEqual(set(indice['cargas']), {'17/07/2026 06:30:47', '20/11/2026 06:30:00'})

    def test_indice_dos_zips_nacionais_e_arquivado(self):
        with tempfile.TemporaryDirectory() as temp:
            antigo = Path(temp) / 'ref' / f'{disc.FONTE}_bronze.json'
            antigo.parent.mkdir(parents=True)
            antigo.write_text(json.dumps({'atual': 'x', 'cargas': {'x': {'arquivos': {}}}}), encoding='utf-8')
            disc.extrair(PortalCsv(), Path(temp))
            self.assertTrue((Path(temp) / 'ref' / 'historico' / f'{disc.FONTE}_bronze_v1.json').exists())

    def test_carga_trocada_durante_download_nao_vira_geracao(self):
        portal = PortalCsv()
        original = portal.get

        def troca(url, timeout=None):
            if url.endswith('siconv_desembolso.csv.zip'):
                portal.carga = '18/07/2026 06:30:00'
            return original(url, timeout)
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ViolacaoContrato):
                disc.extrair(Mock(get=troca), Path(temp))
            with self.assertRaises(ViolacaoContrato):
                disc.verificar(Path(temp))

    def test_download_truncado_e_falha(self):
        sessao = Mock()
        sessao.get.return_value = resposta(b'parcial', headers={'Content-Length': '999'})
        with tempfile.TemporaryDirectory() as temp, patch('time.sleep'), self.assertRaises(FalhaConsulta):
            disc.extrair(sessao, Path(temp))

    def test_conexao_cortada_no_corpo_e_repetida(self):
        portal = PortalCsv()
        original, cortes = portal.get, []

        def corta_uma_vez(url, timeout=None):
            if url.endswith('siconv_proposta.csv.zip') and not cortes:
                cortes.append(url)
                raise requests.exceptions.ChunkedEncodingError('IncompleteRead')
            return original(url, timeout)
        with tempfile.TemporaryDirectory() as temp, patch('time.sleep'):
            caminhos = disc.extrair(Mock(get=corta_uma_vez), Path(temp))
            self.assertEqual(len(cortes), 1)
            self.assertIn('siconv_proposta_pb.csv.gz', caminhos)

    def test_offline_sem_bronze_bloqueia(self):
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(ViolacaoContrato):
            disc.verificar(Path(temp))


class SilverDiscricionarias(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.silver = disc.transformar(disc.extrair(PortalCsv(), Path(cls.temp.name)))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_instrumentos_municipais_assinados_tipados(self):
        inst = self.silver['silver/transferegov_instrumentos'].set_index('nr_convenio')
        self.assertEqual(list(inst.index), ['10', '30'])  # sem pré-convênio, SP nem OSC
        self.assertEqual(inst.loc['10', 'valor_global'], 120000.50)
        self.assertEqual(inst.loc['10', 'data_assinatura'], pd.Timestamp(2021, 3, 15))
        self.assertTrue(inst.loc['10', 'origem_emenda'] and inst.loc['10', 'emenda_individual'])
        self.assertFalse(inst.loc['30', 'origem_emenda'])
        self.assertEqual(inst.loc['10', 'data_carga'], '17/07/2026 06:30:47')

    def test_desembolsos_e_mapa_cnpj(self):
        self.assertEqual(list(self.silver['silver/transferegov_desembolsos'].valor_desembolsado), [50000.25, 25000.0])
        mapa = self.silver['ref/transferegov_cnpj_municipio']
        self.assertEqual(dict(zip(mapa.cnpj, mapa.codigo_ibge)), {'08778326000156': JP, '08924037000118': CONDE})

    def test_painel_por_data_do_evento_com_zero_confirmado(self):
        quadro = disc.painel(self.silver, {JP, CONDE, AGUA_BRANCA}, list(range(2020, 2025))).set_index(['codigo_ibge', 'ano'])
        self.assertEqual(len(quadro), 15)
        self.assertEqual(quadro.loc[(JP, 2021), 'transferegov_instrumentos_assinados'], 1)
        self.assertEqual(quadro.loc[(JP, 2021), 'transferegov_valor_desembolsado'], 50000.25)
        self.assertEqual(quadro.loc[(JP, 2022), 'transferegov_valor_desembolsado'], 25000)
        self.assertEqual(list(quadro.loc[JP, 'transferegov_instrumentos_vigentes']), [0, 1, 1, 1, 0])
        self.assertEqual(quadro.loc[(CONDE, 2022), 'transferegov_instrumentos_assinados'], 1)
        # Anulado conta como vigente: a anulação posterior é desfecho, não contexto do ano.
        self.assertEqual(list(quadro.loc[CONDE, 'transferegov_instrumentos_vigentes']), [0, 0, 1, 1, 1])
        self.assertEqual(quadro.loc[(JP, 2021), 'transferegov_valor_global_assinado'], 120000.50)
        self.assertEqual(set(disc.TEMPORALIDADE), set(quadro.columns) - {'cobertura_transferegov_discricionarias'})
        self.assertTrue((quadro.loc[AGUA_BRANCA].drop(columns='cobertura_transferegov_discricionarias') == 0).all().all())

    def test_desfechos_ficam_no_silver_como_resultado(self):
        inst = self.silver['silver/transferegov_instrumentos'].set_index('nr_convenio')
        self.assertTrue(inst.loc['30', 'resultado_anulado'])
        self.assertFalse(inst.loc['10', 'resultado_anulado'])
        self.assertTrue(inst.loc['10', 'resultado_prorrogado'])  # fim 2023 > fim original 2022
        self.assertFalse(inst.loc['30', 'resultado_prorrogado'])
        self.assertEqual(inst.loc['30', 'valor_global_assinatura'], 500000)

    def test_cnpj_em_dois_municipios_bloqueia(self):
        dados = dict(TABELAS)
        dados['siconv_proposta.csv.zip'] = TABELAS['siconv_proposta.csv.zip'].replace('08924037000118', '08778326000156')
        with tempfile.TemporaryDirectory() as temp, patch.dict(TABELAS, dados), self.assertRaises(ViolacaoContrato):
            disc.transformar(disc.extrair(PortalCsv(), Path(temp)))


class ApiEspeciais:
    """PostgREST simulado: filtros eq./in., ordenação, offset e limit."""

    TABELAS = {
        'plano_acao_especial': [
            {'id_plano_acao': 1, 'uf_beneficiario_plano_acao': 'PB', 'cnpj_beneficiario_plano_acao': '08778326000156',
             'nome_beneficiario_plano_acao': 'JOAO PESSOA', 'ano_plano_acao': 2021, 'valor_custeio_plano_acao': 0,
             'valor_investimento_plano_acao': 100.0},
            {'id_plano_acao': 2, 'uf_beneficiario_plano_acao': 'PB', 'cnpj_beneficiario_plano_acao': '08761124000100',
             'nome_beneficiario_plano_acao': 'ESTADO DA PARAIBA', 'ano_plano_acao': 2021, 'valor_custeio_plano_acao': 0,
             'valor_investimento_plano_acao': 999.0},
            {'id_plano_acao': 3, 'uf_beneficiario_plano_acao': 'PB', 'cnpj_beneficiario_plano_acao': '08924037000118',
             'nome_beneficiario_plano_acao': 'MUNICIPIO DO CONDE', 'ano_plano_acao': 2023, 'valor_custeio_plano_acao': 10.0,
             'valor_investimento_plano_acao': 40.0}],
        'empenho_especial': [
            {'id_empenho': 10, 'id_plano_acao': 1, 'uf_beneficiario_empenho': 'PB', 'numero_empenho': 'NE10',
             'situacao_empenho': 4, 'data_emissao_empenho': '2021-05-01', 'valor_empenho': 100.0},
            {'id_empenho': 11, 'id_plano_acao': 2, 'uf_beneficiario_empenho': 'PB', 'numero_empenho': 'NE11',
             'situacao_empenho': 4, 'data_emissao_empenho': '2021-05-01', 'valor_empenho': 999.0},
            {'id_empenho': 12, 'id_plano_acao': 3, 'uf_beneficiario_empenho': 'PB', 'numero_empenho': 'NE12',
             'situacao_empenho': 1, 'data_emissao_empenho': '2023-06-01', 'valor_empenho': 50.0}],
        'documento_habil_especial': [{'id_dh': 110, 'id_empenho': 10, 'valor_dh': 100.0},
                                     {'id_dh': 111, 'id_empenho': 11, 'valor_dh': 999.0},
                                     {'id_dh': 112, 'id_empenho': 12, 'valor_dh': 50.0}],
        'ordem_pagamento_ordem_bancaria_especial': [
            {'id_op_ob': 1110, 'id_dh': 110, 'situacao_op': 5, 'data_emissao_ob': '2022-01-10'},
            {'id_op_ob': 1111, 'id_dh': 111, 'situacao_op': 5, 'data_emissao_ob': '2021-07-01'}],
    }

    def __init__(self, falhar_em=None):
        self.falhar_em, self.chamadas = falhar_em, []

    def get(self, url, params=None, timeout=None):
        recurso = url.rsplit('/', 1)[1]
        self.chamadas.append((recurso, dict(params)))
        if recurso == self.falhar_em:
            erro = Mock(status_code=404, text='', headers={})
            erro.raise_for_status.side_effect = requests.HTTPError('404')
            return erro
        linhas = self.TABELAS[recurso]
        for coluna, filtro in params.items():
            if not isinstance(filtro, str) or coluna == 'order':
                continue
            if filtro.startswith('eq.'):
                linhas = [l for l in linhas if str(l[coluna]) == filtro[3:]]
            elif filtro.startswith('in.('):
                ids = filtro[4:-1].split(',')
                linhas = [l for l in linhas if str(l[coluna]) in ids]
        linhas = sorted(linhas, key=lambda l: l[params['order']])[params['offset']:params['offset'] + params['limit']]
        return resposta(json.dumps(linhas).encode())


CAMPOS_PLANO = {'codigo_plano_acao': 'x', 'situacao_plano_acao': 'CIENTE', 'nome_parlamentar_emenda_plano_acao': 'P',
                'numero_emenda_parlamentar_plano_acao': '1', 'codigo_descricao_areas_politicas_publicas_plano_acao': 'A',
                'motivo_impedimento_plano_acao': None}
for _plano in ApiEspeciais.TABELAS['plano_acao_especial']:
    _plano.update({k: v for k, v in CAMPOS_PLANO.items() if k not in _plano})

MAPA = pd.DataFrame({'cnpj': ['08778326000156', '08924037000118'], 'codigo_ibge': [JP, CONDE]})


@patch.object(esp, 'LIMITE', 2)
@patch.object(esp, 'LOTE_IDS', 2)
@patch.object(esp, 'CONFIG', {'max_tentativas': 1, 'intervalo_requisicoes_segundos': 0})
class Especiais(unittest.TestCase):
    def test_cadeia_completa_filtrada_pela_api(self):
        api = ApiEspeciais()
        with tempfile.TemporaryDirectory() as temp:
            caminhos = esp.extrair(api, Path(temp))
            linhas = {r: sum(len(json.loads(p.read_bytes())) for p in ps) for r, ps in caminhos.items()}
            self.assertEqual(linhas, {'plano_acao_especial': 3, 'empenho_especial': 3,
                                      'documento_habil_especial': 3, 'ordem_pagamento_ordem_bancaria_especial': 2})
            self.assertEqual(api.chamadas[0], ('plano_acao_especial', {
                'uf_beneficiario_plano_acao': 'eq.PB', 'order': 'id_plano_acao', 'offset': 0, 'limit': 2}))
            filhos = [p for r, p in api.chamadas if r == 'documento_habil_especial']
            self.assertEqual([p['id_empenho'] for p in filhos], ['in.(10,11)', 'in.(10,11)', 'in.(12)'])

    def test_retomada_nao_repete_paginas_preservadas(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(FalhaConsulta):
                esp.extrair(ApiEspeciais(falhar_em='documento_habil_especial'), Path(temp))
            with self.assertRaises(ViolacaoContrato):
                esp.verificar(Path(temp))
            api = ApiEspeciais()
            esp.extrair(api, Path(temp))
            self.assertNotIn('plano_acao_especial', {r for r, _ in api.chamadas})
            api.chamadas.clear()
            esp.extrair(api, Path(temp))
            self.assertEqual(api.chamadas, [])

    def test_refresh_preserva_indice_anterior(self):
        with tempfile.TemporaryDirectory() as temp:
            esp.extrair(ApiEspeciais(), Path(temp))
            api = ApiEspeciais()
            esp.extrair(api, Path(temp), refresh=True)
            self.assertTrue(api.chamadas)
            self.assertEqual(len(list((Path(temp) / 'ref' / 'historico').glob(f'{esp.FONTE}_bronze_*.json'))), 1)

    def test_silver_exclui_estado_e_so_paga_com_ordem_bancaria(self):
        with tempfile.TemporaryDirectory() as temp:
            silver = esp.transformar(esp.extrair(ApiEspeciais(), Path(temp)), MAPA)
            self.assertEqual(list(silver['silver/transferegov_especiais_planos'].codigo_ibge), [JP, CONDE])
            pagos = silver['silver/transferegov_especiais_pagamentos']
            self.assertEqual(list(pagos.id_dh), [110])  # 111 é do Estado; 112 não tem ordem bancária
            quadro = esp.painel(silver, {JP, CONDE}, list(range(2020, 2025))).set_index(['codigo_ibge', 'ano'])
            self.assertEqual(quadro.loc[(JP, 2022), 'transferegov_especiais_valor_pago'], 100.0)
            self.assertEqual(quadro.loc[(JP, 2021), 'transferegov_especiais_valor_pago'], 0)
            self.assertEqual(quadro.loc[(CONDE, 2023), 'transferegov_especiais_valor_planejado'], 50.0)

    def test_municipio_fora_do_mapa_bloqueia(self):
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(ViolacaoContrato):
            esp.transformar(esp.extrair(ApiEspeciais(), Path(temp)), MAPA.iloc[:1])


@patch.object(esp, 'CONFIG', {'max_tentativas': 1, 'intervalo_requisicoes_segundos': 0})
class Publicacao(unittest.TestCase):
    def test_gold_recebe_painel_com_status_e_silver(self):
        with tempfile.TemporaryDirectory() as temp:
            raiz = Path(temp)
            base, eventos = snapshot.transformar(snapshot.extrair(ROOT, raiz))
            referencia = base[['codigo_ibge', 'municipio', 'uf']].drop_duplicates()
            codigos, anos = set(referencia.codigo_ibge), list(range(2020, 2025))
            s_disc = disc.transformar(disc.extrair(PortalCsv(), raiz))
            s_esp = esp.transformar(esp.extrair(ApiEspeciais(), raiz), s_disc['ref/transferegov_cnpj_municipio'])
            tabelas = construir(base, eventos, referencia, adicionais={
                'transferegov_discricionarias': (disc.painel(s_disc, codigos, anos), s_disc, disc.TEMPORALIDADE),
                'transferegov_especiais': (esp.painel(s_esp, codigos, anos), s_esp, esp.TEMPORALIDADE)})
            gold = tabelas['gold/base_municipio_ano'].set_index(['codigo_ibge', 'ano'])
            self.assertEqual(len(gold), 1115)
            self.assertEqual(gold.loc[(JP, 2021), 'transferegov_valor_desembolsado'], 50000.25)
            self.assertIn('silver/transferegov_especiais_pagamentos', tabelas)
            obs = tabelas['silver/observacoes_municipio_ano']
            linha = obs[(obs.codigo_ibge == AGUA_BRANCA) & (obs.ano == 2021) & (obs.variavel == 'transferegov_instrumentos_assinados')]
            self.assertEqual(linha.status.item(), 'sem_registro_confirmado')
            auditoria = tabelas['gold/auditoria_cobertura'].drop_duplicates('variavel').set_index('variavel')
            self.assertEqual(auditoria.loc['transferegov_valor_repasse_atual', 'status_temporal'], 'somente_descritiva')
            self.assertEqual(auditoria.loc['transferegov_instrumentos_vigentes', 'status_temporal'], 'apta_regra_legal')
            self.assertEqual(auditoria.loc['pib', 'status_temporal'], 'pendente_validacao_publicacao')
            manifesto = publicar(tabelas, raiz, {'teste': True})
            self.assertNotIn('Transferegov', manifesto['pendencias'])
            self.assertFalse(manifesto['apto_para_treino_temporal'])
            self.assertIn('transferegov_valor_desembolsado', manifesto['variaveis_aptas_treino_temporal'])
            self.assertNotIn('transferegov_especiais_valor_planejado', manifesto['variaveis_aptas_treino_temporal'])

    def test_variavel_sem_classificacao_temporal_bloqueia(self):
        with tempfile.TemporaryDirectory() as temp:
            raiz = Path(temp)
            base, eventos = snapshot.transformar(snapshot.extrair(ROOT, raiz))
            referencia = base[['codigo_ibge', 'municipio', 'uf']].drop_duplicates()
            s_disc = disc.transformar(disc.extrair(PortalCsv(), raiz))
            painel = disc.painel(s_disc, set(referencia.codigo_ibge), list(range(2020, 2025)))
            incompleta = dict(list(disc.TEMPORALIDADE.items())[:-1])
            with self.assertRaises(ViolacaoContrato):
                construir(base, eventos, referencia, adicionais={'transferegov_discricionarias': (painel, s_disc, incompleta)})

    def test_sem_transferegov_gold_nao_muda(self):
        with tempfile.TemporaryDirectory() as temp:
            base, eventos = snapshot.transformar(snapshot.extrair(ROOT, Path(temp)))
            referencia = base[['codigo_ibge', 'municipio', 'uf']].drop_duplicates()
            gold = construir(base, eventos, referencia)['gold/base_municipio_ano']
            self.assertFalse([c for c in gold.columns if 'transferegov' in c])


class Cli(unittest.TestCase):
    def test_especiais_exige_discricionarias(self):
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(SystemExit):
            main(['--data-dir', temp, '--sources', 'snapshot', 'transferegov_especiais', '--offline'])

    def test_fonte_sem_transformacao_exige_bronze_only(self):
        with tempfile.TemporaryDirectory() as temp, patch('requests.Session.get') as rede:
            with self.assertRaises(SystemExit):
                main(['--data-dir', temp, '--sources', 'snapshot', 'siconfi'])
            rede.assert_not_called()

    def test_bronze_only_nao_aceita_fonte_publicada(self):
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(SystemExit):
            main(['--data-dir', temp, '--bronze-only', '--sources', 'snapshot'])

    def test_offline_sem_bronze_nao_chama_rede(self):
        with tempfile.TemporaryDirectory() as temp, patch('requests.Session.get') as rede:
            with self.assertRaises(SystemExit) as saida:
                main(['--data-dir', temp, '--offline', '--sources', 'snapshot',
                      'transferegov_discricionarias', 'transferegov_especiais'])
            self.assertEqual(saida.exception.code, 1)
            rede.assert_not_called()


if __name__ == '__main__':
    unittest.main()
