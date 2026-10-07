"""Compatibility entry point for historical read-only operator commands."""
import sys
from trading_agent.cli import operator_legacy as implementation

if __name__ == "__main__":
    implementation.main()
else:
    sys.modules[__name__] = implementation
