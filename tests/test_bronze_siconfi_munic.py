"""Bronze do SICONFI e da MUNIC sem rede: escolha do RGF, paginação, falhas e revisões."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from src.etl_municipal.core.contratos import ViolacaoContrato
from src.etl_municipal.fontes import siconfi, munic
from src.etl_municipal.fontes.ibge_territorial import CATALOGO_URL

CODIGOS = [str(2500000 + i) for i in range(1, 224)]
QUADRIMESTRAL, SEMESTRAL, SEM_RGF = CODIGOS[0], CODIGOS[1], CODIGOS[2]


def resposta(conteudo):
    r = Mock(status_code=200, content=conteudo, headers={})
    r.json.side_effect = lambda: json.loads(conteudo)
    return r


def falha_http():
    r = Mock(status_code=404, text='', headers={})
    r.raise_for_status.side_effect = requests.HTTPError('404')
    return r


class Siconfi:
    """API ORDS simulada para um exercício."""

    def __init__(self, falhar=None, outro_ente=None):
        self.falhar, self.outro_ente, self.chamadas = set(falhar or ()), outro_ente, []

    def get(self, url, params=None, timeout=None):
        if url == CATALOGO_URL:
            return resposta(json.dumps([{'id': int(c), 'nome': f'M{c}'} for c in CODIGOS]).encode())
        recurso, params = url.rsplit('/', 1)[1], dict(params)
        codigo = str(params['id_ente'])
        self.chamadas.append((recurso, params))
        if (recurso, codigo) in self.falhar:
            return falha_http()
        if recurso == 'extrato_entregas':
            itens = [] if codigo == SEM_RGF else [{
                'cod_ibge': int(codigo), 'instituicao': f'Prefeitura Municipal de M{codigo}',
                'entregavel': 'Relatório de Gestão Fiscal Simplificado' if codigo == SEMESTRAL else 'Relatório de Gestão Fiscal',
                'periodicidade': 'S' if codigo == SEMESTRAL else 'Q'}]
            return resposta(json.dumps({'items': itens, 'hasMore': False, 'limit': 5000}).encode())
        if recurso == 'dca':
            # Duas páginas para o primeiro município, para exercitar a paginação.
            mais = codigo == QUADRIMESTRAL and params['offset'] == 0
            ente = int(self.outro_ente == codigo) + int(codigo)
            corpo = {'items': [{'cod_ibge': ente, 'conta': params['offset']}], 'hasMore': mais, 'limit': 1}
            return resposta(json.dumps(corpo).encode())
        return resposta(json.dumps({'items': [{'cod_ibge': int(codigo)}], 'hasMore': False, 'limit': 5000}).encode())


@patch.object(siconfi, 'CONFIG', {'max_tentativas': 1, 'intervalo_requisicoes_segundos': 0})
class BronzeSiconfi(unittest.TestCase):
    def test_rgf_segue_a_periodicidade_entregue(self):
        api = Siconfi()
        with tempfile.TemporaryDirectory() as temp:
            caminhos = siconfi.extrair(api, Path(temp), anos=[2023])
            rgf = {p['id_ente']: p for r, p in api.chamadas if r == 'rgf'}
            self.assertEqual((rgf[QUADRIMESTRAL]['in_periodicidade'], rgf[QUADRIMESTRAL]['nr_periodo'],
                              rgf[QUADRIMESTRAL]['co_tipo_demonstrativo']), ('Q', 3, 'RGF'))
            self.assertEqual((rgf[SEMESTRAL]['in_periodicidade'], rgf[SEMESTRAL]['nr_periodo'],
                              rgf[SEMESTRAL]['co_tipo_demonstrativo']), ('S', 2, 'RGF Simplificado'))
            self.assertNotIn(SEM_RGF, rgf)
            self.assertEqual(rgf[QUADRIMESTRAL]['co_poder'], 'E')
            self.assertEqual(len(caminhos['extrato_entregas']), 223)
            self.assertEqual(len(caminhos['dca']), 224)  # o primeiro município tem duas páginas

    def test_falha_fica_registrada_e_retomada_so_repete_o_que_faltou(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ViolacaoContrato):
                siconfi.extrair(Siconfi(falhar={('dca', SEMESTRAL)}), Path(temp), anos=[2023])
            indice = json.loads((Path(temp) / 'ref' / 'siconfi_bronze.json').read_text(encoding='utf-8'))
            self.assertEqual(list(indice['falhas']), [f'{SEMESTRAL}-2023'])
            with self.assertRaises(ViolacaoContrato):
                siconfi.verificar(Path(temp))
            api = Siconfi()
            siconfi.extrair(api, Path(temp), anos=[2023])
            self.assertEqual({p['id_ente'] for _, p in api.chamadas}, {SEMESTRAL})
            api.chamadas.clear()
            siconfi.extrair(api, Path(temp), anos=[2023])
            self.assertEqual(api.chamadas, [])

    def test_resposta_de_outro_ente_nao_entra_no_bronze(self):
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(ViolacaoContrato):
            siconfi.extrair(Siconfi(outro_ente=QUADRIMESTRAL), Path(temp), anos=[2023])

    def test_mudanca_de_anos_inicia_nova_extracao(self):
        with tempfile.TemporaryDirectory() as temp:
            siconfi.extrair(Siconfi(), Path(temp), anos=[2023])
            api = Siconfi()
            siconfi.extrair(api, Path(temp), anos=[2023, 2024])
            self.assertTrue(any(p['an_referencia'] == 2024 for r, p in api.chamadas if r == 'extrato_entregas'))
            self.assertTrue((Path(temp) / 'ref' / 'historico').exists())


class Ftp:
    def __init__(self, bases):
        self.bases, self.urls = bases, []

    def get(self, url, timeout=None):
        self.urls.append(url)
        if url == munic.BASE_URL:
            return resposta(b'<a href="../">..</a><a href="2018/">2018/</a><a href="2019/">2019/</a><a href="2021/">2021/</a>')
        if url.endswith('/Base_de_Dados/'):
            ano = url.split('/')[-3]
            links = ''.join(f'<a href="{n}">{n}</a>' for n in self.bases[ano])
            return resposta(f'<a href="https://www.ibge.gov.br/">IBGE</a>{links}'.encode())
        return resposta(f'xlsx {url}'.encode())


class BronzeMunic(unittest.TestCase):
    def test_edicoes_autorizadas_ignoram_2022_e_anos_fora_do_contrato(self):
        html = b''.join(f'<a href="{ano}/">{ano}/</a>'.encode() for ano in (2019, 2020, 2021, 2022, 2023, 2024, 2025))
        self.assertEqual(munic.edicoes(html), [2019, 2020, 2021, 2023, 2024])

    def test_baixa_edicoes_a_partir_de_2019(self):
        ftp = Ftp({'2019': ['Base_MUNIC_2019_20210817.ods', 'Base_MUNIC_2019_20210817.xlsx'],
                   '2021': ['Base_MUNIC_2021.xlsx']})
        with tempfile.TemporaryDirectory() as temp:
            caminhos = munic.extrair(ftp, Path(temp))
            self.assertEqual(set(caminhos), {'edicao_2019', 'edicao_2021'})
            self.assertEqual(caminhos['edicao_2019'].name, 'Base_MUNIC_2019_20210817.xlsx')
            self.assertFalse(any('2018' in u for u in ftp.urls))

    def test_smoke_pode_limitar_edicoes_sem_baixar_as_demais(self):
        bases = {str(ano): [f'Base_MUNIC_{ano}.xlsx'] for ano in (2019, 2020, 2021, 2023, 2024)}
        class SmokeFtp(Ftp):
            def get(self, url, timeout=None):
                if url == munic.BASE_URL:
                    self.urls.append(url)
                    return resposta(''.join(f'<a href="{ano}/">{ano}/</a>' for ano in bases).encode())
                return super().get(url, timeout=timeout)
        ftp = SmokeFtp(bases)
        with tempfile.TemporaryDirectory() as temp:
            caminhos = munic.extrair(ftp, Path(temp), anos=[2019, 2024])
            self.assertEqual(set(caminhos), {'edicao_2019', 'edicao_2024'})
            self.assertFalse(any('/2020/' in u or '/2021/' in u or '/2023/' in u for u in ftp.urls))

    def test_manifesto_registra_versao_hash_tamanho_e_publicacao(self):
        ftp = Ftp({'2019': ['Base_MUNIC_2019_20210817.xlsx']})
        with tempfile.TemporaryDirectory() as temp:
            munic.extrair(ftp, Path(temp), anos=[2019])
            indice = json.loads((Path(temp) / 'ref' / 'munic_bronze.json').read_text(encoding='utf-8'))
            registro = indice['edicoes']['2019']
            self.assertEqual(registro['versao_base'], 'revisao_2021_08_17')
            self.assertEqual(registro['data_publicacao'], '2020-12-02')
            self.assertEqual(registro['data_publicacao_versao'], '2021-08-17')
            self.assertEqual(len(registro['sha256']), 64)
            self.assertGreater(registro['tamanho_bytes'], 0)
            self.assertEqual(registro['status_versao'], 'revisao_unica_disponivel')
            self.assertFalse(registro['original_disponivel'])
            self.assertFalse(registro['original_bytes_disponiveis'])
            self.assertEqual(registro['escopo_correcao_oficial'], 'MREG0151,MREG0152,MREG0153')
            self.assertTrue(registro['url_nota_oficial'].startswith('https://www.ibge.gov.br/'))

    def test_revisao_entra_sem_apagar_a_anterior(self):
        bases = {'2019': ['Base_MUNIC_2019.xlsx'], '2021': ['Base_MUNIC_2021.xlsx']}
        with tempfile.TemporaryDirectory() as temp:
            antiga = munic.extrair(Ftp(bases), Path(temp))['edicao_2021']
            ftp = Ftp({**bases, '2021': ['Base_MUNIC_2021_20240425.xlsx']})
            nova = munic.extrair(ftp, Path(temp))['edicao_2021']
            self.assertNotEqual(antiga, nova)
            self.assertTrue(antiga.exists())
            indice = json.loads((Path(temp) / 'ref' / 'munic_bronze.json').read_text(encoding='utf-8'))
            self.assertEqual([h['nome'] for h in indice['historico']], ['Base_MUNIC_2021.xlsx'])
            self.assertFalse(any(u.endswith('Base_MUNIC_2019.xlsx') for u in ftp.urls))

    def test_base_ambigua_bloqueia(self):
        ftp = Ftp({'2019': ['Base_MUNIC_2019.xlsx', 'Base_MUNIC_2019_20210817.xlsx'], '2021': ['Base_MUNIC_2021.xlsx']})
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(ViolacaoContrato):
            munic.extrair(ftp, Path(temp))


if __name__ == '__main__':
    unittest.main()
