import copy
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd
import requests
import etl_primario as etl


def resposta(status=200, dados=None, headers=None):
    r = requests.Response()
    r.status_code = status
    r.headers.update(headers or {})
    r._content = json.dumps(dados).encode() if dados is not None else b""
    r.url = "https://pncp.gov.br/teste"
    return r


def pagina(dados=None, total=1, numero=1):
    return {"data": dados or [], "totalPaginas": total, "numeroPagina": numero}


def compra(id="controle-1"):
    return {"numeroControlePNCP": id, "unidadeOrgao": {"codigoIbge": "5105259"},
            "dataPublicacaoPncp": "2024-01-10", "valorTotalEstimado": 10}


class Checkpoint1(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for nome, pasta in (("RAW_DIR", "raw"), ("OUTPUT_DIR", "output")):
            p = patch.object(etl, nome, self.root / pasta)
            p.start()
            self.addCleanup(p.stop)
        self.config = {"municipios": [{"codigo_ibge": "5105259", "nome": "Lucas do Rio Verde", "uf": "MT"}],
                       "ano_inicial": 2024, "ano_final": 2024, "pncp_janela_meses": 12,
                       "pncp_modalidades": [8], "pncp_max_tentativas": 3,
                       "pncp_intervalo_requisicoes_segundos": 0, "pncp_backoff_base_segundos": 0}
        self.sessao = Mock(spec=requests.Session)
        self.erros = []

    def coletar(self):
        return etl.coletar_pncp(self.sessao, self.config, self.erros)

    def test_429_retry_after(self):
        self.sessao.get.side_effect = [resposta(429, headers={"Retry-After": "7"}), resposta(dados=pagina([compra()]))]
        with patch("time.sleep") as sleep:
            _, base = self.coletar()
        self.assertEqual(base.iloc[0].total_contratacoes, 1)
        self.assertTrue(any(c.args[0] >= 7 for c in sleep.call_args_list))
        self.assertEqual(self.sessao.get.call_count, 2)

    def test_timeout_depois_sucesso(self):
        self.sessao.get.side_effect = [requests.ReadTimeout("leitura"), resposta(dados=pagina([compra()]))]
        with patch("time.sleep"):
            _, base = self.coletar()
        self.assertEqual(base.iloc[0].total_contratacoes, 1)

    def test_503_esgota_tentativas_ausente(self):
        self.sessao.get.return_value = resposta(503)
        with patch("time.sleep"):
            _, base = self.coletar()
        self.assertEqual(self.sessao.get.call_count, 3)
        self.assertTrue(pd.isna(base.iloc[0].total_contratacoes))
        self.assertEqual(base.iloc[0].cobertura_pncp, "falhou")
        self.assertTrue(self.erros)

    def test_cache_valido_reutilizado(self):
        self.sessao.get.return_value = resposta(dados=pagina([compra()]))
        self.coletar()
        self.sessao.get.reset_mock()
        _, base = self.coletar()
        self.sessao.get.assert_not_called()
        self.assertEqual(base.iloc[0].total_contratacoes, 1)

    def test_cache_corrompido_reconsultado(self):
        self.sessao.get.return_value = resposta(dados=pagina([compra()]))
        self.coletar()
        arquivos = list((etl.RAW_DIR / "pncp" / "pages").glob("*.json"))
        self.assertEqual(len(arquivos), 1)
        arquivos[0].write_text("{", encoding="utf-8")
        self.coletar()
        self.assertEqual(self.sessao.get.call_count, 2)

    def test_deduplicacao_antes_soma(self):
        self.sessao.get.return_value = resposta(dados=pagina([compra(), compra()]))
        eventos, base = self.coletar()
        self.assertEqual(len(eventos), 1)
        self.assertEqual(base.iloc[0].valor_estimado_contratacoes, 10)

    def test_vazio_confirmado_zero(self):
        self.sessao.get.return_value = resposta(204)
        _, base = self.coletar()
        self.assertEqual(base.iloc[0].total_contratacoes, 0)
        self.assertEqual(base.iloc[0].cobertura_pncp, "sem_registros_confirmado")

    def test_erro_permanente_sem_retry(self):
        self.sessao.get.return_value = resposta(400)
        _, base = self.coletar()
        self.assertEqual(self.sessao.get.call_count, 1)
        self.assertTrue(pd.isna(base.iloc[0].total_contratacoes))

    def test_janelas_bissexto_sem_lacuna(self):
        self.assertTrue(hasattr(etl, "janelas_ano"), "Gerador de janelas ainda ausente")
        janelas = list(etl.janelas_ano(2024, 3))
        self.assertEqual(janelas[0], (date(2024, 1, 1), date(2024, 3, 31)))
        dias = [a + timedelta(days=i) for a, b in janelas for i in range((b-a).days+1)]
        self.assertEqual(len(set(dias)), 366)
        self.assertEqual(dias[-1], date(2024, 12, 31))

    def test_modo_municipal(self):
        self.sessao.get.return_value = resposta(dados=pagina([compra()]))
        _, base = self.coletar()
        params = self.sessao.get.call_args.kwargs["params"]
        self.assertEqual(params["codigoMunicipioIbge"], "5105259")
        self.assertNotIn("uf", params)
        self.assertEqual(base.iloc[0].codigo_ibge, "5105259")

    def test_interrupcao_retoma_pagina_dois(self):
        self.sessao.get.side_effect = [resposta(dados=pagina([compra()], 2)), KeyboardInterrupt()]
        with self.assertRaises(KeyboardInterrupt):
            self.coletar()
        self.sessao.get.side_effect = [resposta(dados=pagina([compra("controle-2")], 2, 2))]
        self.sessao.get.reset_mock()
        eventos, base = self.coletar()
        self.assertEqual(self.sessao.get.call_count, 1)
        self.assertEqual(self.sessao.get.call_args.kwargs["params"]["pagina"], 2)
        self.assertEqual(len(eventos), 2)
        self.assertEqual(base.iloc[0].total_contratacoes, 2)

    def test_pagina_parcial_nao_vira_total(self):
        self.sessao.get.side_effect = [resposta(dados=pagina([compra()], 2)), resposta(400)]
        eventos, base = self.coletar()
        self.assertEqual(len(eventos), 1)
        self.assertTrue(pd.isna(base.iloc[0].total_contratacoes))
        self.assertEqual(base.iloc[0].cobertura_pncp, "parcial")

    def test_json_invalido_nao_vira_zero(self):
        self.sessao.get.return_value = resposta(dados={"mensagem": "erro"})
        _, base = self.coletar()
        self.assertFalse(base.empty)
        self.assertTrue(pd.isna(base.iloc[0].total_contratacoes))

    def test_refresh_interrompido_nao_mistura_pagina_antiga(self):
        self.sessao.get.side_effect = [resposta(dados=pagina([compra("antigo-1")], 2)),
                                      resposta(dados=pagina([compra("antigo-2")], 2, 2))]
        self.coletar()
        self.config["_refresh_fontes"] = ["pncp"]
        self.sessao.get.side_effect = [resposta(dados=pagina([compra("novo-1")], 2)), KeyboardInterrupt()]
        with self.assertRaises(KeyboardInterrupt):
            self.coletar()
        self.config.pop("_refresh_fontes")
        self.sessao.get.side_effect = [resposta(dados=pagina([compra("novo-2")], 2, 2))]
        self.sessao.get.reset_mock()
        eventos, base = self.coletar()
        self.assertEqual(self.sessao.get.call_count, 1)
        self.assertEqual(set(eventos.numero_controle_pncp), {"novo-1", "novo-2"})
        self.assertEqual(base.iloc[0].total_contratacoes, 2)

    def test_paginas_nao_somam_total_declarado(self):
        p1 = {**pagina([compra()], 2), "totalRegistros": 4}
        p2 = {**pagina([compra("2")], 2, 2), "totalRegistros": 4}
        self.sessao.get.side_effect = [resposta(dados=p1), resposta(dados=p2)]
        _, base = self.coletar()
        self.assertTrue(pd.isna(base.iloc[0].total_contratacoes))
        self.assertEqual(base.iloc[0].cobertura_pncp, "parcial")


if __name__ == "__main__":
    unittest.main()
