"""IB Gateway simulator: speaks the TWS API so the unmodified bridge runs against it.

TEST EVIDENCE ONLY. It reports account DUSIM0001; per CLAUDE.md §8
(Simulation) nothing it produces is IBKR evidence. It never connects anywhere:
it is a local server the bridge connects to instead of IB Gateway.

Covers what the bridge uses (server version 176, as ib_insync 0.9.86 sees it):
connect handshake and initial sync, contract details, historical bars, market
data ticks, account values, positions, and orders -- placeOrder, cancelOrder,
order status, executions, commissions and position updates.

Scripted symbols:
  HANG  -- reqContractDetails is never answered (a stalled Gateway)
  NOPE  -- contract not found
  MSFT  -- market data has a last price only, no bid/ask
  other -- a US stock with 20 daily bars and bid/ask/last ticks

Order modes (what the "broker" does with transmitted orders):
  fill     -- MKT: Submitted, then filled in full at the ask (BUY) / bid (SELL)
  partial  -- MKT: Submitted, then half the quantity (at least 1) fills
  no_ack   -- orders are swallowed: no status, no fill, ever
  reject   -- error 201 and status Cancelled
STP orders (a bracket's protective stop) rest as PreSubmitted, then Submitted.

Modelling assumption, not verified against IBKR: an order placed with
transmit=False gets no status until a child with transmit=True transmits the
bracket. That is how the TWS API documents bracket transmission.

Run standalone:  python -m sim.ib_gateway --port 4999 [--mode fill] [--position AAPL=10@180]
"""

import argparse
import itertools
import math
import socket
import struct
import sys
import threading
import time
import zlib

ACCOUNT = "DUSIM0001"
CON_IDS = {"AAPL": 265598, "MSFT": 272093, "META": 107113386, "NVDA": 4815747, "AMD": 4391}
LAST_PRICE = 190.5
BID_PRICE = 190.4
ASK_PRICE = 190.6
LAST_ONLY_SYMBOLS = {"MSFT"}
USD_EXCHANGE_RATE = "0.8700"   # value of 1 USD in EUR (account base currency)
NET_LIQUIDATION_EUR = "1000000.00"
# 20 daily bars (enough for ATR(14)): date, open, high, low, close.
BARS = [
    (f"202609{day:02d}", 180.0 + i, 182.0 + i, 179.0 + i, 181.0 + i)
    for i, day in enumerate(range(1, 21))
]
ORDER_MODES = ("fill", "partial", "no_ack", "reject")


def con_id(symbol: str) -> int:
    return CON_IDS.get(symbol) or 900000 + zlib.crc32(symbol.encode()) % 100000


def _num(x) -> str:
    return str(int(x)) if float(x).is_integer() else str(x)


def _frame(*fields) -> bytes:
    body = "".join(f"{f}\0" for f in fields).encode()
    return struct.pack(">I", len(body)) + body


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("client closed")
        buf += chunk
    return buf


def _contract_fields(symbol: str) -> tuple:
    # conId, symbol, secType, lastTrade, strike, right, multiplier, exchange,
    # currency, localSymbol, tradingClass -- as execDetails/position decode them.
    return (con_id(symbol), symbol, "STK", "", "0", "", "", "SMART", "USD", symbol, "NMS")


def _contract_details(req_id: str, symbol: str) -> bytes:
    # Field order of ib_insync Decoder.contractDetails for serverVersion >= 164.
    return _frame(
        "10", req_id, symbol, "STK", "", "0", "", "SMART", "USD", symbol,
        "NMS", "NMS", con_id(symbol), "0.01",
        "", "LMT,MKT,STP", "SMART,NASDAQ", "1", "0", f"{symbol} INC", "NASDAQ", "",
        "Technology", "Computers", "Computers", "US/Eastern", "", "", "", "0",
        "0",                                 # numSecIds
        "1", "", "", "26", "", "COMMON",
        "1", "1", "100",
    )


def _account_values() -> bytes:
    rows = [
        ("AccountCode", ACCOUNT, ""),
        ("NetLiquidation", NET_LIQUIDATION_EUR, "EUR"),
        ("TotalCashValue", NET_LIQUIDATION_EUR, "EUR"),
        ("AvailableFunds", NET_LIQUIDATION_EUR, "EUR"),
        ("BuyingPower", "6666666.67", "EUR"),
        ("Currency", "EUR", "EUR"),
        ("ExchangeRate", USD_EXCHANGE_RATE, "USD"),
        ("ExchangeRate", "1.00", "EUR"),
        ("ExchangeRate", "1.00", "BASE"),   # sent last: the row a tag-keyed lookup kept
    ]
    return b"".join(_frame("6", "2", tag, value, cur, ACCOUNT) for tag, value, cur in rows)


