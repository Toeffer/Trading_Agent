"""The fake IB Gateway used by bridge tests -- now the simulator in sim/ib_gateway.py.

Kept as a module so existing tests keep importing `fake_ib_gateway`; the one
implementation lives in sim/ (see its docstring for scripted symbols and
order modes). Not a test module (no test_ prefix).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sim.ib_gateway import (  # noqa: E402,F401
    ACCOUNT, ASK_PRICE, BARS, BID_PRICE, CON_IDS, LAST_ONLY_SYMBOLS, LAST_PRICE,
    NET_LIQUIDATION_EUR, ORDER_MODES, USD_EXCHANGE_RATE, SimGateway, con_id,
)

FakeIBGateway = SimGateway
