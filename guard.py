"""Compatibility imports and historical test switches for the guard."""
import sys
from trading_agent import legacy_guard as implementation

if __name__ == "__main__":
    from trading_agent.checkpoints import main
    raise SystemExit(main())
else:
    sys.modules[__name__] = implementation