def _parse_place_order(f: list) -> dict:
    # ib_insync Client.placeOrder field order: 3, orderId, contract (12 fields),
    # secIdType, secId, action, totalQuantity, orderType, lmtPrice, auxPrice,
    # tif, ocaGroup, account, openClose, origin, orderRef, transmit, parentId, ...
    return {
        "order_id": int(f[1]),
        "symbol": f[3],
        "action": f[16],
        "quantity": float(f[17]),
        "order_type": f[18],
        "aux_price": float(f[20]) if f[20] else None,
        "transmit": f[27] == "1",
        "parent_id": int(f[28] or 0),
        "status": None,
        "filled": 0.0,
        "perm_id": None,
    }


class SimGateway:
    """Serves the simulator on 127.0.0.1:<port> (0 = any free port) from daemon threads."""

    def __init__(self, port: int = 0, order_mode: str = "fill",
                 positions: dict | None = None) -> None:
        if order_mode not in ORDER_MODES:
            raise ValueError(f"order_mode must be one of {ORDER_MODES}")
        self.order_mode = order_mode
        self.positions = {s: (float(q), float(c)) for s, (q, c) in (positions or {}).items()}
        self.orders: dict[int, dict] = {}
        self.executions: list[dict] = []
        self.requests: list[tuple] = []     # (msg_id, symbol-or-None)
        self._lock = threading.Lock()
        self._perm_ids = itertools.count(900001)
        self._exec_ids = itertools.count(1)
        self._srv = socket.socket()
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", port))
        self._srv.listen()
        self.port = self._srv.getsockname()[1]
        threading.Thread(target=self._accept, daemon=True).start()

    # -- connection handling ------------------------------------------------

    def _accept(self) -> None:
        while True:
            try:
                conn, _ = self._srv.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn: socket.socket) -> None:
        state = {"client_id": 0, "held": {}}
        try:
            assert _recv_exact(conn, 4) == b"API\0"
            _recv_exact(conn, struct.unpack(">I", _recv_exact(conn, 4))[0])
            conn.sendall(_frame("176", "20260928 12:00:00 UTC"))
            while True:
                n = struct.unpack(">I", _recv_exact(conn, 4))[0]
                f = _recv_exact(conn, n).decode().split("\0")[:-1]
                with self._lock:
                    self._handle(conn, state, int(f[0]), f)
        except (ConnectionError, OSError, AssertionError):
            return

    def _handle(self, conn: socket.socket, state: dict, msg_id: int, f: list) -> None:
        if msg_id == 71:                                   # startApi
            state["client_id"] = int(f[2])
            conn.sendall(_frame("9", "1", "1") + _frame("15", "1", ACCOUNT))
        elif msg_id == 61:                                 # reqPositions
            conn.sendall(b"".join(self._position_frame(s) for s in self.positions)
                         + _frame("62", "1"))
        elif msg_id == 6:                                  # reqAccountUpdates
            conn.sendall(_account_values()
                         + b"".join(self._portfolio_frame(s) for s in self.positions)
                         + _frame("54", "1", ACCOUNT))
        elif msg_id == 76:                                 # reqAccountUpdatesMulti
            conn.sendall(_frame("74", "1", f[2]))
        elif msg_id == 7:                                  # reqExecutions
            conn.sendall(_frame("55", "1", f[2]))
        elif msg_id in (5, 16):                            # req(All)OpenOrders
            conn.sendall(_frame("53", "1"))
        elif msg_id == 99:                                 # reqCompletedOrders
            conn.sendall(_frame("102"))
        elif msg_id == 9:                                  # reqContractDetails
            req_id, symbol = f[2], f[4]
            if not symbol:
                symbol = next((s for s, cid in CON_IDS.items() if str(cid) == f[3]), "NOPE")
            self.requests.append((msg_id, symbol))
            if symbol == "HANG":
                return
            if symbol != "NOPE":
                conn.sendall(_contract_details(req_id, symbol))
            conn.sendall(_frame("52", "1", req_id))
        elif msg_id == 20:                                 # reqHistoricalData
            req_id = f[1]
            self.requests.append((msg_id, f[3]))
            bars = [x for d, o, h, lo, c in BARS for x in (d, o, h, lo, c, 1000, c, 10)]
            conn.sendall(_frame("17", req_id, "", "", len(BARS), *bars))
        elif msg_id == 1:                                  # reqMktData
            req_id, symbol = f[2], f[4]
            self.requests.append((msg_id, symbol))
            ticks = [("4", LAST_PRICE)]                    # tick type 4 = last
            if symbol not in LAST_ONLY_SYMBOLS:
                ticks += [("1", BID_PRICE), ("2", ASK_PRICE)]
            conn.sendall(b"".join(_frame("1", "6", req_id, t, px, "100", "0") for t, px in ticks))
        elif msg_id == 97:                                 # reqTickByTickData
            req_id, symbol = f[1], f[3]
            self.requests.append((msg_id, symbol))
            if symbol not in LAST_ONLY_SYMBOLS:
                # A newly observed tick, with the protocol's whole-second resolution.
                conn.sendall(_frame("99", req_id, "3", math.ceil(time.time()),
                                    BID_PRICE, ASK_PRICE, "100", "100", "0"))
        elif msg_id == 3:                                  # placeOrder
            order = _parse_place_order(f)
            self.requests.append((msg_id, order["symbol"]))
            self._place(conn, state, order)
        elif msg_id == 4:                                  # cancelOrder
            self._cancel(conn, state, int(f[2]))
        # Everything else (reqMarketDataType, cancelMktData, ...) needs no reply.

    # -- orders ---------------------------------------------------------------

    def _place(self, conn: socket.socket, state: dict, order: dict) -> None:
        if self.order_mode == "no_ack":
            return
        if not order["transmit"]:
            state["held"][order["order_id"]] = order
            return
        batch = []
        parent = state["held"].pop(order["parent_id"], None) if order["parent_id"] else None
        if parent:
            batch.append(parent)
        batch.append(order)
        for o in batch:
            self._transmit(conn, state, o)

    def _transmit(self, conn: socket.socket, state: dict, o: dict) -> None:
        o["perm_id"] = next(self._perm_ids)
        self.orders[o["order_id"]] = o
        if self.order_mode == "reject":
            conn.sendall(_frame("4", "2", o["order_id"], "201",
                                "Order rejected - reason: SIMULATED rejection", ""))
            conn.sendall(self._status_frame(state, o, "Cancelled"))
            return
        if o["order_type"] == "STP":
            conn.sendall(self._status_frame(state, o, "PreSubmitted")
                         + self._status_frame(state, o, "Submitted"))
            return
        conn.sendall(self._status_frame(state, o, "Submitted"))
        qty = o["quantity"] if self.order_mode == "fill" else max(1.0, math.floor(o["quantity"] / 2))
        price = ASK_PRICE if o["action"] == "BUY" else BID_PRICE
        conn.sendall(self._fill(state, o, qty, price))
        status = "Filled" if o["filled"] >= o["quantity"] else "Submitted"
        conn.sendall(self._status_frame(state, o, status, price))

    def _cancel(self, conn: socket.socket, state: dict, order_id: int) -> None:
        o = state["held"].pop(order_id, None) or self.orders.get(order_id)
        if o and o.get("status") not in ("Filled", "Cancelled"):
            conn.sendall(self._status_frame(state, o, "Cancelled"))

    def _status_frame(self, state: dict, o: dict, status: str, last_price: float = 0.0) -> bytes:
        o["status"] = status
        remaining = 0.0 if status == "Cancelled" else o["quantity"] - o["filled"]
        avg = last_price if o["filled"] else 0.0
        return _frame("3", o["order_id"], status, _num(o["filled"]), _num(remaining), avg,
                      o["perm_id"] or 0, o["parent_id"], last_price, state["client_id"], "", 0)

    def _fill(self, state: dict, o: dict, qty: float, price: float) -> bytes:
        o["filled"] += qty
        exec_id = f"sim.{next(self._exec_ids):06d}"
        side = "BOT" if o["action"] == "BUY" else "SLD"
        symbol = o["symbol"]
        pos, avg = self.positions.get(symbol, (0.0, 0.0))
        signed = qty if o["action"] == "BUY" else -qty
        new_pos = pos + signed
        new_avg = ((pos * avg + qty * price) / new_pos) if o["action"] == "BUY" and new_pos else avg
        self.positions[symbol] = (new_pos, new_avg)
        self.executions.append({"exec_id": exec_id, "order_id": o["order_id"], "symbol": symbol,
                                "side": side, "shares": qty, "price": price})
        return (
            _frame("11", "-1", o["order_id"], *_contract_fields(symbol), exec_id,
                   int(time.time()), ACCOUNT, "SMART", side, _num(qty), price, o["perm_id"],
                   state["client_id"], "0", _num(o["filled"]), price, "", "", "", "", "0")
            + _frame("59", "1", exec_id, "1.0", "USD", "", "", "")
            + self._position_frame(symbol)
            + self._portfolio_frame(symbol)
        )

    def _position_frame(self, symbol: str) -> bytes:
        qty, avg = self.positions[symbol]
        return _frame("61", "3", ACCOUNT, *_contract_fields(symbol), _num(qty), avg)

    def _portfolio_frame(self, symbol: str) -> bytes:
        qty, avg = self.positions[symbol]
        return _frame("7", "8", *_contract_fields(symbol), _num(qty),
                      LAST_PRICE, qty * LAST_PRICE, avg, (LAST_PRICE - avg) * qty, 0, ACCOUNT)

    def close(self) -> None:
        self._srv.close()


def _parse_position(text: str) -> tuple[str, tuple[float, float]]:
    symbol, rest = text.split("=", 1)
    qty, _, cost = rest.partition("@")
    return symbol.upper(), (float(qty), float(cost or ASK_PRICE))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="IB Gateway simulator (SIMULATION, account DUSIM0001)")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--mode", choices=ORDER_MODES, default="fill")
    ap.add_argument("--position", action="append", default=[], metavar="SYM=QTY[@COST]")
    args = ap.parse_args(argv)
    gw = SimGateway(args.port, args.mode, dict(_parse_position(p) for p in args.position))
    print(f"SIMULATION IB Gateway on 127.0.0.1:{gw.port} account={ACCOUNT} mode={args.mode}",
          flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        gw.close()
        sys.exit(0)


if __name__ == "__main__":
    main()
