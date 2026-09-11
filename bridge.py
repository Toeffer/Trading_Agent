"""Compatibility entry point: uvicorn bridge:app."""
import sys
from trading_agent import http_compat as implementation

sys.modules[__name__] = implementation
