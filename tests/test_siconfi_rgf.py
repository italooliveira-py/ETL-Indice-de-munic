"""RGF, Anexo 1: razão declarada, harmonização da mudança de 2024 e publicação."""
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.etl_municipal.core.contratos import ViolacaoContrato
from src.etl_municipal.fontes import siconfi, snapshot
from src.etl_municipal.publicacao import construir

ROOT = Path(__file__).resolve().parents[1]
JP, CONDE = '2507507', '2504603'
TOTAL = 'TOTAL (ÚLTIMOS 12 MESES) (a)'


def anexo1(codigo, ano, periodicidade, *, bruta, dtp, rcl, acs=None, enf=None, rcl_acs=None, pct=None):
    linhas = [('DespesaComPessoalBruta', TOTAL, bruta), ('DespesaComPessoalTotal', 'Valor', dtp),
              ('DespesaComPessoalTotal', '% sobre a RCL Ajustada', round(dtp / rcl * 100, 2) if pct is None else pct),
              ('ReceitaCorrenteLiquidaLimiteLegal', 'Valor', rcl + (rcl_acs or 0)), ('ReceitaCorrenteLiquidaAjustada', 'Valor', rcl)]
    linhas += [(conta, coluna, valor) for conta, coluna, valor in [
        (siconfi.DEDUCAO_ACS, TOTAL, acs), (siconfi.DEDUCAO_ENFERMAGEM, TOTAL, enf), (siconfi.RCL_ACS, 'Valor', rcl_acs)]
        if valor is not None]
    return [{'cod_ibge': int(codigo), 'exercicio': ano, 'periodicidade': periodicidade, 'anexo': 'RGF-Anexo 01',
             'cod_conta': conta, 'coluna': coluna, 'valor': valor} for conta, coluna, valor in linhas]


def extrato(codigo, ano, periodicidade, status='HO'):
    return [{'cod_ibge': int(codigo), 'exercicio': ano, 'instituicao': f'Prefeitura Municipal {codigo}',
             'entregavel': 'Relatório de Gestão Fiscal' + (' Simplificado' if periodicidade == 'S' else ''),
             'periodicidade': periodicidade, 'periodo': siconfi.ULTIMO_PERIODO[periodicidade],
             'status_relatorio': status, 'data_status': f'{ano + 1}-01-30T10:00:00Z'}]


def caminhos(pasta, rgfs, extratos):
    saida = {'rgf': [], 'extrato_entregas': []}
    for recurso, paginas in [('rgf', rgfs), ('extrato_entregas', extratos)]:
        for n, itens in enumerate(paginas):
            arquivo = Path(pasta) / f'{recurso}_{n}.json'
            arquivo.write_text(json.dumps({'items': itens, 'hasMore': False}), encoding='utf-8')
            saida[recurso].append(arquivo)
    return saida


class SilverRgf(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.silver = siconfi.transformar_rgf(caminhos(cls.temp.name, [
            anexo1(JP, 2023, 'Q', bruta=60, dtp=54, rcl=100),
            anexo1(JP, 2024, 'Q', bruta=70, dtp=50, rcl=100, acs=10, enf=5, rcl_acs=20),
            anexo1(CONDE, 2024, 'S', bruta=45, dtp=45, rcl=100),
        ], [extrato(JP, 2023, 'Q'), extrato(JP, 2024, 'Q', 'RE'), extrato(CONDE, 2024, 'S')]))['silver/siconfi_rgf_pessoal']

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def linha(self, codigo, ano):
        return self.silver.set_index(['codigo_ibge', 'ano']).loc[(codigo, ano)]

    def test_harmonizacao_devolve_deducoes_novas(self):
        jp = self.linha(JP, 2024)
        self.assertAlmostEqual(jp.razao_declarada, 50.0)
        self.assertAlmostEqual(jp.razao_harmonizada, (50 + 10 + 5) / (100 + 20) * 100)

    def test_sem_contas_novas_harmonizada_igual_a_declarada(self):
        for codigo, ano in [(JP, 2023), (CONDE, 2024)]:
            linha = self.linha(codigo, ano)
            self.assertAlmostEqual(linha.razao_harmonizada, linha.razao_declarada)
            self.assertEqual(linha.deducao_acs, 0)

    def test_data_e_status_do_envio_pelo_extrato(self):
        self.assertEqual(self.linha(JP, 2024).status_relatorio, 'RE')
        self.assertEqual(self.linha(CONDE, 2024).periodicidade, 'S')
        self.assertEqual(self.linha(CONDE, 2024).data_envio, pd.Timestamp('2025-01-30T10:00:00Z'))

    def test_percentual_publicado_divergente_bloqueia(self):
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(ViolacaoContrato):
            siconfi.transformar_rgf(caminhos(temp, [anexo1(JP, 2023, 'Q', bruta=60, dtp=54, rcl=100, pct=50.0)], []))

    def test_dois_rgfs_no_mesmo_ano_bloqueia(self):
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(ViolacaoContrato):
            siconfi.transformar_rgf(caminhos(temp, [anexo1(JP, 2023, 'Q', bruta=60, dtp=54, rcl=100),
                                                    anexo1(JP, 2023, 'S', bruta=60, dtp=54, rcl=100)], []))

    def test_painel_deixa_ausente_nulo_e_deducao_zero_antes_de_2024(self):
        quadro = siconfi.painel_rgf({'silver/siconfi_rgf_pessoal': self.silver}, {JP, CONDE}, [2023, 2024]) \
            .set_index(['codigo_ibge', 'ano'])
        self.assertTrue(quadro.loc[(CONDE, 2023)].isna().all())
        self.assertEqual(quadro.loc[(JP, 2023), 'rgf_deducoes_novas_pp'], 0)
        self.assertAlmostEqual(quadro.loc[(JP, 2024), 'rgf_deducoes_novas_pp'], 65 / 120 * 100 - 50)


class PublicacaoRgf(unittest.TestCase):
    def test_ausente_indisponivel_e_zero_nao_e_confirmado(self):
        with tempfile.TemporaryDirectory() as temp:
            base, eventos = snapshot.transformar(snapshot.extrair(ROOT, Path(temp)))
            referencia = base[['codigo_ibge', 'municipio', 'uf']].drop_duplicates()
            silver = siconfi.transformar_rgf(caminhos(temp, [anexo1(JP, 2023, 'Q', bruta=60, dtp=54, rcl=100)], []))
            painel = siconfi.painel_rgf(silver, set(referencia.codigo_ibge), list(range(2020, 2025)))
            tabelas = construir(base, eventos, referencia,
                                adicionais={'siconfi_rgf': (painel, silver, siconfi.TEMPORALIDADE_RGF)})
            obs = tabelas['silver/observacoes_municipio_ano']
            rgf = obs[obs.fonte == 'siconfi_rgf'].set_index(['codigo_ibge', 'ano', 'variavel']).status
            self.assertEqual(rgf.loc[(JP, 2023, 'rgf_deducoes_novas_pp')], 'observado')
            self.assertEqual(rgf.loc[(CONDE, 2023, 'rgf_pessoal_rcl_declarada')], 'indisponivel')
            self.assertNotIn('sem_registro_confirmado', set(rgf))
            self.assertIn('silver/siconfi_rgf_pessoal', tabelas)


if __name__ == '__main__':
    unittest.main()
