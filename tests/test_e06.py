"""Garantias do protocolo E06: partições do pacote, pipeline sem metadados, janelas sem futuro."""
import json
import unittest

import numpy as np
import pandas as pd

from src.e06 import dados as d
from src.e06 import experimento as x

CONFIG = d.ler_config()
PARTES = d.carregar(CONFIG)


class TestPacote(unittest.TestCase):
    def test_particoes_iguais_ao_manifesto_do_pacote(self):
        manifesto = pd.read_csv(d.ROOT / CONFIG['pacote'] / 'data' / 'split_manifest.csv').set_index('split')
        for nome, parte in PARTES.items():
            self.assertEqual(len(parte), manifesto.loc[nome, 'n'])
            self.assertEqual(int(parte[d.ALVO].sum()), manifesto.loc[nome, 'y1'])
        ids = pd.concat([p.nr_convenio for p in PARTES.values()])
        self.assertFalse(ids.duplicated().any())

    def test_conjuntos_m1_iguais_aos_do_pacote(self):
        pacote = json.loads((d.ROOT / CONFIG['pacote'] / 'data' / 'feature_sets.json').read_text(encoding='utf-8'))
        self.assertEqual(CONFIG['conjuntos']['M1'], pacote['M1'])
        self.assertEqual(CONFIG['conjuntos']['M1_plus'], pacote['M1_plus'])

    def test_nenhum_conjunto_usa_identificador_data_ou_alvo(self):
        proibidas = {'nr_convenio', 'codigo_ibge', 'data_assinatura', 'data_previsao', 'split', d.ALVO}
        for nome, colunas in CONFIG['conjuntos'].items():
            self.assertFalse(proibidas & set(colunas), nome)


class TestPipeline(unittest.TestCase):
    def test_pipeline_usa_so_as_colunas_do_conjunto(self):
        treino = PARTES['train']
        colunas = CONFIG['conjuntos']['M1_plus']
        m = x.criar_pipeline('logistica', {'l1_ratio': 0.0, 'C': 1.0}, colunas, CONFIG).fit(treino[colunas], treino[d.ALVO])
        entrada = m.named_steps['preparo'].feature_names_in_
        self.assertTrue(set(entrada) >= set(colunas))
        self.assertFalse({'nr_convenio', 'codigo_ibge', 'data_assinatura'} & set(entrada))

    def test_transformacoes_ajustadas_so_no_treino(self):
        treino, teste = PARTES['train'], PARTES['test']
        colunas = CONFIG['conjuntos']['M1_plus']
        m = x.criar_pipeline('svc', {'C': 1.0}, colunas, CONFIG).fit(treino[colunas], treino[d.ALVO])
        escala = m.named_steps['preparo'].named_transformers_['log'].named_steps['escala']
        valores = d.DerivadasHistorico(CONFIG['suavizacao_historico']).fit(treino, treino[d.ALVO]).transform(treino)
        esperado = np.log1p(valores[[c for c in colunas if c in d.EM_LOG]]).mean().to_numpy()
        np.testing.assert_allclose(escala.mean_, esperado)
        self.assertFalse(np.allclose(escala.mean_, np.log1p(teste[[c for c in colunas if c in d.EM_LOG]]).mean().to_numpy()))

    def test_conjuntos_b_treinam_com_as_derivadas(self):
        treino = PARTES['train']
        for conjunto in ('B1', 'B2'):
            colunas = CONFIG['conjuntos'][conjunto]
            m = x.criar_pipeline('logistica', {'l1_ratio': 0.0, 'C': 1.0}, colunas, CONFIG)
            m.fit(treino[x.entrada(colunas)], treino[d.ALVO])
            usadas = {n.split('__', 1)[1] for n in m.named_steps['preparo'].get_feature_names_out()}
            self.assertTrue(set(d.DERIVADAS) <= usadas, conjunto)
            if conjunto == 'B1':
                self.assertFalse(set(d.CONTAGENS) & usadas)

    def test_derivadas_nao_usam_o_alvo_da_linha(self):
        treino, teste = PARTES['train'], PARTES['test'].copy()
        t = d.DerivadasHistorico(5).fit(treino, treino[d.ALVO])
        antes = t.transform(teste)[d.DERIVADAS]
        teste[d.ALVO] = 1 - teste[d.ALVO]
        pd.testing.assert_frame_equal(antes, t.transform(teste)[d.DERIVADAS])

    def test_taxa_suavizada_vai_para_a_prevalencia_sem_historico(self):
        t = d.DerivadasHistorico(5).fit(PARTES['train'], PARTES['train'][d.ALVO])
        linha = PARTES['train'].iloc[[0]].copy()
        linha[['historico_instrumentos_maduros', 'historico_atrasados', 'historico_eventos_financeiros']] = 0
        saida = t.transform(linha)
        self.assertAlmostEqual(float(saida.taxa_atraso_hist.iloc[0]), t.prevalencia_)
        self.assertEqual(float(saida.sem_historico.iloc[0]), 1.0)
        self.assertEqual(float(saida.valor_medio_evento.iloc[0]), 0.0)


class TestJanelas(unittest.TestCase):
    def test_janelas_sem_desfecho_do_futuro(self):
        treino = PARTES['train']
        for ano, t, v in x.janelas_tempo(treino, [2016, 2017, 2018, 2019]):
            fim = treino.iloc[t].data_assinatura + pd.Timedelta(days=365)
            self.assertTrue((fim < pd.Timestamp(f'{ano}-01-01')).all())
            self.assertTrue((treino.iloc[v].ano_origem == ano).all())
            self.assertEqual(int((treino.iloc[t].ano_origem >= ano - 1).sum()), 0)


class TestProspectivo(unittest.TestCase):
    def test_rotulo_pelo_silver_reproduz_o_pacote(self):
        caminho = (d.ROOT / CONFIG['desembolsos']).resolve()
        if not caminho.exists():
            self.skipTest('Silver de desembolsos ausente nesta máquina')
        for nome in ('train', 'validation', 'test'):
            parte = PARTES[nome]
            np.testing.assert_array_equal(d.rotular_por_desembolsos(parte, CONFIG), parte[d.ALVO].to_numpy(), nome)

    def test_censurados_fora_das_particoes(self):
        ids = set(pd.concat([p.nr_convenio for p in PARTES.values()]))
        self.assertFalse(ids & set(d.carregar_censurados(CONFIG).nr_convenio))


class TestCapacidade(unittest.TestCase):
    def test_capacidade_reparte_empates(self):
        y = np.array([1, 0, 1, 0])
        self.assertAlmostEqual(x.matriz_capacidade(y, np.full(4, 0.5), 0.5)['precisao'], 0.5)


class TestMetricas(unittest.TestCase):
    def test_brier_skill_da_prevalencia_e_zero(self):
        y = np.array([1, 1, 0, 1])
        self.assertAlmostEqual(x.metricas(y, np.full(4, 0.75), 0.75)['brier_skill'], 0.0)

    def test_capacidade_marca_a_fracao_pedida(self):
        y = np.array([1, 0, 1, 1, 0, 1, 1, 0, 1, 1])
        p = np.linspace(0.9, 0.1, 10)
        saida = x.decisoes(y, p, {'f1': 0.5}, [0.2])
        self.assertEqual(saida['vp_top20'] + saida['fp_top20'], 2)


if __name__ == '__main__':
    unittest.main()
