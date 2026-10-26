"""CLI de migração/reprodução Medallion; a coleta legada continua disponível."""
import argparse
import json
from pathlib import Path
import requests
from etl_confiabilidade import FalhaConsulta
from .fontes import (snapshot, ibge_territorial, coleta_legada, siconfi, munic,
                     transferegov_discricionarias, transferegov_especiais)
from .publicacao import construir, publicar

ROOT = Path(__file__).resolve().parents[2]
# Fontes com extração para o Bronze e transformação ainda pendente.
SOMENTE_BRONZE = {'siconfi': siconfi, 'munic': munic,
                  'transferegov_discricionarias': transferegov_discricionarias,
                  'transferegov_especiais': transferegov_especiais}


def carregar_bronze(parser, args, raiz):
    if set(args.sources) - set(SOMENTE_BRONZE):
        parser.error(f'--bronze-only aceita apenas: {", ".join(SOMENTE_BRONZE)}')
    if args.offline and args.refresh:
        parser.error('--offline não permite --refresh')
    resultado = {}
    try:
        with requests.Session() as sessao:
            for nome in args.sources:
                modulo = SOMENTE_BRONZE[nome]
                caminhos = modulo.verificar(raiz) if args.offline else modulo.extrair(sessao, raiz, refresh=args.refresh)
                resultado[nome] = {chave: (len(valor) if isinstance(valor, list) else valor.relative_to(raiz).as_posix())
                                   for chave, valor in caminhos.items()}
    except (ValueError, OSError, KeyError, FalhaConsulta) as exc:
        parser.exit(1, f'Carga Bronze bloqueada: {exc}\n')
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data')
    parser.add_argument('--sources', nargs='+', default=['snapshot'],
                        choices=['snapshot', 'coleta_legada', 'ibge_territorial', *SOMENTE_BRONZE])
    parser.add_argument('--bronze-only', action='store_true',
                        help='Somente extrai para o Bronze as fontes ainda sem transformação')
    parser.add_argument('--input-dir', type=Path, default=ROOT / 'output', help='Saídas da coleta legada quando selecionada')
    modos = parser.add_mutually_exclusive_group()
    modos.add_argument('--resume', action='store_true', help='Reusa Bronze verificado (padrão)')
    modos.add_argument('--refresh', action='store_true', help='Reconsulta somente a fonte territorial selecionada')
    parser.add_argument('--offline', action='store_true', help='Proíbe rede; territorial exige Bronze existente')
    args = parser.parse_args(argv)
    if args.bronze_only:
        return carregar_bronze(parser, args, args.data_dir.resolve())
    if set(args.sources) & set(SOMENTE_BRONZE):
        parser.error('Fontes sem transformação ainda: use --bronze-only')
    if sum(fonte in args.sources for fonte in ['snapshot', 'coleta_legada']) != 1:
        parser.error('Escolha uma única origem do painel: snapshot ou coleta_legada')
    raiz = args.data_dir.resolve()
    try:
        if 'coleta_legada' in args.sources:
            caminhos = coleta_legada.extrair(args.input_dir, raiz)
            base, eventos = coleta_legada.transformar(caminhos)
            painel = 'coleta_legada_importada'
        else:
            caminhos = snapshot.extrair(ROOT, raiz)
            base, eventos = snapshot.transformar(caminhos)
            painel = 'snapshot_legado_verificado'
        referencia = base[['codigo_ibge', 'municipio', 'uf']].drop_duplicates().reset_index(drop=True)
        territorial = None
        proveniencia = {'painel': painel,
                       'referencia_territorial': 'snapshot_legado_sem_validacao_externa',
                       'bronze_painel': {k: p.relative_to(raiz).as_posix() for k, p in caminhos.items()}}
        if 'ibge_territorial' in args.sources:
            indice = raiz / 'ref' / 'ibge_territorial_bronze.json'
            if args.offline and (args.refresh or not indice.exists()):
                parser.error('--offline exige Bronze territorial existente e não permite --refresh')
            with requests.Session() as sessao:
                fontes = ibge_territorial.extrair(sessao, raiz, refresh=args.refresh)
            referencia, territorial = ibge_territorial.transformar(fontes)
            proveniencia['referencia_territorial'] = 'ibge_localidades_oficial'
            proveniencia['bronze_territorial'] = {k: p.relative_to(raiz).as_posix() for k, p in fontes.items()}
        tabelas = construir(base, eventos, referencia, territorial)
        resultado = publicar(tabelas, raiz, proveniencia)
    except (ValueError, OSError, KeyError, FalhaConsulta) as exc:
        parser.exit(1, f'Publicação bloqueada: {exc}\n')
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
