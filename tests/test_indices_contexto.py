import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd

from etl_municipal.indices_contexto import (
    annual_band,
    annual_percentile,
    compute_indices,
    export_indices,
    derive_components,
    load_config,
    winsorize_annual,
)


class IndicesContextoTest(unittest.TestCase):
    def test_deriva_margem_relativa_e_proporcoes_sem_imputacao(self):
        frame = pd.DataFrame(
            {
                "ano": [2020, 2020, 2020],
                "receita_total_realizada": [100.0, 0.0, 100.0],
                "despesa_total_liquidada": [120.0, 20.0, 80.0],
                "transferencias_correntes_realizadas": [50.0, 10.0, 40.0],
                "restos_pagar_total": [10.0, 2.0, 5.0],
                "caixa_equivalentes": [20.0, 1.0, 10.0],
                "despesa_pessoal_liquidada": [30.0, 5.0, 20.0],
                "pessoal_ativo": [10.0, 0.0, 10.0],
                "pessoal_estatutario": [8.0, 0.0, np.nan],
                "pessoal_comissionado": [1.0, 0.0, 1.0],
                "pessoal_sem_vinculo": [1.0, 0.0, 1.0],
                "total_contratacoes": [10.0, 0.0, np.nan],
                "populacao": [1000.0, 1000.0, np.nan],
                "valor_estimado_contratacoes": [1000.0, 0.0, np.nan],
                "contratacoes_similares": [2.0, 0.0, np.nan],
            }
        )
        out = derive_components(frame)
        self.assertEqual(out.loc[0, "resultado_orcamentario_proxy"], -0.2)
        self.assertTrue(pd.isna(out.loc[1, "resultado_orcamentario_proxy"]))
        self.assertEqual(out.loc[0, "proporcao_pessoal_estatutario"], 0.8)
        self.assertTrue(pd.isna(out.loc[2, "proporcao_pessoal_estatutario"]))
        self.assertEqual(out.loc[0, "contratacoes_por_mil_habitantes"], 10.0)
        self.assertEqual(out.loc[0, "exposicao_contratual_sobre_receita"], 10.0)
        self.assertEqual(out.loc[0, "proporcao_contratacoes_similares"], 0.2)
        self.assertTrue(pd.isna(out.loc[1, "proporcao_contratacoes_similares"]))

    def test_winsorizacao_p1_p99_anual_preserva_nulos(self):
        frame = pd.DataFrame({"ano": [2020] * 5, "x": [1.0, 2.0, 3.0, 4.0, np.nan]})
        out, meta = winsorize_annual(frame, "x", "ano")
        self.assertTrue(pd.isna(out.loc[4, "x_winsorized"]))
        self.assertEqual(meta[2020]["method"], "linear")
        self.assertIn("lower", meta[2020])
        self.assertIn("upper", meta[2020])

    def test_percentil_tem_rank_medio_inversao_posterior_e_unico_50(self):
        frame = pd.DataFrame({"ano": [2020] * 4 + [2021], "x": [1.0, 1.0, 3.0, 4.0, 9.0]})
        out = annual_percentile(frame, "x", "ano", inverse=False)
        self.assertEqual(out.loc[0, "x_percentile"], out.loc[1, "x_percentile"])
        self.assertAlmostEqual(out.loc[0, "x_percentile"], 16.666666666666668)
        self.assertEqual(out.loc[4, "x_percentile"], 50.0)
        inv = annual_percentile(frame, "x", "ano", inverse=True)
        self.assertEqual(inv.loc[0, "x_percentile"], 100.0 - out.loc[0, "x_percentile"])

    def test_faixa_exige_quatro_valores_distintos_e_limite_fica_abaixo(self):
        frame = pd.DataFrame({"ano": [2020] * 5, "indice": [0.0, 1.0, 2.0, 3.0, 4.0]})
        out, meta = annual_band(frame, "indice", "ano")
        self.assertEqual(out.loc[0, "indice_faixa"], "baixo")
        self.assertEqual(out.loc[1, "indice_faixa"], "baixo")
        self.assertIn("q1", meta[2020])

    def test_faixa_nula_quando_todos_os_valores_sao_iguais(self):
        frame = pd.DataFrame({"ano": [2020] * 4, "indice": [5.0] * 4})
        out, meta = annual_band(frame, "indice", "ano")
        self.assertTrue(out["indice_faixa"].isna().all())
        self.assertEqual(meta[2020]["reason"], "valores_distintos_insuficientes")

    def test_indices_separados_sem_penalizar_transferegov(self):
        frame = pd.DataFrame(
            {
                "codigo_ibge": [1, 2, 3, 4, 5], "ano": [2022] * 5,
                "receita_total_realizada": [100] * 5, "despesa_total_liquidada": [80, 90, 100, 110, 120],
                "transferencias_correntes_realizadas": [20, 30, 40, 50, 60], "restos_pagar_total": [1, 2, 3, 4, 5],
                "caixa_equivalentes": [50, 40, 30, 20, 10], "despesa_pessoal_liquidada": [20] * 5,
                "pessoal_ativo": [10] * 5, "pessoal_estatutario": [8, 7, 6, 5, 4],
                "pessoal_comissionado": [1, 1, 2, 2, 3], "pessoal_sem_vinculo": [1, 2, 2, 3, 3],
                "total_contratacoes": [0, 1, 2, 3, 4], "populacao": [1000] * 5,
                "valor_estimado_contratacoes": [0, 100, 200, 300, 400], "contratacoes_similares": [0, 0, 1, 2, 2],
                "cobertura_pncp": ["completa"] * 5,
            }
        )
        out = compute_indices(frame)
        self.assertTrue(out["indice_vulnerabilidade_fiscal"].notna().all())
        self.assertTrue(out["indice_estrutura_vinculos_institucionais"].notna().all())
        self.assertTrue(out["indice_contexto_estrutural_municipal"].notna().all())
        self.assertTrue(out["historico_execucao_transferegov"].isna().all())
        self.assertEqual(out.loc[0, "status_similaridade_pncp"], "nao_aplicavel_sem_contratacoes")
        self.assertTrue(pd.isna(out.loc[0, "indice_intensidade_contratual_pncp"]))
        self.assertFalse(pd.isna(out.loc[0, "subindice_intensidade_geral_pncp"]))

    def test_pncp_fora_de_2022_2024_e_configuracao_controla_periodo(self):
        frame = pd.DataFrame({
            "codigo_ibge": [1, 2, 3], "ano": [2020, 2021, 2022],
            "receita_total_realizada": [100] * 3, "despesa_total_liquidada": [80] * 3,
            "transferencias_correntes_realizadas": [20] * 3, "restos_pagar_total": [1] * 3,
            "caixa_equivalentes": [10] * 3, "despesa_pessoal_liquidada": [20] * 3,
            "pessoal_ativo": [10] * 3, "pessoal_estatutario": [8] * 3,
            "pessoal_comissionado": [1] * 3, "pessoal_sem_vinculo": [1] * 3,
            "total_contratacoes": [99, 99, 1], "populacao": [1000] * 3,
            "valor_estimado_contratacoes": [999, 999, 10], "contratacoes_similares": [2, 2, 1],
            "cobertura_pncp": ["completa", "completa", "completa"],
        })
        out = compute_indices(frame)
        for row in (0, 1):
            self.assertEqual(out.loc[row, "status_pncp_indice"], "fora_periodo_configurado")
            self.assertTrue(pd.isna(out.loc[row, "contratacoes_por_mil_habitantes"]))
            self.assertTrue(pd.isna(out.loc[row, "indice_intensidade_contratual_pncp"]))
        self.assertEqual(out.loc[2, "status_pncp_indice"], "calculado")
        self.assertEqual(out.loc[0, "cobertura_pncp_fonte"], "completa")

    def test_dominios_invalidos_recebem_nulo(self):
        frame = pd.DataFrame({
            "ano": [2022], "receita_total_realizada": [100], "despesa_total_liquidada": [80],
            "transferencias_correntes_realizadas": [20], "restos_pagar_total": [1], "caixa_equivalentes": [10],
            "despesa_pessoal_liquidada": [20], "pessoal_ativo": [10], "pessoal_estatutario": [11],
            "pessoal_comissionado": [-1], "pessoal_sem_vinculo": [1], "total_contratacoes": [-2],
            "populacao": [1000], "valor_estimado_contratacoes": [-1], "contratacoes_similares": [3],
            "cobertura_pncp": ["completa"],
        })
        out = derive_components(frame)
        self.assertTrue(pd.isna(out.loc[0, "proporcao_pessoal_estatutario"]))
        self.assertTrue(pd.isna(out.loc[0, "proporcao_pessoal_comissionado"]))
        self.assertTrue(pd.isna(out.loc[0, "contratacoes_por_mil_habitantes"]))
        self.assertTrue(pd.isna(out.loc[0, "exposicao_contratual_sobre_receita"]))
        self.assertTrue(pd.isna(out.loc[0, "proporcao_contratacoes_similares"]))

    def test_configuracao_e_carregada(self):
        config, digest = load_config()
        self.assertEqual(config["versao_metodologia_indice"], "indice-contexto-municipal-v0")
        self.assertEqual(config["pncp"]["periodo"], [2022, 2024])
        self.assertEqual(len(digest), 64)

    def test_configuracao_divergente_interrompe(self):
        config_path = Path("config/indice_contexto_municipal.v0.json")
        data = json.loads(config_path.read_text(encoding="utf-8"))
        data["pncp"]["pesos"]["similaridade"] = 0.4
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_config(path)

    def test_exportacao_tem_hashes_manifesto_e_reexecucao_deterministica(self):
        frame = pd.DataFrame({
            "codigo_ibge": [2, 1], "ano": [2022, 2022],
            "receita_total_realizada": [100, 100], "despesa_total_liquidada": [80, 90],
            "transferencias_correntes_realizadas": [20, 30], "restos_pagar_total": [1, 2],
            "caixa_equivalentes": [10, 20], "despesa_pessoal_liquidada": [20, 20],
            "pessoal_ativo": [10, 10], "pessoal_estatutario": [8, 7],
            "pessoal_comissionado": [1, 1], "pessoal_sem_vinculo": [1, 2],
            "total_contratacoes": [1, 2], "populacao": [1000, 1000],
            "valor_estimado_contratacoes": [10, 20], "contratacoes_similares": [0, 1],
            "cobertura_pncp": ["completa", "completa"],
        })
        out = compute_indices(frame)
        with TemporaryDirectory() as a, TemporaryDirectory() as b:
            hashes_a = export_indices(out, "a" * 64, a)
            hashes_b = export_indices(out, "a" * 64, b)
            self.assertEqual(hashes_a["csv_sha256"], hashes_b["csv_sha256"])
            self.assertEqual(hashes_a["parquet_sha256"], hashes_b["parquet_sha256"])
            manifest = pd.read_json(Path(a) / "manifesto_indices_contexto.json", typ="series")
            self.assertTrue(manifest["limites_faixas"])
            self.assertEqual(manifest["input_sha256"], "a" * 64)
            csv = pd.read_csv(Path(a) / "indices_contexto_municipal.csv", sep=";")
            parquet = pd.read_parquet(Path(a) / "indices_contexto_municipal.parquet")
            self.assertEqual(csv.shape, parquet.shape)


if __name__ == "__main__":
    unittest.main()
