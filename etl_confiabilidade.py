"""Compatibilidade para importações existentes."""
import sys
from src.etl_municipal.legado import confiabilidade as _impl
sys.modules[__name__] = _impl
