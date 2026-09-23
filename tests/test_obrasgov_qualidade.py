import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd
import requests

import etl_primario as etl
from test_checkpoint1 import resposta
from test_checkpoint2 import MUNICIPIOS


class FakeEspacial:
    metadados = {"fonte_malha": "IBGE", "versao_malha": "2025", "data_download_malha": "2026-09-23", "checksum_malha": "abc"}

    def __init__(self, resultados):
        self.resultados = resultados

    def localizar(self, latitude, longitude):
        return self.resultados.get((float(latitude), float(longitude)))


class ObrasGovQualidade(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for nome, pasta in (("RAW_DIR", "raw"), ("OUTPUT_DIR", "output")):
            p = patch.object(etl, nome, self.root / pasta)
            p.start()
            self.addCleanup(p.stop)
        self.config = {"municipios": MUNICIPIOS, "escopo": {"tipo": "uf", "ufs": ["PB"]},
                       "ano_inicial": 2024, "ano_final": 2024, "max_tentativas": 1}
        self.sessao = Mock(spec=requests.Session)
        self.erros = []

    def resolver(self, item, **kwargs):
        return etl.resolver_atribuicao_obra(item, MUNICIPIOS, **kwargs)

    def test_codigo_oficial_preserva_papel(self):
        r = self.resolver({"codigo_ibge": "2507507"})
        self.assertEqual(r["status_atribuicao_territorial"], "exata")
        self.assertEqual(r["codigo_ibge_localizacao"], "2507507")
        self.assertEqual(r["metodo_atribuicao"], "codigo_ibge_oficial")

    def test_executor_tomador_iguais_e_conflitantes(self):
        igual = {"executores": [{"organizacao_executor": "MUNICIPIO DE JOAO PESSOA"}],
                 "tomadores": [{"organizacao_tomador": "PREFEITURA MUNICIPAL DE JOAO PESSOA"}]}
        r = self.resolver(igual)
        self.assertEqual(r["codigo_ibge_executor"], "2507507")
        self.assertEqual(r["codigo_ibge_tomador"], "2507507")
        self.assertEqual(r["status_atribuicao_territorial"], "exata")
        self.assertEqual(r["metodo_atribuicao"], "exato_executor_tomador")
        igual["tomadores"] = [{"organizacao_tomador": "MUNICIPIO DE CAMPINA GRANDE"}]
        self.assertEqual(self.resolver(igual)["status_atribuicao_territorial"], "conflitante")

    def test_codigo_oficial_fora_conflita_com_nome_dentro(self):
        item = {"codigo_ibge": "5105259", "executores": [{"organizacao_executor": "MUNICIPIO DE JOAO PESSOA"}]}
        r = self.resolver(item)
        self.assertEqual(r["status_atribuicao_territorial"], "conflitante")
        self.assertEqual({e["codigo_ibge"] for e in r["evidencias_atribuicao"]}, {"5105259", "2507507"})

    def test_cnpj_municipal_unico_com_proveniencia(self):
        mapa = {"12345678000100": {"codigo_ibge": "2504009", "fonte": "TCE-PB", "versao": "2026", "entidade_municipal": True}}
        item = {"executores": [{"cnpj_executor": "12.345.678/0001-00", "organizacao_executor": "FUNDO MUNICIPAL DE SAUDE"}]}
        r = self.resolver(item, mapa_cnpj=mapa)
        self.assertEqual(r["codigo_ibge_executor"], "2504009")
        self.assertEqual(r["fonte_mapeamento_cnpj"], "TCE-PB")
        self.assertEqual(r["metodo_atribuicao"], "cnpj_municipal")

    def test_nome_exato_e_nome_generico(self):
        explicito = {"executores": [{"organizacao_executor": "FUNDO MUNICIPAL DE SAUDE DE CAMPINA GRANDE"}]}
        self.assertEqual(self.resolver(explicito)["codigo_ibge_executor"], "2504009")
        generico = {"executores": [{"organizacao_executor": "FUNDO MUNICIPAL DE SAUDE"}]}
        r = self.resolver(generico)
        self.assertEqual(r["status_atribuicao_territorial"], "nao_identificada")
        self.assertTrue(r["indicio_municipal_pendente"])

    def test_cep_unico_e_generico(self):
        mapa = {"58000000": {"codigo_ibge": "2507507", "fonte": "Correios", "versao": "2026", "generico": False},
                "58000001": {"codigo_ibge": "2507507", "fonte": "Correios", "versao": "2026", "generico": True}}
        r = self.resolver({"nr_cep": "58000-000"}, mapa_cep=mapa)
        self.assertEqual(r["metodo_atribuicao"], "cep_municipal")
        self.assertTrue(r["cep_validado"])
        self.assertEqual(self.resolver({"nr_cep": "58000-001"}, mapa_cep=mapa)["status_atribuicao_territorial"], "nao_identificada")
        incompleto = {"58000002": {"codigo_ibge": "2507507"}}
        self.assertEqual(self.resolver({"nr_cep": "58000-002"}, mapa_cep=incompleto)["status_atribuicao_territorial"], "nao_identificada")

    def test_coordenada_unica_limite_e_multiterritorial(self):
        espacial = FakeEspacial({(-7, -35): {"codigos": ["2507507"], "limite": False},
                                 (-8, -36): {"codigos": ["2504009"], "limite": False},
                                 (-9, -37): {"codigos": ["2507507"], "limite": True}})
        um = self.resolver({"pins": [{"latitude": -7, "longitude": -35}]}, resolver_espacial=espacial)
        self.assertEqual(um["codigo_ibge_localizacao"], "2507507")
        self.assertEqual(um["papel_municipio_modelagem"], "localizacao")
        limite = self.resolver({"pins": [{"latitude": -9, "longitude": -37}]}, resolver_espacial=espacial)
        self.assertEqual(limite["status_atribuicao_territorial"], "nao_identificada")
        multi = self.resolver({"pins": [{"latitude": -7, "longitude": -35}, {"latitude": -8, "longitude": -36}]}, resolver_espacial=espacial)
        self.assertEqual(multi["status_atribuicao_territorial"], "multiterritorial")
        self.assertEqual(multi["quantidade_municipios_atribuidos"], 2)

    def test_pins_fora_do_catalogo_reduzido_continuam_multiterritoriais(self):
        espacial = FakeEspacial({(-7, -35): {"codigos": ["2507507"], "limite": False},
                                 (-8, -36): {"codigos": ["2504009"], "limite": False}})
        r = etl.resolver_atribuicao_obra({"pins": [{"latitude": -7, "longitude": -35},
                                                     {"latitude": -8, "longitude": -36}]},
                                            MUNICIPIOS[:1], resolver_espacial=espacial)
        self.assertEqual(r["status_atribuicao_territorial"], "multiterritorial")
        self.assertEqual(r["quantidade_municipios_atribuidos"], 2)

    def test_ponto_resolvido_e_ponto_ambiguo_nao_produzem_exata(self):
        espacial = FakeEspacial({(-7, -35): {"codigos": ["2507507"], "limite": False},
                                 (-9, -37): {"codigos": ["2507507"], "limite": True}})
        r = self.resolver({"pins": [{"latitude": -7, "longitude": -35},
                                     {"latitude": -9, "longitude": -37}]}, resolver_espacial=espacial)
        self.assertEqual(r["status_atribuicao_territorial"], "conflitante")
        self.assertTrue(any(e["metodo"] == "coordenada_ambigua" for e in r["evidencias_atribuicao"]))

    def test_multiplos_pontos_no_mesmo_municipio_permanecem_unicos(self):
        espacial = FakeEspacial({(-7, -35): {"codigos": ["2507507"], "limite": False},
                                 (-7.1, -35.1): {"codigos": ["2507507"], "limite": False}})
        r = self.resolver({"pins": [{"latitude": -7, "longitude": -35},
                                     {"latitude": -7.1, "longitude": -35.1}]}, resolver_espacial=espacial)
        self.assertEqual(r["status_atribuicao_territorial"], "exata")
        self.assertEqual(r["quantidade_municipios_atribuidos"], 1)

    def test_cache_malha_e_indisponibilidade_nao_fazem_rede_extra(self):
        geojson, metadados = self.root / "malha.geojson", self.root / "malha.json"
        geojson.write_text("{}", encoding="utf-8")
        metadados.write_text("{}", encoding="utf-8")
        self.config.update(obrasgov_malha_geojson=str(geojson), obrasgov_malha_metadados=str(metadados))
        self.sessao.get.return_value = resposta(dados={"data": [], "total_pages": 0, "total_items": 0})
        with patch.object(etl, "ResolvedorMalhaIBGE", return_value=FakeEspacial({})) as construtor:
            etl.coletar_obrasgov(self.sessao, self.config, self.erros)
        construtor.assert_called_once()
        self.assertEqual(self.sessao.get.call_count, 1)
        self.sessao.get.reset_mock()
        with patch.object(etl, "ResolvedorMalhaIBGE", side_effect=RuntimeError("sem motor")):
            etl.coletar_obrasgov(self.sessao, self.config, self.erros)
        self.sessao.get.assert_not_called()

    def test_federal_sem_territorio_fora_escopo(self):
        item = {"organizacao_resp": "DEPARTAMENTO NACIONAL DE INFRAESTRUTURA DE TRANSPORTES",
                "executores": [{"organizacao_executor": "DNIT"}]}
        self.assertEqual(self.resolver(item)["status_atribuicao_territorial"], "fora_escopo_municipal")

    def test_temporalidade_alvo_censura_e_legado(self):
        base = {"ano_cadastro": 2024, "dt_inicial_prevista": "2021-02-03", "dt_final_prevista": "2025-01-01"}
        for situacao, alvo, censurado in (("Concluída", 0, False), ("Cancelada", 1, False),
                                          ("Inacabada", 1, False), ("Paralisada", 1, False),
                                          ("Cadastrada", None, True), ("Em execução", None, True)):
            with self.subTest(situacao=situacao):
                r = etl.campos_temporais_obras({**base, "situacao": situacao}, 2024)
                self.assertEqual(r["ano"], 2024)
                self.assertEqual(r["ano_cadastro"], 2024)
                self.assertEqual(r["ano_inicio_previsto"], 2021)
                self.assertEqual(r["evento_adverso_execucao"], alvo)
                self.assertEqual(r["obra_parada"], alvo)
                self.assertEqual(r["projeto_censurado"], censurado)

    def test_rejeitado_federal_nao_contamina_ano_e_pendente_nao_vira_zero(self):
        federal = {"id_projeto_investimento": "f", "organizacao_resp": "MINISTERIO DOS TRANSPORTES", "situacao": "Em execução"}
        self.sessao.get.return_value = resposta(dados={"data": [federal], "total_pages": 1, "total_items": 1})
        _, base = etl.coletar_obrasgov(self.sessao, self.config, self.erros)
        self.assertTrue(base.total_obras.eq(0).all())
        self.assertTrue(base.status_agregado.eq("completo_no_escopo").all())

    def test_pendente_municipal_publica_observado_parcial(self):
        pendente = {"id_projeto_investimento": "p", "executores": [{"organizacao_executor": "FUNDO MUNICIPAL DE SAUDE"}]}
        self.sessao.get.return_value = resposta(dados={"data": [pendente], "total_pages": 1, "total_items": 1})
        _, base = etl.coletar_obrasgov(self.sessao, self.config, self.erros)
        self.assertTrue(base.total_obras.isna().all())
        self.assertTrue(base.valor_observado_total_obras.isna().all())
        self.assertTrue(base.status_agregado.eq("observado_parcial").all())
        self.assertTrue((etl.OUTPUT_DIR / "cobertura_territorial_obrasgov.csv").exists())

    def test_falha_api_nao_publica_zero_observado(self):
        self.sessao.get.side_effect = requests.ConnectionError("falha")
        _, base = etl.coletar_obrasgov(self.sessao, self.config, self.erros)
        self.assertTrue(base.valor_observado_total_obras.isna().all())
        self.assertTrue(base.status_agregado.eq("indisponivel").all())

    def test_ano_cadastro_divergente_nao_entra_no_ano_consultado(self):
        obra = {"id_projeto_investimento": "ano", "codigo_ibge": "2507507", "ano_cadastro": 2023}
        self.sessao.get.return_value = resposta(dados={"data": [obra], "total_pages": 1, "total_items": 1})
        eventos, base = etl.coletar_obrasgov(self.sessao, self.config, self.erros)
        self.assertTrue(eventos.empty)
        self.assertTrue(base.total_obras.isna().all())
        rejeitados = json.loads((etl.OUTPUT_DIR / "rejeitados_obrasgov.json").read_text(encoding="utf-8"))
        self.assertEqual(rejeitados[0]["motivo"], "ano_cadastro_divergente")

    def test_evento_unico_e_rerun_idempotente(self):
        obra = {"id_projeto_investimento": "1", "codigo_ibge": "2507507", "situacao": "Concluída", "ano_cadastro": 2024}
        self.sessao.get.return_value = resposta(dados={"data": [obra, obra], "total_pages": 1, "total_items": 2})
        primeiro, _ = etl.coletar_obrasgov(self.sessao, self.config, self.erros)
        self.sessao.get.reset_mock()
        segundo, _ = etl.coletar_obrasgov(self.sessao, self.config, self.erros)
        self.assertEqual(primeiro.id_projeto_investimento.tolist(), ["1"])
        pd.testing.assert_frame_equal(primeiro, segundo)

    def test_saida_multiterritorial_e_relatorio_anual(self):
        espacial = FakeEspacial({(-7, -35): {"codigos": ["2507507"], "limite": False},
                                 (-8, -36): {"codigos": ["2504009"], "limite": False},
                                 (-9, -37): {"codigos": ["2507507"], "limite": True}})
        self.config["_obrasgov_resolvedor_espacial"] = espacial
        obra = {"id_projeto_investimento": "m", "pins": [{"latitude": -7, "longitude": -35},
                                                              {"latitude": -8, "longitude": -36},
                                                              {"latitude": -9, "longitude": -37}]}
        self.sessao.get.return_value = resposta(dados={"data": [obra], "total_pages": 1, "total_items": 1})
        eventos, base = etl.coletar_obrasgov(self.sessao, self.config, self.erros)
        self.assertTrue(eventos.empty)
        self.assertTrue(base.status_agregado.eq("observado_parcial").all())
        multi = json.loads((etl.OUTPUT_DIR / "projetos_multiterritoriais_obrasgov.json").read_text(encoding="utf-8"))
        self.assertEqual(multi[0]["codigos_ibge_envolvidos"], ["2504009", "2507507"])
        relatorio = pd.read_csv(etl.OUTPUT_DIR / "cobertura_territorial_obrasgov.csv")
        self.assertEqual(relatorio.iloc[0].projetos_multiterritoriais, 1)

    def test_resultados_nao_recomendados_e_quase_constante(self):
        base = pd.DataFrame({"codigo_ibge": ["2507507"] * 20, "ano": range(2000, 2020),
                             "evento_adverso_execucao": [0, 1] * 10,
                             "percentual_execucao_medio": range(20),
                             "obras_sem_estudo_viabilidade": [1] * 20})
        qualidade, _ = etl.auditar_qualidade(base, {})
        q = qualidade.set_index("variavel")
        self.assertEqual(q.loc["evento_adverso_execucao", "recomendacao_inicial"], "nao_usar_como_preditor_resultado")
        self.assertEqual(q.loc["percentual_execucao_medio", "recomendacao_inicial"], "nao_usar_como_preditor_resultado")
        self.assertEqual(q.loc["obras_sem_estudo_viabilidade", "recomendacao_inicial"], "remover_constante_ou_quase_constante")


if __name__ == "__main__":
    unittest.main()
