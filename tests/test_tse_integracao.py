import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd

import etl_primario as etl
import etl_tse_eleitoral as tse
try:
    from test_tse_eleitoral import catalogo_sintetico_pb
except ModuleNotFoundError:
    from tests.test_tse_eleitoral import catalogo_sintetico_pb


class TestIntegracaoTSE(unittest.TestCase):
    def test_smoke_tse_propagate_dois_municipios_periodos_e_edicoes(self):
        catalogo = tse.validar_catalogo_tse_ibge(catalogo_sintetico_pb())
        foto = tse.construir_municipio_ano_politico(catalogo, pd.DataFrame(), pd.DataFrame())
        codigos = catalogo.codigo_ibge.head(2).tolist()
        foto = foto[foto.codigo_ibge.isin(codigos)].reset_index(drop=True)
        resultado = tse.ResultadoTSE(pd.DataFrame(), pd.DataFrame(), foto, pd.DataFrame(), [])
        municipios = [{"codigo_ibge": r.codigo_ibge, "nome": r.municipio, "uf": "PB"} for r in catalogo.itertuples()]
        with tempfile.TemporaryDirectory() as temp:
            raiz = Path(temp)
            config = {"escopo": {"tipo": "uf", "ufs": ["PB"]}, "municipios": municipios,
                      "ano_inicial": 2020, "ano_final": 2024, "fontes": ["ibge"],
                      "tse_eleitoral_edicoes": [2016, 2020, 2024], "tse_eleitoral_ano_inicial": 2020,
                      "tse_eleitoral_ano_final": 2024}
            config_path = raiz / "config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            executor = Mock(return_value=resultado)
            with patch.object(etl, "RAW_DIR", raiz / "raw"), patch.object(etl, "OUTPUT_DIR", raiz / "output"), \
                 patch.object(etl, "MANUAL_DIR", raiz / "manual"), patch.object(etl, "resolver_municipios", return_value=municipios), \
                 patch.object(etl.etl_tse_eleitoral, "executar_tse_eleitoral", executor), \
                 patch.object(sys, "argv", ["etl_primario.py", "--config", str(config_path), "--sources", "tse_eleitoral", "--smoke-test"]), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(etl.main(), 0)
            resumo = json.loads((raiz / "output" / "smoke").glob("*/resumo_execucao.json").__iter__().__next__().read_text())
            self.assertEqual(resumo["municipios"], 2)
            self.assertEqual(resumo["periodo"], [2020, 2024])
            self.assertEqual(resumo["periodos_por_fonte"]["tse_eleitoral"], [2016, 2020])
            base = pd.read_csv(next((raiz / "output" / "smoke").glob("*/base_municipio_ano.csv")))
            self.assertEqual(len(base), 10)
            self.assertEqual(len(base[["codigo_ibge", "ano"]].drop_duplicates()), 10)
            self.assertEqual(json.loads(config_path.read_text())["fontes"], ["ibge"])
            executor.assert_called_once()

    def test_cli_chama_fonte_uma_vez_e_preserva_1115_linhas(self):
        catalogo = tse.validar_catalogo_tse_ibge(catalogo_sintetico_pb())
        foto = tse.construir_municipio_ano_politico(catalogo, pd.DataFrame(), pd.DataFrame())
        resultado = tse.ResultadoTSE(pd.DataFrame(), pd.DataFrame(), foto, pd.DataFrame(), [])
        municipios = [{"codigo_ibge": r.codigo_ibge, "nome": r.municipio, "uf": "PB"} for r in catalogo.itertuples()]
        with tempfile.TemporaryDirectory() as temp:
            raiz = Path(temp)
            config = {"escopo": {"tipo": "uf", "ufs": ["PB"]}, "municipios": municipios,
                      "ano_inicial": 2020, "ano_final": 2024, "fontes": ["ibge"]}
            config_path = raiz / "config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            executor = Mock(return_value=resultado)
            with patch.object(etl, "RAW_DIR", raiz / "raw"), patch.object(etl, "OUTPUT_DIR", raiz / "output"), \
                 patch.object(etl, "MANUAL_DIR", raiz / "manual"), patch.object(etl, "resolver_municipios", return_value=municipios), \
                 patch.object(etl.etl_tse_eleitoral, "executar_tse_eleitoral", executor), \
                 patch.object(sys, "argv", ["etl_primario.py", "--config", str(config_path), "--sources", "tse_eleitoral"]), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(etl.main(), 0)
            executor.assert_called_once()
            base = pd.read_csv(raiz / "output" / "base_municipio_ano.csv", dtype={"codigo_ibge": str})
            self.assertEqual(len(base), 1115)
            self.assertIn("ano_fotografia", base)
            self.assertEqual(json.loads(config_path.read_text())["fontes"], ["ibge"])


if __name__ == "__main__":
    unittest.main()
