"""Bronze do Transferegov sem rede: bytes originais, retomada e gerações."""
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from etl_confiabilidade import FalhaConsulta
from src.etl_municipal.core.contratos import ViolacaoContrato
from src.etl_municipal.fontes import transferegov_discricionarias as disc
from src.etl_municipal.fontes import transferegov_especiais as esp
from src.etl_municipal.__main__ import main


def zip_texto(nome, texto):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as arquivo:
        arquivo.writestr(nome, texto)
    return buffer.getvalue()


def resposta(conteudo, headers=None):
    r = Mock(status_code=200, content=conteudo, headers=headers or {})
    r.json.side_effect = lambda: json.loads(conteudo)
    return r


class PortalCsv:
    """Repositório de downloads com a carga publicada trocável."""

    def __init__(self, carga='17/07/2026 06:30:47'):
        self.carga, self.urls = carga, []

    def get(self, url, timeout=None):
        self.urls.append(url)
        nome = url.rsplit('/', 1)[1]
        if nome == disc.DATA_CARGA:
            return resposta(zip_texto('data_carga_siconv.csv', f'﻿data_carga\n{self.carga}\n'))
        return resposta(zip_texto(nome[:-4], f'{nome};{self.carga}'))


class Discricionarias(unittest.TestCase):
    def test_preserva_zips_nacionais_sem_recorte(self):
        portal = PortalCsv()
        with tempfile.TemporaryDirectory() as temp:
            caminhos = disc.extrair(portal, Path(temp))
            self.assertEqual(set(caminhos), {disc.DATA_CARGA, *disc.TABELAS})
            proposta = caminhos['siconv_proposta.csv.zip']
            self.assertEqual(proposta.read_bytes(), zip_texto('siconv_proposta.csv', 'siconv_proposta.csv.zip;17/07/2026 06:30:47'))
            manifesto = json.loads(proposta.with_name(proposta.name + '.manifesto.json').read_text(encoding='utf-8'))
            self.assertEqual(manifesto['origem'], disc.BASE_URL + 'siconv_proposta.csv.zip')

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
            self.assertNotEqual(antiga['siconv_convenio.csv.zip'], nova['siconv_convenio.csv.zip'])
            self.assertTrue(antiga['siconv_convenio.csv.zip'].exists())
            indice = json.loads((Path(temp) / 'ref' / f'{disc.FONTE}_bronze.json').read_text(encoding='utf-8'))
            self.assertEqual(set(indice['cargas']), {'17/07/2026 06:30:47', '20/11/2026 06:30:00'})
            self.assertEqual(indice['atual'], '20/11/2026 06:30:00')

    def test_carga_trocada_durante_download_nao_vira_geracao(self):
        portal = PortalCsv()
        original = portal.get

        def troca(url, timeout=None):
            if url.endswith('siconv_emenda.csv.zip'):
                portal.carga = '18/07/2026 06:30:00'
            return original(url, timeout)
        sessao = Mock(get=troca)
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ViolacaoContrato):
                disc.extrair(sessao, Path(temp))
            with self.assertRaises(ViolacaoContrato):
                disc.verificar(Path(temp))

    def test_download_truncado_e_falha(self):
        sessao = Mock()
        sessao.get.return_value = resposta(b'parcial', headers={'Content-Length': '999'})
        with tempfile.TemporaryDirectory() as temp, patch('time.sleep'), self.assertRaises(FalhaConsulta):
            disc.extrair(sessao, Path(temp))

    def test_offline_sem_bronze_bloqueia(self):
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(ViolacaoContrato):
            disc.verificar(Path(temp))


class ApiEspeciais:
    """PostgREST simulado: filtros eq./in., ordenação, offset e limit."""

    TABELAS = {
        'plano_acao_especial': [{'id_plano_acao': i, 'uf_beneficiario_plano_acao': 'PB'} for i in (1, 2, 3)],
        'empenho_especial': [{'id_empenho': i, 'id_plano_acao': 1, 'uf_beneficiario_empenho': 'PB'} for i in (10, 11, 12)],
        'documento_habil_especial': [{'id_dh': 100 + i, 'id_empenho': i} for i in (10, 11, 12)],
        'ordem_pagamento_ordem_bancaria_especial': [{'id_op_ob': 1000 + i, 'id_dh': 100 + i} for i in (10, 11, 12)],
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


@patch.object(esp, 'LIMITE', 2)
@patch.object(esp, 'LOTE_IDS', 2)
@patch.object(esp, 'CONFIG', {'max_tentativas': 1, 'intervalo_requisicoes_segundos': 0})
class Especiais(unittest.TestCase):
    def test_cadeia_completa_filtrada_pela_api(self):
        api = ApiEspeciais()
        with tempfile.TemporaryDirectory() as temp:
            caminhos = esp.extrair(api, Path(temp))
            linhas = {r: sum(len(json.loads(p.read_bytes())) for p in ps) for r, ps in caminhos.items()}
            self.assertEqual(set(linhas.values()), {3})
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
            self.assertNotIn('empenho_especial', {r for r, _ in api.chamadas})
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


class Cli(unittest.TestCase):
    def test_fonte_sem_transformacao_exige_bronze_only(self):
        with tempfile.TemporaryDirectory() as temp, patch('requests.Session.get') as rede:
            with self.assertRaises(SystemExit):
                main(['--data-dir', temp, '--sources', 'snapshot', 'transferegov_especiais'])
            rede.assert_not_called()

    def test_bronze_only_nao_aceita_fonte_publicada(self):
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(SystemExit):
            main(['--data-dir', temp, '--bronze-only', '--sources', 'snapshot'])

    def test_bronze_only_offline_sem_bronze_nao_chama_rede(self):
        with tempfile.TemporaryDirectory() as temp, patch('requests.Session.get') as rede:
            with self.assertRaises(SystemExit) as saida:
                main(['--data-dir', temp, '--bronze-only', '--offline',
                      '--sources', 'transferegov_discricionarias', 'transferegov_especiais'])
            self.assertEqual(saida.exception.code, 1)
            rede.assert_not_called()


if __name__ == '__main__':
    unittest.main()
