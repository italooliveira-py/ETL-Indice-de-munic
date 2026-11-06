import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd
from pandas.api.types import is_string_dtype

from etl_municipal.analitico.transferegov_temporal import (
    build_temporal_package,
    context_year_for_signature,
    load_config,
    write_versioned_temporal_package,
    write_temporal_package,
)


class TransferegovHistoricoTest(unittest.TestCase):
    def setUp(self):
        self.config, _ = load_config()
        self.instruments = pd.DataFrame(
            {
                "nr_convenio": ["0001", "0002", "0003", "0004", "0005"],
                "id_proposta": ["00001", "00002", "00003", "00004", "00005"],
                "codigo_ibge": ["2500001"] * 5,
                "nome_proponente": ["Município"] * 5,
                "modalidade": ["discricionaria"] * 5,
                "data_assinatura": ["2020-01-01"] * 5,
                "data_carga": ["2026-07-17 06:30:47"] * 5,
            }
        )
        self.disbursements = pd.DataFrame(
            {
                "id_desembolso": ["d1", "d2", "d3", "d4"],
                "nr_convenio": ["0001", "0002", "0003", "0004"],
                "codigo_ibge": ["2500001"] * 4,
                "data_desembolso": ["2020-12-31", "2021-01-01", "2025-01-02", "2020-01-01"],
                "valor_desembolsado": [10, 10, 10, 0],
            }
        )

    def test_configuracao_controla_contrato_e_parametros(self):
        self.assertEqual(self.config["periodo"], [2020, 2024])
        self.assertEqual(self.config["maturidade_dias"], 365)
        self.assertEqual(self.config["regra_dia_365"], "no_prazo_365")
        self.assertEqual(self.config["regra_dia_366"], "atrasado_apos_365")
        self.assertIn("discricionaria", self.config["modalidades"])
        self.assertEqual(self.config["faixas_denominador"][1]["nome"], "1-4")

    def test_configuracao_temporaria_altera_parametros_diagnosticos(self):
        data = json.loads(Path("config/transferegov_historico_temporal.v0.json").read_text(encoding="utf-8"))
        data["parametros_sensibilidade"]["minimo_denominador"] = 1
        data["parametros_sensibilidade"]["beta_alpha"] = 2
        data["parametros_sensibilidade"]["beta_beta"] = 3
        data["parametros_sensibilidade"]["shrinkage_k"] = 1
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            config, _ = load_config(path)
            self.assertEqual(config["parametros_sensibilidade"]["minimo_denominador"], 1)
            self.assertEqual(config["parametros_sensibilidade"]["beta_alpha"], 2)
            self.assertEqual(config["parametros_sensibilidade"]["beta_beta"], 3)
            self.assertEqual(config["parametros_sensibilidade"]["shrinkage_k"], 1)
            municipalities = pd.DataFrame({"codigo_ibge": ["2500001", "2500002"], "uf": ["PB", "PB"], "municipio": ["M1", "M2"]})
            instruments = pd.concat([self.instruments, pd.DataFrame({"nr_convenio": ["0006"], "id_proposta": ["00006"], "codigo_ibge": ["2500002"], "nome_proponente": ["M2"], "modalidade": ["discricionaria"], "data_assinatura": ["2020-01-01"], "data_carga": ["2026-07-17"]})], ignore_index=True)
            base = build_temporal_package(instruments, self.disbursements, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), municipalities, self.config, "g", "h")
            changed = build_temporal_package(instruments, self.disbursements, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), municipalities, config, "g", "h")
            self.assertFalse(base["sensibilidade_maturidade"]["taxa_beta_binomial"].equals(changed["sensibilidade_maturidade"]["taxa_beta_binomial"]))
            self.assertFalse(base["sensibilidade_maturidade"]["taxa_shrinkage_estadual"].equals(changed["sensibilidade_maturidade"]["taxa_shrinkage_estadual"]))
            self.assertTrue(base["sensibilidade_maturidade"]["taxa_minimo_configurado"].isna().any())
            self.assertFalse(changed["sensibilidade_maturidade"]["taxa_minimo_configurado"].isna().any())

    def test_temporalidade_preserva_ids_e_classifica_365_366_e_censura(self):
        instruments = self.instruments.copy()
        instruments.loc[0, "data_assinatura"] = "2020-01-01"
        instruments.loc[1, "data_assinatura"] = "2020-01-02"
        instruments.loc[2, "data_assinatura"] = "2024-07-01"
        instruments.loc[3, "data_assinatura"] = "2020-01-01"
        disbursements = self.disbursements.copy()
        disbursements.loc[0, "data_desembolso"] = "2020-12-31"
        disbursements.loc[1, "data_desembolso"] = "2021-01-01"
        disbursements.loc[2, "data_desembolso"] = "2025-01-02"
        out = build_temporal_package(
            instruments, disbursements, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(),
            pd.DataFrame({"codigo_ibge": ["2500001"], "uf": ["PB"], "municipio": ["Teste"]}),
            self.config, "gold-v", "manifest-sha",
        )
        temporal = out["instrumentos"]
        self.assertTrue(is_string_dtype(temporal["nr_convenio"]))
        states_2020 = temporal[temporal["ano"] == 2020].set_index("nr_convenio")["estado_maturidade"]
        states_2021 = temporal[temporal["ano"] == 2021].set_index("nr_convenio")["estado_maturidade"]
        states_2024 = temporal[temporal["ano"] == 2024].set_index("nr_convenio")["estado_maturidade"]
        self.assertEqual(states_2020["0001"], "no_prazo_365")
        self.assertEqual(states_2021["0002"], "no_prazo_365")
        self.assertEqual(states_2024["0003"], "censurado_365_incompleto")
        self.assertEqual(states_2020["0004"], "sem_desembolso_ate_maturidade")
        self.assertTrue((temporal["data_carga"] == "2026-07-17 06:30:47").all())

    def test_evento_futuro_nao_vaza_para_fotografia_anterior(self):
        instruments = self.instruments.iloc[[0]].copy()
        events = pd.DataFrame({"id_desembolso": ["futuro"], "nr_convenio": ["0001"], "codigo_ibge": ["2500001"], "data_desembolso": ["2025-01-01"], "valor_desembolsado": [10]})
        out = build_temporal_package(instruments, events, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame({"codigo_ibge": ["2500001"], "uf": ["PB"], "municipio": ["M"]}), self.config, "g", "h")
        historical = out["instrumentos"]
        self.assertTrue(historical.loc[historical["ano"] < 2025, "primeiro_desembolso_observado_ate_corte"].isna().all())
        self.assertTrue(historical.loc[historical["ano"] < 2025, "dias_ate_primeiro_desembolso_observado"].isna().all())
        self.assertNotIn("primeiro_desembolso_positivo", historical.columns)

    def test_desfecho_tem_semantica_true_false_e_na(self):
        instruments = self.instruments.copy()
        instruments.loc[2, "data_assinatura"] = "2024-07-01"
        out = build_temporal_package(instruments, self.disbursements, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame({"codigo_ibge": ["2500001"], "uf": ["PB"], "municipio": ["M"]}), self.config, "g", "h")
        values = out["instrumentos"].query("ano == 2020").set_index("nr_convenio")["evento_sem_desembolso_positivo_ate_365d"]
        self.assertFalse(bool(values["0001"]))
        self.assertTrue(bool(values["0004"]))
        self.assertTrue(pd.isna(out["instrumentos"].query("ano == 2024 and nr_convenio == '0003'")["evento_sem_desembolso_positivo_ate_365d"].iloc[0]))

    def test_assinatura_ausente_fica_na_auditoria_e_nao_entra_no_denominador(self):
        instruments = self.instruments.copy()
        instruments.loc[0, "data_assinatura"] = None
        out = build_temporal_package(instruments, self.disbursements, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame({"codigo_ibge": ["2500001"], "uf": ["PB"], "municipio": ["M"]}), self.config, "g", "h")
        audit = out["instrumentos_auditoria"]
        self.assertEqual(audit.loc[audit["nr_convenio"] == "0001", "estado_base"].iloc[0], "indisponivel_sem_assinatura")
        self.assertNotIn("0001", set(out["instrumentos"]["nr_convenio"]))
        self.assertIn("0002", set(out["instrumentos"]["nr_convenio"]))

    def test_rejeita_referencias_especiais_sem_pai(self):
        empenho = pd.DataFrame({"id_empenho": ["e1"], "id_plano_acao": ["p_inexistente"], "codigo_ibge": ["2500001"], "data_empenho": ["2022-01-01"], "valor_empenhado": [1]})
        with self.assertRaises(ValueError):
            build_temporal_package(self.instruments, self.disbursements, pd.DataFrame(), empenho, pd.DataFrame(), pd.DataFrame(), self.config, "g", "h")

    def test_rejeita_id_vazio_codigo_invalido_e_territorio_divergente(self):
        invalid = self.instruments.copy(); invalid.loc[0, "nr_convenio"] = ""
        with self.assertRaises(ValueError):
            build_temporal_package(invalid, self.disbursements, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), self.config, "g", "h")
        invalid = self.instruments.copy(); invalid.loc[0, "codigo_ibge"] = "123"
        with self.assertRaises(ValueError):
            build_temporal_package(invalid, self.disbursements, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), self.config, "g", "h")
        divergent = self.disbursements.copy(); divergent.loc[0, "codigo_ibge"] = "2500002"
        with self.assertRaises(ValueError):
            build_temporal_package(self.instruments, divergent, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), self.config, "g", "h")

    def test_cobertura_incompleta_nao_confirma_zeros(self):
        municipalities = pd.DataFrame({"codigo_ibge": ["2500001", "2500002"], "uf": ["PB", "PB"], "municipio": ["M1", "M2"]})
        out = build_temporal_package(self.instruments, self.disbursements, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), municipalities, self.config, "g", "h")
        row = out["municipio_ano_historico"].query("codigo_ibge == '2500002' and ano == 2020").iloc[0]
        self.assertTrue(pd.isna(row["instrumentos_elegiveis"]))
        self.assertEqual(row["status_cobertura"], "incompleta")
        self.assertTrue(pd.isna(row["denominador_maduro_coorte"]))
        self.assertTrue(pd.isna(row["denominador_maduro_janela_3a"]))

    def test_rejeita_evento_anterior_valor_invalido_e_duplicidade(self):
        bad = self.disbursements.copy()
        bad.loc[0, "data_desembolso"] = "2019-12-31"
        bad.loc[1, "valor_desembolsado"] = -1
        with self.assertRaises(ValueError):
            build_temporal_package(self.instruments, bad, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), self.config, "g", "h")
        duplicate = pd.concat([self.disbursements, self.disbursements.iloc[[0]]], ignore_index=True)
        with self.assertRaises(ValueError):
            build_temporal_package(self.instruments, duplicate, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), self.config, "g", "h")
        for value in [None, ""]:
            invalid_id = self.disbursements.copy()
            invalid_id.loc[0, "id_desembolso"] = value
            with self.assertRaises(ValueError):
                build_temporal_package(self.instruments, invalid_id, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), self.config, "g", "h")

    def test_dia_366_e_atraso_e_zero_nao_e_evento(self):
        instruments = self.instruments.iloc[[0, 1]].copy()
        instruments.loc[1, "data_assinatura"] = "2020-01-01"
        events = pd.DataFrame({"id_desembolso": ["d1", "d2"], "nr_convenio": ["0001", "0002"], "codigo_ibge": ["2500001", "2500001"], "data_desembolso": ["2021-01-01", "2020-01-01"], "valor_desembolsado": [10, 0]})
        out = build_temporal_package(instruments, events, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame({"codigo_ibge": ["2500001"], "uf": ["PB"], "municipio": ["M"]}), self.config, "g", "h")
        states = out["instrumentos"].query("ano == 2021").set_index("nr_convenio")["estado_maturidade"]
        self.assertEqual(states["0001"], "atrasado_apos_365")
        self.assertEqual(len(out["eventos_financeiros"]), 1)

    def test_agregado_canonico_tem_visoes_acumulada_coorte_e_janela(self):
        municipalities = pd.DataFrame({"codigo_ibge": [f"25{i:05d}" for i in range(1, 224)], "uf": ["PB"] * 223, "municipio": ["M"] * 223})
        instruments = pd.concat([self.instruments, pd.DataFrame({"nr_convenio": ["0006"], "id_proposta": ["00006"], "codigo_ibge": ["2500002"], "nome_proponente": ["M"], "modalidade": ["discricionaria"], "data_assinatura": ["2021-01-01"], "data_carga": ["2026-07-17"]})], ignore_index=True)
        out = build_temporal_package(instruments, self.disbursements, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), municipalities, self.config, "g", "h")
        annual = out["municipio_ano_historico"]
        self.assertEqual(len(annual), 1115)
        self.assertEqual(annual[["codigo_ibge", "ano"]].duplicated().sum(), 0)
        self.assertIn("taxa_atraso_365_acumulada", annual.columns)
        self.assertIn("taxa_atraso_365_coorte", annual.columns)
        self.assertIn("taxa_atraso_365_janela_3a", annual.columns)
        self.assertIn("denominador_maduro_coorte", annual.columns)
        self.assertIn("denominador_maduro_janela_3a", annual.columns)

    def test_especiais_sao_separadas_e_nao_recebem_desfecho_365(self):
        special = pd.DataFrame({"id_plano_acao": ["p1"], "codigo_ibge": ["2500001"], "ano_plano_acao": [2022], "valor_custeio": [10]})
        out = build_temporal_package(self.instruments, self.disbursements, special, pd.DataFrame(), pd.DataFrame(), pd.DataFrame({"codigo_ibge": ["2500001"], "uf": ["PB"], "municipio": ["M"]}), self.config, "g", "h")
        self.assertEqual(len(out["especiais"]), 1)
        self.assertNotIn("estado_maturidade", out["especiais"].columns)

    def test_especiais_rejeitam_duplicidade_antes_da_normalizacao(self):
        special = pd.DataFrame({"id_plano_acao": ["p1", "p1"], "codigo_ibge": ["2500001", "2500001"], "ano_plano_acao": [2022, 2022], "valor_custeio": [10, 10]})
        with self.assertRaises(ValueError):
            build_temporal_package(self.instruments, self.disbursements, special, pd.DataFrame(), pd.DataFrame(), pd.DataFrame({"codigo_ibge": ["2500001"], "uf": ["PB"], "municipio": ["M"]}), self.config, "g", "h")

    def test_contexto_temporal_nao_usa_fotografia_do_proprio_ano(self):
        self.assertEqual(context_year_for_signature(pd.Timestamp("2022-06-01"), 2022), 2021)
        self.assertEqual(context_year_for_signature(pd.Timestamp("2021-12-31"), 2022), 2021)
        self.assertIsNone(context_year_for_signature(pd.Timestamp("2021-01-01"), 2020))

    def test_exportacao_deterministica_e_manifesto_sem_caminho_absoluto(self):
        municipalities = pd.DataFrame({"codigo_ibge": ["2500001"], "uf": ["PB"], "municipio": ["M"]})
        package = build_temporal_package(self.instruments, self.disbursements, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), municipalities, self.config, "g", "h")
        with TemporaryDirectory() as a, TemporaryDirectory() as b:
            ma = write_temporal_package(package, a)
            mb = write_temporal_package(package, b)
            self.assertEqual(ma["versao_analitica"], mb["versao_analitica"])
            self.assertEqual(ma["hashes_saidas"], mb["hashes_saidas"])
            manifest = json.loads((Path(a) / "manifesto.json").read_text(encoding="utf-8"))
            self.assertNotIn("C:\\", json.dumps(manifest))
            self.assertIn("formulas", manifest)
            self.assertIn("regras_maturidade", manifest)
            self.assertFalse(manifest["aptidao_preditiva"])
            self.assertTrue((Path(a) / "elegibilidade_variaveis.csv").exists())

    def test_exportacao_usa_namespace_versionado(self):
        municipalities = pd.DataFrame({"codigo_ibge": ["2500001"], "uf": ["PB"], "municipio": ["M"]})
        package = build_temporal_package(self.instruments, self.disbursements, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), municipalities, self.config, "g", "h")
        with TemporaryDirectory() as directory:
            target = write_versioned_temporal_package(package, directory)
            self.assertEqual(target.name, package["metadata"]["versao_analitica"])
            self.assertTrue((target / "manifesto.json").exists())

    def test_entradas_embaralhadas_produzem_mesmos_hashes(self):
        municipalities = pd.DataFrame({"codigo_ibge": ["2500001"], "uf": ["PB"], "municipio": ["M"]})
        a = build_temporal_package(self.instruments, self.disbursements, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), municipalities, self.config, "g", "h")
        b = build_temporal_package(self.instruments.sample(frac=1, random_state=9), self.disbursements.sample(frac=1, random_state=8), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), municipalities, self.config, "g", "h")
        with TemporaryDirectory() as da, TemporaryDirectory() as db:
            self.assertEqual(write_temporal_package(a, da)["hashes_saidas"], write_temporal_package(b, db)["hashes_saidas"])

    def test_diretorio_versionado_nao_sobrescreve_hash_divergente(self):
        municipalities = pd.DataFrame({"codigo_ibge": ["2500001"], "uf": ["PB"], "municipio": ["M"]})
        package = build_temporal_package(self.instruments, self.disbursements, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), municipalities, self.config, "g", "h")
        with TemporaryDirectory() as directory:
            write_versioned_temporal_package(package, directory)
            package["eventos_financeiros"] = package["eventos_financeiros"].iloc[0:0]
            with self.assertRaises(ValueError):
                write_versioned_temporal_package(package, directory)


if __name__ == "__main__":
    unittest.main()
