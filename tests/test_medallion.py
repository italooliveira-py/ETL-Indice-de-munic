"""Regressões da publicação, imutabilidade, grãos e temporalidade."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd

from src.etl_municipal.core.armazenamento import preservar, sha256
from src.etl_municipal.core.contratos import ViolacaoContrato, validar_painel, validar_numerica
from src.etl_municipal.fontes import snapshot, ibge_territorial, coleta_legada
from src.etl_municipal.publicacao import construir, publicar, COLUNAS_OBRAS
from src.etl_municipal.__main__ import main

ROOT = Path(__file__).resolve().parents[1]


class Bronze(unittest.TestCase):
    def test_retomada_nao_altera_bytes_nem_manifesto(self):
        with tempfile.TemporaryDirectory() as temp:
            raiz = Path(temp)
            p = preservar(raiz, 'fonte', 'pagina.json', b'{"a":1}', 'https://oficial')
            manifesto = p.with_name(p.name + '.manifesto.json')
            antes = manifesto.read_bytes()
            preservar(raiz, 'fonte', p.name, p.read_bytes(), 'https://oficial')
            self.assertEqual(manifesto.read_bytes(), antes)
            novo = preservar(raiz, 'fonte', p.name, b'{"a":2}', 'https://oficial')
            self.assertNotEqual(p.parent, novo.parent)
            self.assertEqual(p.read_bytes(), b'{"a":1}')

    def test_corrompido_bloqueia_retomada(self):
        with tempfile.TemporaryDirectory() as temp:
            p = preservar(Path(temp), 'fonte', 'pagina.json', b'original', 'https://oficial')
            p.write_bytes(b'corrompido')
            with self.assertRaises(ValueError):
                preservar(Path(temp), 'fonte', p.name, b'original', 'https://oficial')

    def test_nome_nao_pode_escapar_da_pasta(self):
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(ValueError):
            preservar(Path(temp), 'fonte', '../fora', b'1', 'origem')


class Publicacao(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        caminhos = snapshot.extrair(ROOT, Path(cls.temp.name))
        cls.base, cls.eventos = snapshot.transformar(caminhos)
        cls.ref = cls.base[['codigo_ibge', 'municipio', 'uf']].drop_duplicates()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def tabelas(self, base=None, eventos=None):
        return construir(self.base if base is None else base,
                         self.eventos if eventos is None else eventos, self.ref)

    def test_preserva_snapshot_e_remove_obras_apenas_do_gold(self):
        tabelas = self.tabelas()
        gold = tabelas['gold/base_municipio_ano']
        self.assertEqual(len(gold), 1115)
        self.assertFalse(COLUNAS_OBRAS & set(gold.columns))
        self.assertEqual(len(tabelas['silver/eventos_obrasgov']), 1638)
        self.assertEqual(len(tabelas['gold/base_municipio_ano_mvp']), 892)
        self.assertIn('total_obras', self.base)

    def test_2024_pib_nulo_com_flag_e_populacao_preservada(self):
        gold = self.tabelas()['gold/base_municipio_ano']
        atual = gold[gold.ano == 2024]
        self.assertTrue(atual[['pib', 'pib_per_capita']].isna().all().all())
        self.assertTrue((atual.status_pib == 'fora_periodo').all())
        self.assertEqual(atual.populacao.notna().sum(), self.base.loc[self.base.ano == 2024, 'populacao'].notna().sum())
        pd.testing.assert_series_equal(gold.pib[gold.ano == 2023].reset_index(drop=True),
                                       self.base.pib[self.base.ano == 2023].reset_index(drop=True))

    def test_falha_ausencia_nao_vira_zero(self):
        base = self.base.copy()
        base.loc[0, 'total_contratacoes'] = float('nan')
        gold = self.tabelas(base)['gold/base_municipio_ano']
        self.assertTrue(pd.isna(gold.loc[0, 'total_contratacoes']))

    def test_municipio_ano_ausente_bloqueia(self):
        with self.assertRaises(ViolacaoContrato):
            self.tabelas(self.base.iloc[1:])

    def test_chave_duplicada_bloqueia(self):
        with self.assertRaises(ViolacaoContrato):
            self.tabelas(pd.concat([self.base, self.base.iloc[:1]]))

    def test_municipio_estranho_bloqueia(self):
        base = self.base.copy()
        base.loc[0, 'codigo_ibge'] = '2599999'
        with self.assertRaises(ViolacaoContrato):
            self.tabelas(base)

    def test_codigo_de_seis_digitos_nao_e_completado(self):
        base = self.base.copy()
        base.loc[0, 'codigo_ibge'] = '250010'
        with self.assertRaises(ViolacaoContrato):
            self.tabelas(base)

    def test_evento_nao_precisa_ter_223_municipios(self):
        tabelas = self.tabelas(eventos=self.eventos.iloc[:1])
        self.assertEqual(len(tabelas['silver/eventos_obrasgov']), 1)

    def test_evento_duplicado_bloqueia(self):
        with self.assertRaises(ViolacaoContrato):
            self.tabelas(eventos=pd.concat([self.eventos, self.eventos.iloc[:1]]))

    def test_valor_impossivel_bloqueia(self):
        for valor in [-1, float('inf'), 'invalido']:
            with self.subTest(valor=valor), self.assertRaises(ViolacaoContrato):
                validar_numerica(pd.DataFrame({'area': [valor]}), 'area')

    def test_detalhe_tem_status_por_variavel_e_nao_inventa_data(self):
        detalhe = self.tabelas()['silver/observacoes_municipio_ano']
        self.assertTrue(detalhe.data_disponibilidade.isna().all())
        fora = detalhe[(detalhe.variavel == 'pib') & (detalhe.ano == 2024)]
        self.assertTrue((fora.status == 'fora_periodo').all())
        populacao = detalhe[(detalhe.variavel == 'populacao') & detalhe.valor.notna()]
        self.assertTrue((populacao.status == 'observado').all())

    def test_reexecucao_produz_mesmos_hashes(self):
        with tempfile.TemporaryDirectory() as temp:
            raiz = Path(temp)
            a = publicar(self.tabelas(), raiz, {'teste': True})
            b = publicar(self.tabelas(), raiz, {'teste': True})
            self.assertEqual(a['hashes'], b['hashes'])
            self.assertEqual(a['versao_gold'], b['versao_gold'])
            current = json.loads((raiz / 'gold/CURRENT.json').read_text())
            self.assertEqual(current['versao'], a['versao_gold'])
            self.assertFalse(a['apto_para_treino_temporal'])

    def test_publicacao_interrompida_preserva_ponteiro_anterior(self):
        with tempfile.TemporaryDirectory() as temp:
            raiz = Path(temp)
            publicar(self.tabelas(), raiz, {'teste': True})
            antes = (raiz / 'gold/CURRENT.json').read_bytes()
            with patch('src.etl_municipal.publicacao._parquet_atomico', side_effect=OSError('sem espaço')):
                with self.assertRaises(OSError):
                    publicar(self.tabelas(), raiz, {'teste': 'nova'})
            self.assertEqual((raiz / 'gold/CURRENT.json').read_bytes(), antes)

    def test_adaptador_coleta_real_confere_contagens_e_preserva_saida(self):
        with tempfile.TemporaryDirectory() as temp:
            raiz = Path(temp)
            saida = raiz / 'output'
            saida.mkdir()
            self.base.to_csv(saida / 'base_municipio_ano.csv', index=False)
            self.eventos.to_csv(saida / 'eventos_obrasgov.csv', index=False)
            resumo = dict(municipios=223, periodo=[2020, 2024], smoke_test=False,
                          linhas_base_municipio_ano=1115, eventos_obrasgov=1638)
            (saida / 'resumo_execucao.json').write_text(json.dumps(resumo))
            original = (saida / 'base_municipio_ano.csv').read_bytes()
            caminhos = coleta_legada.extrair(saida, raiz / 'data')
            base, eventos = coleta_legada.transformar(caminhos)
            self.assertEqual(len(self.tabelas(base, eventos)['gold/base_municipio_ano']), 1115)
            self.assertEqual((saida / 'base_municipio_ano.csv').read_bytes(), original)
            resumo['eventos_obrasgov'] = 1
            (saida / 'resumo_execucao.json').write_text(json.dumps(resumo))
            with self.assertRaises(ViolacaoContrato):
                coleta_legada.transformar(coleta_legada.extrair(saida, raiz / 'data'))

    def test_adaptador_coleta_rejeita_smoke(self):
        with tempfile.TemporaryDirectory() as temp:
            caminho = Path(temp) / 'resumo.json'
            caminho.write_text(json.dumps({'smoke_test': True}))
            with self.assertRaises(ViolacaoContrato):
                coleta_legada.transformar({'resumo_execucao.json': caminho})

    def test_offline_sem_bronze_territorial_nao_chama_rede(self):
        with tempfile.TemporaryDirectory() as temp, patch('requests.Session.get') as rede:
            with self.assertRaises(SystemExit):
                main(['--data-dir', temp, '--sources', 'snapshot', 'ibge_territorial', '--offline'])
            rede.assert_not_called()


class Territorial(unittest.TestCase):
    def test_preserva_bytes_originais_da_resposta(self):
        sessao = Mock()
        sessao.get.return_value = resposta = Mock(status_code=200, content=b'{ "a": 1 }')
        resposta.json.return_value = {'a': 1}
        with tempfile.TemporaryDirectory() as temp:
            caminhos = ibge_territorial.extrair(sessao, Path(temp))
            self.assertEqual(caminhos['dados'].read_bytes(), b'{ "a": 1 }')
            self.assertEqual(sessao.get.call_count, 3)
            ibge_territorial.extrair(sessao, Path(temp))
            self.assertEqual(sessao.get.call_count, 3)


if __name__ == '__main__':
    unittest.main()
