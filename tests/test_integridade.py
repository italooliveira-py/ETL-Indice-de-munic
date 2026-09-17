"""Regressões de integridade: datas, metadados e limites do smoke."""
import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd
import requests
import etl_primario as etl
import etl_confiabilidade as seguro
from test_checkpoint1 import resposta, pagina, compra
from test_checkpoint2 import MUNICIPIOS


class Integridade(unittest.TestCase):
    def test_retry_after_data_http(self):
        futuro = datetime.now(timezone.utc) + timedelta(seconds=30)
        self.assertGreaterEqual(seguro.retry_after(format_datetime(futuro)), 28)
        self.assertEqual(seguro.retry_after("invalido"), 0)

    def test_erros_transitorios_e_permanente(self):
        for erro in (requests.ConnectTimeout(), requests.ConnectionError(), requests.ReadTimeout()):
            with self.subTest(tipo=type(erro).__name__), patch("time.sleep"):
                sessao = Mock()
                sessao.get.side_effect = [erro, resposta(dados={"ok": True})]
                self.assertEqual(seguro.requisitar_json(sessao, "https://teste", {"max_tentativas": 2, "backoff_base_segundos": 0}), {"ok": True})

    def test_pagina_vazia_contradiz_total_registros(self):
        with self.assertRaises(ValueError):
            seguro.validar_pagina({"data": [], "totalPaginas": 1, "totalRegistros": 50}, pagina=1)

    def test_obras_pagina_repetida_nao_validada(self):
        with self.assertRaises(ValueError):
            seguro.validar_pagina({"data": [{"id": 1}], "total_pages": 2, "page_number": 1}, "total_pages", pagina=2)

    def test_falha_escrita_preserva_arquivo_anterior(self):
        with tempfile.TemporaryDirectory() as temp:
            arquivo = Path(temp) / "pagina.json"
            seguro.salvar_json_atomico(arquivo, {"versao": 1})
            with patch.object(seguro.os, "replace", side_effect=OSError("sem espaco")):
                with self.assertRaises(OSError):
                    seguro.salvar_json_atomico(arquivo, {"versao": 2})
            self.assertEqual(json.loads(arquivo.read_text()), {"versao": 1})

    def test_deduplicacao_sem_numero_controle(self):
        a = {"orgaoEntidade": {"cnpj": "123"}, "anoCompra": 2024, "sequencialCompra": 8, "valor": 10}
        b = {**a, "valor": 20}
        self.assertEqual(seguro.chave_compra(a), seguro.chave_compra(b))
        self.assertNotEqual(seguro.chave_compra({"objeto": "a"}), seguro.chave_compra({"objeto": "b"}))

    def test_janelas_outros_tamanhos(self):
        for ano in (2023, 2024):
            for meses in (1, 3, 5, 12):
                with self.subTest(ano=ano, meses=meses):
                    janelas = list(seguro.janelas_ano(ano, meses))
                    self.assertEqual(sum((fim-inicio).days+1 for inicio, fim in janelas), 366 if ano == 2024 else 365)
                    for anterior, atual in zip(janelas, janelas[1:]):
                        self.assertEqual(anterior[1] + timedelta(days=1), atual[0])

    def test_merge_rejeita_chaves_duplicadas(self):
        base = pd.DataFrame([{"codigo_ibge": "2507507", "ano": 2024, "pib": 1}] * 2)
        with self.assertRaises(pd.errors.MergeError):
            etl.combinar_bases([base], {"municipios": MUNICIPIOS, "ano_inicial": 2024, "ano_final": 2024})

    def test_dca_nao_imputa_populacao_e_rp_incompleto(self):
        base = pd.DataFrame([{"codigo_ibge": "2507507", "ano": 2024, "populacao_siconfi": 123,
                              "populacao": None, "restos_pagar_processados": 10, "restos_pagar_nao_processados": None}])
        resultado = etl.combinar_bases([base], {"municipios": MUNICIPIOS, "ano_inicial": 2024, "ano_final": 2024})
        self.assertTrue(resultado.populacao.isna().all())
        self.assertTrue(resultado.restos_pagar_total.isna().all())

    def test_status_campo_sem_dados(self):
        base = pd.DataFrame({"pib": [None]})
        status = etl.gerar_status_variaveis(base, pd.DataFrame()).set_index("variavel")
        self.assertEqual(status.loc["pib", "status_etl"], "campo_presente_sem_observacoes_validas")

    def test_smoke_pncp_cli_isolado_limite_sem_mudar_config(self):
        with tempfile.TemporaryDirectory() as temp:
            raiz = Path(temp)
            config = {"municipios": [{"codigo_ibge": "5105259", "nome": "Lucas do Rio Verde", "uf": "MT"}],
                      "ano_inicial": 2020, "ano_final": 2024, "pncp_intervalo_requisicoes_segundos": 0}
            arquivo = raiz / "config.json"
            arquivo.write_text(json.dumps(config), encoding="utf-8")
            original = arquivo.read_bytes()
            saida = raiz / "output"
            saida.mkdir()
            (saida / "base_municipio_ano.csv").write_text("original")
            sessao = Mock()
            sessao.get.side_effect = [resposta(dados=pagina([compra()], 10)), resposta(dados=pagina([compra("2")], 10, 2))]
            with patch.object(etl, "RAW_DIR", raiz / "raw"), patch.object(etl, "OUTPUT_DIR", saida), \
                 patch.object(etl, "MANUAL_DIR", raiz / "manual"), patch.object(etl, "criar_sessao", return_value=sessao), \
                 patch("sys.argv", ["etl_primario.py", "--config", str(arquivo), "--sources", "pncp", "--smoke-test"]), contextlib.redirect_stdout(io.StringIO()):
                etl.main()
            self.assertEqual(sessao.get.call_count, 2)
            params = sessao.get.call_args.kwargs["params"]
            self.assertEqual(params["dataInicial"], params["dataFinal"])
            self.assertEqual(params["codigoModalidadeContratacao"], 8)
            self.assertEqual(arquivo.read_bytes(), original)
            self.assertEqual((saida / "base_municipio_ano.csv").read_text(), "original")
            base = pd.read_csv(next((saida / "smoke").glob("*/base_municipio_ano.csv")))
            self.assertTrue(base.total_contratacoes.isna().all())


if __name__ == "__main__":
    unittest.main()
