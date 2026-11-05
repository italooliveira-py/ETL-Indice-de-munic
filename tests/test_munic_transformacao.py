"""Contratos TDD da integração MUNIC; fixtures sintéticos não substituem os arquivos oficiais."""
import unittest
import tempfile
from pathlib import Path

import pandas as pd

from src.etl_municipal.fontes import munic_catalogo
from src.etl_municipal.fontes.munic_transformacao import (
    CORRIGIDAS_OFICIAIS,
    construir_silver_munic_versionado,
    construir_painel_munic,
    ler_recursos_humanos,
    normalizar_observacoes,
)


class CatalogoMunic(unittest.TestCase):
    def test_edicoes_autorizadas_e_ausencia_explicita_de_2022(self):
        self.assertEqual(munic_catalogo.EDICOES_AUTORIZADAS, (2019, 2020, 2021, 2023, 2024))
        self.assertNotIn(2022, munic_catalogo.EDICOES_AUTORIZADAS)
        self.assertEqual(munic_catalogo.status_edicao(2022), 'edicao_indisponivel')

    def test_identidade_e_alias_sao_versionados_por_edicao_bloco_codigo(self):
        entrada = munic_catalogo.definicao(2021, 'recursos_humanos', 'RH_TOTAL')
        self.assertEqual(entrada['codigo_original'], 'RH_TOTAL')
        self.assertEqual(entrada['edicao'], 2021)
        self.assertEqual(entrada['bloco'], 'recursos_humanos')
        self.assertEqual(munic_catalogo.aliases(2021, 'recursos_humanos', 'RH_TOTAL'), ('RH_TOTAL',))

    def test_codigo_fora_do_catalogo_e_rejeitado(self):
        with self.assertRaises(munic_catalogo.CatalogoMunicError):
            munic_catalogo.definicao(2021, 'recursos_humanos', 'COLUNA_INVENTADA')


