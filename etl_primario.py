"""Entrada compatível; implementação em src/etl_municipal/legado."""
import sys
from src.etl_municipal.legado import primario as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
