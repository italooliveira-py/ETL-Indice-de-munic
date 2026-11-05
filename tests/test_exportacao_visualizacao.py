import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from etl_municipal.exportacao_visualizacao import exportar_pacote_visualizacao


class ExportacaoVisualizacaoTest(unittest.TestCase):
    def _gold(self, raiz):
        pasta = raiz / 'gold' / 'versoes' / 'versao-teste'
        (pasta / 'gold').mkdir(parents=True)
        quadro = pd.DataFrame([
            {'codigo_ibge': f'{2500000 + municipio:07d}', 'ano': ano,
             'municipio': 'Água Branca', 'uf': 'PB',
             'populacao': None if municipio == 1 and ano == 2021 else 1000,
             'pessoal_ativo': 10 + ano - 2020, 'status_munic': 'observado'}
            for municipio in range(1, 224) for ano in range(2020, 2025)
        ])
        quadro.to_parquet(pasta / 'gold' / 'base_municipio_ano.parquet', index=False)
        (pasta / 'manifesto.json').write_text(json.dumps({
            'versao_gold': 'versao-teste',
            'commit_base': '5e8ed87',
            'proveniencia': {'condicao_temporal_munic': 'apta_com_ressalva_documentada'},
        }), encoding='utf-8')

    def test_versao_explicita_e_saida_deterministica(self):
        with tempfile.TemporaryDirectory() as temp:
            raiz = Path(temp) / 'data'
            self._gold(raiz)
            a = Path(temp) / 'a'
            b = Path(temp) / 'b'
            exportar_pacote_visualizacao(raiz, 'versao-teste', a)
            exportar_pacote_visualizacao(raiz, 'versao-teste', b)
            for nome in (
                'painel_municipio_ano_2020_2024.csv',
                'painel_municipio_ano_2020_2024.parquet',
                'dicionario_variaveis.csv',
                'cobertura_variaveis.csv',
                'manifesto.json',
            ):
                self.assertEqual(
                    hashlib.sha256((a / nome).read_bytes()).digest(),
                    hashlib.sha256((b / nome).read_bytes()).digest(),
                    nome,
                )
            painel = pd.read_csv(a / 'painel_municipio_ano_2020_2024.csv', sep=';', encoding='utf-8-sig', dtype={'codigo_ibge': 'string'})
            self.assertEqual(len(painel), 1115)
            self.assertEqual(painel.loc[0, 'codigo_ibge'], '2500001')
            self.assertTrue(pd.isna(painel.loc[1, 'populacao']))

    def test_versao_inexistente_bloqueia(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(FileNotFoundError):
                exportar_pacote_visualizacao(Path(temp), 'nao-existe', Path(temp) / 'saida')


if __name__ == '__main__':
    unittest.main()