class NormalizacaoMunic(unittest.TestCase):
    def test_le_recursos_humanos_por_codigo_do_questionario_e_filtra_pb(self):
        bruto = pd.DataFrame([
            {'CodMun': 2500106, 'UF': 'PB', 'Mun': 'MUNICIPIO A', 'MREH0111': 10,
             'MREH0112': 20, 'MREH0113': 30, 'MREH0114': 4, 'MREH0115': 5, 'MREH0116': 69},
            {'CodMun': 1100015, 'UF': 'RO', 'Mun': 'OUTRO', 'MREH0111': 1,
             'MREH0112': 2, 'MREH0113': 3, 'MREH0114': 4, 'MREH0115': 5, 'MREH0116': 15},
        ])
        with tempfile.TemporaryDirectory() as temp:
            caminho = Path(temp) / 'munic.xlsx'
            bruto.to_excel(caminho, sheet_name='Recursos humanos', index=False)
            resultado = ler_recursos_humanos(caminho, 2021)
        self.assertEqual(set(resultado.codigo_ibge), {'2500106'})
        self.assertEqual(set(resultado.codigo_original), {
            'MREH0111', 'MREH0112', 'MREH0113', 'MREH0114', 'MREH0115', 'MREH0116',
        })
        self.assertEqual(resultado.loc[resultado.codigo_original == 'MREH0116', 'valor_original'].iloc[0], 69)

    def test_preserva_estados_e_zero_observado_sem_completar_codigo(self):
        bruto = pd.DataFrame([
            {'codigo_ibge': '2500106', 'municipio': 'MUNICIPIO A', 'uf': 'PB',
             'bloco': 'recursos_humanos', 'codigo_original': 'RH_TOTAL', 'valor_original': '100'},
            {'codigo_ibge': '2500106', 'municipio': 'MUNICIPIO A', 'uf': 'PB',
             'bloco': 'recursos_humanos', 'codigo_original': 'RH_ESTATUTARIOS', 'valor_original': ''},
            {'codigo_ibge': '2500106', 'municipio': 'MUNICIPIO A', 'uf': 'PB',
             'bloco': 'recursos_humanos', 'codigo_original': 'RH_CELETISTAS', 'valor_original': 'NAO SE APLICA'},
            {'codigo_ibge': '2500106', 'municipio': 'MUNICIPIO A', 'uf': 'PB',
             'bloco': 'recursos_humanos', 'codigo_original': 'RH_COMISSIONADOS', 'valor_original': 'NAO'},
            {'codigo_ibge': '2500106', 'municipio': 'MUNICIPIO A', 'uf': 'PB',
             'bloco': 'recursos_humanos', 'codigo_original': 'RH_ESTAGIARIOS', 'valor_original': '0'},
        ])
        resultado = normalizar_observacoes(bruto, 2021, referencia='fixture')
        estados = dict(zip(resultado.codigo_original, resultado.status_observacao))
        self.assertEqual(estados['RH_TOTAL'], 'observado')
        self.assertEqual(estados['RH_ESTATUTARIOS'], 'nao_informado')
        self.assertEqual(estados['RH_CELETISTAS'], 'nao_se_aplica')
        self.assertEqual(estados['RH_COMISSIONADOS'], 'resposta_negativa')
        self.assertEqual(estados['RH_ESTAGIARIOS'], 'observado')
        zero = resultado.loc[resultado.codigo_original == 'RH_ESTAGIARIOS', 'valor_normalizado'].iloc[0]
        self.assertEqual(zero, 0)
        self.assertTrue((resultado.codigo_ibge.str.len() == 7).all())

    def test_silver_versionado_preserva_original_e_revisao(self):
        bruto = pd.DataFrame([{
            'codigo_ibge': '2500106', 'municipio': 'MUNICIPIO A', 'uf': 'PB',
            'bloco': 'recursos_humanos', 'codigo_original': 'RH_TOTAL', 'valor_original': '100',
        }])
        observacoes = normalizar_observacoes(bruto, 2021, referencia='fixture')
        original = construir_silver_munic_versionado(
            observacoes, versao_base='original', data_publicacao='2022-12-08',
            arquivo_origem='Base_MUNIC_2021.xlsx', sha256_origem='a' * 64,
        )
        revisao = construir_silver_munic_versionado(
            observacoes.assign(valor_normalizado=101), versao_base='revisao_2024_04_25',
            data_publicacao='2024-04-25', arquivo_origem='Base_MUNIC_2021_20240425.xlsx',
            sha256_origem='b' * 64,
        )
        observacoes_versao = pd.concat([
            original['silver/munic_observacoes_versao'],
            revisao['silver/munic_observacoes_versao'],
        ], ignore_index=True)
        edicao_versao = pd.concat([
            original['silver/munic_municipio_edicao_versao'],
            revisao['silver/munic_municipio_edicao_versao'],
        ], ignore_index=True)
        self.assertEqual(set(observacoes_versao.versao_base), {'original', 'revisao_2024_04_25'})
        self.assertEqual(len(observacoes_versao), 2)
        self.assertEqual(len(edicao_versao), 2)
        self.assertEqual(set(edicao_versao.versao_base), {'original', 'revisao_2024_04_25'})

    def test_point_in_time_considera_data_da_versao_e_nao_so_ano(self):
        base = pd.DataFrame([
            {'codigo_ibge': '2500106', 'municipio': 'MUNICIPIO A', 'uf': 'PB',
             'ano_edicao_munic': 2021, 'variavel': 'pessoal_ativo', 'valor_publicado': 100,
             'versao_base': 'original', 'data_publicacao': '2022-12-08',
             'data_publicacao_original': '2022-12-08', 'arquivo_origem': 'original.xlsx',
             'sha256_origem': 'a' * 64, 'status_observacao': 'observado'},
            {'codigo_ibge': '2500106', 'municipio': 'MUNICIPIO A', 'uf': 'PB',
             'ano_edicao_munic': 2021, 'variavel': 'pessoal_ativo', 'valor_publicado': 101,
             'versao_base': 'revisao_2024_04_25', 'data_publicacao': '2024-04-25',
             'data_publicacao_original': '2022-12-08', 'arquivo_origem': 'revisao.xlsx',
             'sha256_origem': 'b' * 64, 'status_observacao': 'observado'},
            {'codigo_ibge': '2500106', 'municipio': 'MUNICIPIO A', 'uf': 'PB',
             'ano_edicao_munic': 2023, 'variavel': 'pessoal_ativo', 'valor_publicado': 110,
             'versao_base': 'original', 'data_publicacao': '2024-10-31',
             'data_publicacao_original': '2024-10-31', 'arquivo_origem': '2023.xlsx',
             'sha256_origem': 'c' * 64, 'status_observacao': 'observado'},
            {'codigo_ibge': '2500106', 'municipio': 'MUNICIPIO A', 'uf': 'PB',
             'ano_edicao_munic': 2024, 'variavel': 'pessoal_ativo', 'valor_publicado': 120,
             'versao_base': 'original', 'data_publicacao': '2025-10-31',
             'data_publicacao_original': '2025-10-31', 'arquivo_origem': '2024.xlsx',
             'sha256_origem': 'd' * 64, 'status_observacao': 'observado'},
        ])
        longo = construir_painel_munic(base, anos=(2022, 2023, 2024))['gold/munic_disponibilidade_variavel']
        por_ano = longo.set_index('ano_fotografia')
        self.assertEqual(por_ano.loc[2022, 'versao_origem'], 'original')
        self.assertEqual(por_ano.loc[2022, 'valor_publicado'], 100)
        self.assertEqual(por_ano.loc[2023, 'valor_publicado'], 100)
        self.assertEqual(por_ano.loc[2024, 'valor_publicado'], 110)
        self.assertNotIn(120, set(longo.valor_publicado))

    def test_indicador_por_mil_usa_populacao_do_ano_e_nao_retropropaga_censo(self):
        observacoes = pd.DataFrame([
            {'codigo_ibge': '2500106', 'municipio': 'MUNICIPIO A', 'uf': 'PB',
             'ano_edicao_munic': 2019, 'variavel': 'pessoal_ativo', 'valor_publicado': 100,
             'versao_base': 'original', 'data_publicacao': '2020-12-02',
             'data_publicacao_original': '2020-12-02', 'arquivo_origem': '2019.xlsx',
             'sha256_origem': 'a' * 64, 'status_observacao': 'observado'},
        ])
        populacao = pd.DataFrame([{'codigo_ibge': '2500106', 'ano_fotografia': 2022, 'populacao': 1000}])
        resultado = construir_painel_munic(observacoes, anos=(2020, 2022), populacao=populacao)
        largo = resultado['gold/munic_capacidade_institucional_ano'].set_index('ano_fotografia')
        self.assertTrue(pd.isna(largo.loc[2020, 'pessoal_ativo_por_mil_habitantes']))
        self.assertEqual(largo.loc[2022, 'pessoal_ativo_por_mil_habitantes'], 100.0)
        self.assertEqual(largo.loc[2020, 'status_denominador_populacao'], 'denominador_indisponivel')

    def test_codigos_corrigidos_ficam_na_auditoria_e_fora_do_gold_largo(self):
        observacoes = pd.DataFrame([
            {'codigo_ibge': '2500106', 'municipio': 'MUNICIPIO A', 'uf': 'PB',
             'ano_edicao_munic': 2019, 'variavel': codigo, 'valor_publicado': 1,
             'versao_base': 'revisao_2021_08_17', 'data_publicacao': '2021-08-17',
             'data_publicacao_original': '2020-12-02', 'arquivo_origem': 'revisao.xlsx',
             'sha256_origem': 'a' * 64, 'status_observacao': 'observado'}
            for codigo in CORRIGIDAS_OFICIAIS
        ])
        resultado = construir_painel_munic(observacoes, anos=(2021,))
        self.assertTrue(CORRIGIDAS_OFICIAIS <= set(resultado['gold/munic_auditoria_disponibilidade_variavel'].variavel))
        self.assertTrue(CORRIGIDAS_OFICIAIS.isdisjoint(resultado['gold/munic_disponibilidade_variavel'].variavel))
        self.assertTrue(CORRIGIDAS_OFICIAIS.isdisjoint(resultado['gold/munic_capacidade_institucional_ano'].columns))

    def test_errata_temporal_separa_arquivo_fisico_de_variavel(self):
        base = pd.DataFrame([
            {'codigo_ibge': '2500106', 'municipio': 'MUNICIPIO A', 'uf': 'PB',
             'ano_edicao_munic': 2021, 'variavel': 'MCUL42', 'valor_publicado': 1,
             'versao_base': 'revisao_2024_04_25', 'data_publicacao': '2024-04-25',
             'data_publicacao_original': '2022-12-08', 'data_disponibilidade_temporal': '2024-04-25',
             'arquivo_origem': 'revisao.xlsx', 'sha256_origem': 'a' * 64,
             'status_observacao': 'observado', 'status_afetada_errata': 'afetada'},
            {'codigo_ibge': '2500106', 'municipio': 'MUNICIPIO A', 'uf': 'PB',
             'ano_edicao_munic': 2021, 'variavel': 'pessoal_ativo', 'valor_publicado': 100,
             'versao_base': 'revisao_2024_04_25', 'data_publicacao': '2024-04-25',
             'data_publicacao_original': '2022-12-08', 'data_disponibilidade_temporal': '2022-12-08',
             'arquivo_origem': 'revisao.xlsx', 'sha256_origem': 'a' * 64,
             'status_observacao': 'observado', 'status_afetada_errata': 'nao_afetada',
             'precisao_data_disponibilidade': 'condicional_por_escopo_de_errata',
             'evidencia_disponibilidade_variavel': 'nota_oficial_ibge_delimita_correcao_a_mcul42'},
        ])
        resultado = construir_painel_munic(base, anos=(2022, 2023, 2024))
        analitica = resultado['gold/munic_disponibilidade_variavel']
        auditoria = resultado['gold/munic_auditoria_disponibilidade_variavel']
        self.assertNotIn('MCUL42', set(analitica.variavel))
        self.assertNotIn('MCUL42', set(analitica.loc[analitica.ano_fotografia.isin([2022, 2023]), 'variavel']))
        self.assertIn('MCUL42', set(auditoria.variavel))
        rh = analitica[analitica.variavel == 'pessoal_ativo']
        self.assertEqual(set(rh.versao_origem), {'revisao_2024_04_25'})
        self.assertEqual(set(rh.data_disponibilidade_adotada.astype(str)), {'2022-12-08'})
        self.assertTrue(set(rh.status_temporal) <= {'apta_com_ressalva_documentada'})
        self.assertEqual(set(rh.precisao_data_disponibilidade), {'condicional_por_escopo_de_errata'})

    def test_metadados_errata_nao_sao_confundidos_com_variaveis_publicadas(self):
        observacoes = pd.DataFrame([{
            'codigo_ibge': '2500106', 'municipio': 'MUNICIPIO A', 'uf': 'PB',
            'ano_edicao_munic': 2021, 'variavel': 'pessoal_ativo', 'valor_publicado': 1,
            'versao_base': 'revisao_2024_04_25', 'data_publicacao': '2024-04-25',
            'data_publicacao_original': '2022-12-08', 'data_disponibilidade_temporal': '2022-12-08',
            'arquivo_origem': 'revisao.xlsx', 'sha256_origem': 'a' * 64,
            'status_observacao': 'observado', 'escopo_correcao_oficial': 'MCUL42',
        }])
        resultado = construir_painel_munic(observacoes, anos=(2022,))
        auditoria = resultado['gold/munic_auditoria_disponibilidade_variavel']
        self.assertIn('MCUL42', auditoria.escopo_correcao_oficial.iloc[0])
        self.assertNotIn('MCUL42', set(resultado['gold/munic_disponibilidade_variavel'].variavel))


if __name__ == '__main__':
    unittest.main()
