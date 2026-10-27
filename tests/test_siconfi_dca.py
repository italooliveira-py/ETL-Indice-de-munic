"""DCA, Anexo I-C, no recorte de apoio ao Transferegov: leiautes, nulos e cruzamentos."""
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.etl_municipal.core.contratos import ViolacaoContrato
from src.etl_municipal.fontes import siconfi

JP, CONDE = '2507507', '2504603'
BRUTA = 'Receitas Brutas Realizadas'


def dca(codigo, ano, contas, *, bruta=1000.0, fundeb=100.0):
    linhas = [('ReceitasExcetoIntraOrcamentarias', BRUTA, bruta),
              ('ReceitasExcetoIntraOrcamentarias', 'Deduções - FUNDEB', fundeb)]
    linhas += [('RO' + conta, BRUTA, valor) for conta, valor in contas.items()]
    return [{'cod_ibge': int(codigo), 'exercicio': ano, 'anexo': 'DCA-Anexo I-C', 'cod_conta': conta,
             'conta': conta, 'coluna': coluna, 'valor': valor} for conta, coluna, valor in linhas]


def caminhos(pasta, paginas):
    saida = {'dca': [], 'extrato_entregas': []}
    for n, itens in enumerate(paginas):
        arquivo = Path(pasta) / f'dca_{n}.json'
        arquivo.write_text(json.dumps({'items': itens, 'hasMore': False}), encoding='utf-8')
        saida['dca'].append(arquivo)
    return saida


class SilverDca(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.silver = siconfi.transformar_dca(caminhos(cls.temp.name, [
            # 2021: leiaute antigo; a conta-filha não pode ser somada de novo.
            dca(JP, 2021, {'1.7.1.8.10.0.0': 30, '1.7.1.8.10.9.0': 30, '2.4.1.8.10.0.0': 70, '1.7.2.8.10.0.0': 5}),
            dca(JP, 2023, {'1.7.1.7.00.0.0': 10, '2.4.1.4.00.0.0': 40, '2.4.1.9.51.0.0': 25}),
            dca(CONDE, 2023, {}, bruta=500, fundeb=0),
        ]))
        cls.municipio = cls.silver['silver/siconfi_dca_receita_municipio'].set_index(['codigo_ibge', 'ano'])

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_receita_liquida_desconta_deducoes(self):
        self.assertEqual(self.municipio.loc[(JP, 2023), 'receita_liquida'], 900)

    def test_soma_so_agregadoras_nos_dois_leiautes(self):
        self.assertEqual(self.municipio.loc[(JP, 2021), 'convenios_uniao'], 100)
        self.assertEqual(self.municipio.loc[(JP, 2021), 'convenios_estado'], 5)
        self.assertEqual(self.municipio.loc[(JP, 2023), 'convenios_uniao'], 50)
        self.assertEqual(self.municipio.loc[(JP, 2023), 'transferencia_especial'], 25)

    def test_conta_inexistente_no_leiaute_e_nula_e_ausente_declarada_e_zero(self):
        self.assertTrue(pd.isna(self.municipio.loc[(JP, 2021), 'transferencia_especial']))
        self.assertEqual(self.municipio.loc[(CONDE, 2023), 'transferencia_especial'], 0)
        self.assertEqual(self.municipio.loc[(CONDE, 2023), 'convenios_uniao'], 0)

    def test_natureza_fora_do_leiaute_do_ano_bloqueia(self):
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(ViolacaoContrato):
            siconfi.transformar_dca(caminhos(temp, [dca(JP, 2023, {'1.7.1.8.10.0.0': 30})]))

    def test_painel_cruza_com_transferegov(self):
        transferegov = pd.DataFrame({'codigo_ibge': [JP, JP, CONDE, CONDE], 'ano': [2021, 2023, 2021, 2023],
                                     'transferegov_valor_desembolsado': [60.0, 50.0, 0.0, 0.0],
                                     'transferegov_especiais_valor_pago': [0.0, 25.0, 0.0, 30.0]})
        quadro = siconfi.painel_dca(self.silver, {JP, CONDE}, [2021, 2023], transferegov).set_index(['codigo_ibge', 'ano'])
        self.assertEqual(quadro.loc[(JP, 2021), 'dca_convenios_uniao_fora_transferegov'], 40)
        self.assertEqual(quadro.loc[(JP, 2023), 'dca_pix_divergente'], 0)
        self.assertEqual(quadro.loc[(CONDE, 2023), 'dca_pix_divergente'], 1)  # pago no Transferegov, zero na DCA
        self.assertTrue(pd.isna(quadro.loc[(JP, 2021), 'dca_pix_divergente']))  # conta não existia
        self.assertTrue(quadro.loc[(CONDE, 2021)].isna().all())  # DCA não entregue
        self.assertAlmostEqual(quadro.loc[(JP, 2023), 'dca_dependencia_convenios_uniao'], 50 / 900)

    def test_sem_transferegov_nao_publica_cruzamentos(self):
        quadro = siconfi.painel_dca(self.silver, {JP, CONDE}, [2021, 2023])
        self.assertEqual(set(quadro.columns) - {'codigo_ibge', 'ano'}, set(siconfi.TEMPORALIDADE_DCA))


if __name__ == '__main__':
    unittest.main()
