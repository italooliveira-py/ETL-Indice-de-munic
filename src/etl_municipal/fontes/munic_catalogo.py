"""Catálogo versionado de variáveis MUNIC por edição, bloco e código original."""
from __future__ import annotations

import json
from pathlib import Path


class CatalogoMunicError(ValueError):
    """Catálogo MUNIC ausente, inválido ou sem a variável solicitada."""


_CAMINHO = Path(__file__).resolve().parents[3] / 'data' / 'reference' / 'munic' / 'variaveis.json'
_CATALOGO = json.loads(_CAMINHO.read_text(encoding='utf-8'))
EDICOES_AUTORIZADAS = tuple(_CATALOGO['edicoes_autorizadas'])

_DEFINICOES = {
    (item['edicao'], item['bloco'], item['codigo_original']): item
    for item in _CATALOGO['variaveis']
}


def status_edicao(edicao: int) -> str:
    return 'observada' if edicao in EDICOES_AUTORIZADAS else 'edicao_indisponivel'


def definicao(edicao: int, bloco: str, codigo_original: str) -> dict:
    try:
        return dict(_DEFINICOES[(int(edicao), bloco, codigo_original)])
    except KeyError as exc:
        if bloco == 'recursos_humanos':
            variavel = _CATALOGO.get('mapas_rh', {}).get(str(int(edicao)), {}).get(codigo_original)
            if variavel:
                return {
                    'edicao': int(edicao), 'bloco': bloco, 'codigo_original': codigo_original,
                    'aliases': [codigo_original], 'variavel': variavel, 'tipo': 'numerico',
                    'unidade': 'pessoas', 'comparabilidade': 'recorrente',
                    'decisao_uso': 'candidata_gold',
                }
        raise CatalogoMunicError(
            f'Variável MUNIC não catalogada: edição={edicao}, bloco={bloco}, '
            f'código={codigo_original}'
        ) from exc


def aliases(edicao: int, bloco: str, codigo_original: str) -> tuple[str, ...]:
    return tuple(definicao(edicao, bloco, codigo_original).get('aliases', ()))
