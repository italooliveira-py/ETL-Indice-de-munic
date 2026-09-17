import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd
import requests
import etl_primario as etl
from test_checkpoint1 import resposta, pagina, compra


MUNICIPIOS = [{"codigo_ibge": "2507507", "nome": "João Pessoa", "uf": "PB"},
              {"codigo_ibge": "2504009", "nome": "Campina Grande", "uf": "PB"}]


class Checkpoint2(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for nome, pasta in (("RAW_DIR", "raw"), ("OUTPUT_DIR", "output")):
            p = patch.object(etl, nome, self.root / pasta)
            p.start()
            self.addCleanup(p.stop)
        self.config = {"municipios": MUNICIPIOS, "escopo": {"tipo": "uf", "ufs": ["PB"]},
                       "ano_inicial": 2024, "ano_final": 2024, "pncp_janela_meses": 12,
                       "pncp_modalidades": [8], "max_tentativas": 1,
                       "pncp_intervalo_requisicoes_segundos": 0,
                       "siconfi_intervalo_requisicoes_segundos": 0}
        self.sessao = Mock(spec=requests.Session)
        self.erros = []

    def test_resolver_catalogo_uf(self):
        self.assertTrue(hasattr(etl, "resolver_municipios"))
        self.sessao.get.return_value = resposta(dados=[{"id": 2507507, "nome": "João Pessoa"}])
        resultado = etl.resolver_municipios(self.sessao, self.config)
        self.assertEqual(resultado, MUNICIPIOS[:1])
        self.assertTrue((etl.RAW_DIR / "ibge" / "municipios_PB.json").exists())

    def test_municipios_legado_sem_chamada(self):
        self.assertTrue(hasattr(etl, "resolver_municipios"))
        del self.config["escopo"]
        self.assertEqual(etl.resolver_municipios(self.sessao, self.config), MUNICIPIOS)
        self.sessao.get.assert_not_called()

    def test_catalogo_vazio_erro_claro(self):
        self.assertTrue(hasattr(etl, "resolver_municipios"))
        self.sessao.get.return_value = resposta(dados=[])
        with self.assertRaises(ValueError):
            etl.resolver_municipios(self.sessao, self.config)

    def test_esqueleto_e_merge_codigo_ano(self):
        self.config["ano_inicial"] = 2023
        base = pd.DataFrame([{"codigo_ibge": "2507507", "municipio": "JOAO PESSOA", "uf": "XX", "ano": 2024, "pib": 123}])
        resultado = etl.combinar_bases([base], self.config)
        self.assertEqual(len(resultado), 4)
        linha = resultado.query("codigo_ibge == '2507507' and ano == 2024").iloc[0]
        self.assertEqual(linha.pib, 123)
        self.assertEqual(linha.municipio, "João Pessoa")
        self.assertEqual(linha.uf, "PB")
        self.assertEqual(resultado.pib.isna().sum(), 3)

    def test_pncp_uf_uma_chamada_filtro_rejeitados(self):
        pb = compra("pb")
        pb["unidadeOrgao"]["codigoIbge"] = "2507507"
        sem_codigo = {"numeroControlePNCP": "sem-codigo"}
        self.sessao.get.return_value = resposta(dados=pagina([pb, compra("mt"), sem_codigo]))
        eventos, base = etl.coletar_pncp(self.sessao, self.config, self.erros)
        self.assertEqual(self.sessao.get.call_count, 1)
        params = self.sessao.get.call_args.kwargs["params"]
        self.assertEqual(params.get("uf"), "PB")
        self.assertNotIn("codigoMunicipioIbge", params)
        self.assertEqual(eventos.codigo_ibge.tolist(), ["2507507"])
        self.assertEqual(len(base), 2)
        self.assertTrue((etl.OUTPUT_DIR / "rejeitados_pncp.json").exists())
        self.assertTrue(base.total_contratacoes.isna().all())

    def test_pncp_periodo_independente(self):
        self.config["ano_inicial"] = 2020
        self.config["ano_final"] = 2022
        self.sessao.get.return_value = resposta(204)
        _, agregado = etl.coletar_pncp(self.sessao, self.config, self.erros)
        base = etl.combinar_bases([agregado], self.config)
        self.assertTrue(base.loc[base.ano < 2022, "total_contratacoes"].isna().all())
        self.assertTrue(base.loc[base.ano == 2022, "total_contratacoes"].eq(0).all())
        self.assertEqual(self.sessao.get.call_count, 1)

    def test_siconfi_cache_legado(self):
        self.config["municipios"] = MUNICIPIOS[:1]
        dados = {"items": [{"cod_ibge": 2507507, "exercicio": 2024, "anexo": "DCA-Anexo I-D", "cod_conta": "TotalDespesas", "coluna": "Despesas Liquidadas", "valor": 42}], "hasMore": False}
        etl.salvar_json(etl.RAW_DIR / "siconfi" / "dca_2507507_2024.json", dados)
        self.sessao.get.return_value = resposta(dados=dados)
        base = etl.coletar_siconfi(self.sessao, self.config, self.erros)
        self.sessao.get.assert_not_called()
        self.assertEqual(base.iloc[0].despesa_total_liquidada, 42)

    def test_siconfi_paginacao_e_retomada(self):
        self.config["municipios"] = MUNICIPIOS[:1]
        primeiro = {"items": [{"cod_ibge": 2507507, "exercicio": 2024}], "hasMore": True,
                    "links": [{"rel": "next", "href": "https://apidatalake.tesouro.gov.br/ords/siconfi/tt/dca?offset=1"}]}
        segundo = {"items": [{"cod_ibge": 2507507, "exercicio": 2024, "anexo": "DCA-Anexo I-D", "cod_conta": "TotalDespesas", "coluna": "Despesas Liquidadas", "valor": 42}], "hasMore": False}
        self.sessao.get.side_effect = [resposta(dados=primeiro), KeyboardInterrupt()]
        with self.assertRaises(KeyboardInterrupt):
            etl.coletar_siconfi(self.sessao, self.config, self.erros)
        self.sessao.get.reset_mock()
        self.sessao.get.side_effect = [resposta(dados=segundo)]
        base = etl.coletar_siconfi(self.sessao, self.config, self.erros)
        self.assertEqual(self.sessao.get.call_count, 1)
        self.assertEqual(base.iloc[0].despesa_total_liquidada, 42)

    def test_obras_sem_atribuicao_por_descricao(self):
        obra = {"id_projeto_investimento": "1", "desc_endereco": "João Pessoa", "desc_nome": "Obra", "executores": []}
        self.sessao.get.return_value = resposta(dados={"data": [obra], "total_pages": 1})
        eventos, base = etl.coletar_obrasgov(self.sessao, self.config, self.erros)
        self.assertTrue(eventos.empty)
        self.assertEqual(self.sessao.get.call_count, 1)
        self.assertTrue((etl.OUTPUT_DIR / "rejeitados_obrasgov.json").exists())
        self.assertTrue(base.total_obras.isna().all())

    def test_obras_nome_exato_ambiguidades(self):
        self.assertTrue(hasattr(etl, "identificar_municipio_obra"))
        obra = {"executores": [{"organizacao_executor": "MUNICIPIO DE JOAO PESSOA"}]}
        m, motivo = etl.identificar_municipio_obra(obra, MUNICIPIOS)
        self.assertEqual(m["codigo_ibge"], "2507507")
        obra["tomadores"] = [{"organizacao_tomador": "PREFEITURA MUNICIPAL DE CAMPINA GRANDE"}]
        self.assertIsNone(etl.identificar_municipio_obra(obra, MUNICIPIOS)[0])
        obra = {"executores": [{"organizacao_executor": "MUNICIPIO DE JOAO PESSOA DO SUL"}]}
        self.assertIsNone(etl.identificar_municipio_obra(obra, MUNICIPIOS)[0])

    def test_obras_cache_pagina(self):
        self.sessao.get.return_value = resposta(dados={"data": [], "total_pages": 0})
        etl.coletar_obrasgov(self.sessao, self.config, self.erros)
        self.sessao.get.reset_mock()
        _, base = etl.coletar_obrasgov(self.sessao, self.config, self.erros)
        self.sessao.get.assert_not_called()
        self.assertTrue(base.total_obras.eq(0).all())

    def test_sidra_consulta_em_lote(self):
        self.config["ano_inicial"] = 2023
        self.config["ano_final"] = 2023
        self.sessao.get.return_value = resposta(dados=[{"resultados": [{"series": [
            {"localidade": {"id": "2507507"}, "serie": {"2023": "12"}},
            {"localidade": {"id": "2504009"}, "serie": {"2023": "34"}}]}]}])
        base = etl.coletar_ibge(self.sessao, self.config, self.erros)
        self.assertEqual(len(base), 2)
        self.assertEqual(self.sessao.get.call_count, 2)
        self.assertEqual(self.sessao.get.call_args.kwargs["params"]["localidades"], "N6[2507507,2504009]")
        self.assertTrue(all("2507507" in c.kwargs["params"]["localidades"] and "2504009" in c.kwargs["params"]["localidades"] for c in self.sessao.get.call_args_list))
        self.assertEqual(base.populacao.sum(), 46)

    def test_auditoria_cobertura_metadados(self):
        base = pd.DataFrame({"codigo_ibge": ["2507507"] * 25, "ano": list(range(2000, 2025)),
                             "pib": list(range(25)), "populacao": list(range(25)),
                             "total_obras": [None] * 25})
        qualidade, pares = etl.auditar_qualidade(base, self.config)
        pib = qualidade.set_index("variavel").loc["pib"]
        self.assertTrue({"fonte", "dimensao", "tipo", "quantidade_municipios", "quantidade_anos", "percentual_faltantes", "primeiro_ano", "ultimo_ano", "possivel_vazamento_temporal", "mudanca_metodologica"}.issubset(qualidade.columns))
        self.assertEqual(pib.cobertura, 1)
        self.assertEqual(len(pares), 1)
        self.assertTrue(etl.auditar_qualidade(base.head(19), self.config)[1].empty)

    def test_sidra_vazio_confirmado_permanece_ausente(self):
        self.sessao.get.return_value = resposta(dados=[])
        base = etl.coletar_ibge(self.sessao, self.config, self.erros)
        self.assertEqual(self.erros, [])
        self.assertTrue(base.pib.isna().all())
        self.assertTrue(base.populacao.isna().all())

    def test_dca_valor_ausente_nao_zero(self):
        itens = [{"anexo": "a", "cod_conta": "c", "coluna": "v", "valor": None}]
        self.assertIsNone(etl.valor_dca(itens, "a", "c", "v"))

    def test_obras_municipal_descarta_outro_codigo_sem_perder_alvo(self):
        self.config.pop("escopo")
        self.config["municipios"] = MUNICIPIOS[:1]
        obras = [{"id_projeto_investimento": "1", "codigo_ibge": "2507507", "situacao": "Concluída"},
                 {"id_projeto_investimento": "2", "codigo_ibge": "2504009", "situacao": "Concluída"}]
        self.sessao.get.side_effect = [resposta(dados={"data": obras, "total_pages": 1}),
                                      resposta(dados={"data": [], "total_pages": 0}), resposta(dados={"data": [], "total_pages": 0})]
        _, base = etl.coletar_obrasgov(self.sessao, self.config, self.erros)
        self.assertEqual(base.iloc[0].total_obras, 1)

    def test_obras_municipal_descarta_nome_catalogado_fora_escopo(self):
        self.config.pop("escopo")
        self.config["municipios"] = MUNICIPIOS[:1]
        etl.salvar_json(etl.RAW_DIR / "ibge" / "municipios_PB.json", [{"id": int(m["codigo_ibge"]), "nome": m["nome"]} for m in MUNICIPIOS])
        obras = [{"id_projeto_investimento": "1", "codigo_ibge": "2507507", "situacao": "Concluída"},
                 {"id_projeto_investimento": "2", "executores": [{"organizacao_executor": "MUNICIPIO DE CAMPINA GRANDE"}]}]
        self.sessao.get.side_effect = [resposta(dados={"data": obras, "total_pages": 1}),
                                      resposta(dados={"data": [], "total_pages": 0}), resposta(dados={"data": [], "total_pages": 0})]
        _, base = etl.coletar_obrasgov(self.sessao, self.config, self.erros)
        self.assertEqual(base.iloc[0].total_obras, 1)

    def test_obras_municipal_executor_tomador_de_cidades_diferentes(self):
        self.config.pop("escopo")
        self.config["municipios"] = MUNICIPIOS[:1]
        etl.salvar_json(etl.RAW_DIR / "ibge" / "municipios_PB.json", [{"id": int(m["codigo_ibge"]), "nome": m["nome"]} for m in MUNICIPIOS])
        obra = {"id_projeto_investimento": "1", "executores": [{"organizacao_executor": "MUNICIPIO DE JOAO PESSOA"}],
                "tomadores": [{"organizacao_tomador": "MUNICIPIO DE CAMPINA GRANDE"}]}
        self.sessao.get.return_value = resposta(dados={"data": [obra], "total_pages": 1})
        eventos, base = etl.coletar_obrasgov(self.sessao, self.config, self.erros)
        self.assertTrue(eventos.empty)
        self.assertTrue(pd.isna(base.iloc[0].total_obras))


if __name__ == "__main__":
    unittest.main()
