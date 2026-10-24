"""Contratos de identidade e grão; ausência nunca é convertida em zero."""
import pandas as pd


class ViolacaoContrato(ValueError):
    pass


def validar_tabela(quadro, chaves, universo, *, completa=False):
    faltantes = set(chaves) - set(quadro.columns)
    if faltantes:
        raise ViolacaoContrato(f'Chaves ausentes: {sorted(faltantes)}')
    if quadro[chaves].isna().any().any() or quadro.duplicated(chaves).any():
        raise ViolacaoContrato(f'Chave nula ou duplicada: {chaves}')
    if 'codigo_ibge' in quadro:
        codigos = quadro.codigo_ibge.astype('string')
        if not codigos.str.fullmatch(r'25\d{5}').all():
            raise ViolacaoContrato('Código IBGE deve ter sete dígitos e pertencer à PB')
        encontrados = set(codigos)
        if encontrados - universo or (completa and encontrados != universo):
            raise ViolacaoContrato('Municípios incompatíveis com o universo de referência')


def validar_painel(quadro, universo, anos):
    validar_tabela(quadro, ['codigo_ibge', 'ano'], universo, completa=True)
    if set(zip(quadro.codigo_ibge, quadro.ano)) != {(c, a) for c in universo for a in anos}:
        raise ViolacaoContrato('Painel deve conter exatamente o produto município × ano')


def validar_numerica(quadro, coluna, minimo=0, maximo=None, *, nulos=True):
    original = quadro[coluna]
    valores = pd.to_numeric(original, errors='coerce')
    if (original.notna() & valores.isna()).any() or (not nulos and valores.isna().any()):
        raise ViolacaoContrato(f'{coluna}: tipo inválido ou ausência não permitida')
    if ((valores < minimo) | valores.isin([float('inf'), -float('inf')])).any():
        raise ViolacaoContrato(f'{coluna}: valor fora da faixa')
    if maximo is not None and (valores > maximo).any():
        raise ViolacaoContrato(f'{coluna}: valor acima de {maximo}')
