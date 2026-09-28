"""Minimal in-process fake IB Gateway for bridge tests (no IBKR, no network).

Speaks just enough of the TWS API (server version 176) for ib_insync:
the connect handshake and initial sync, contract details, historical bars,
a single last-price tick for market data, and account values. Every reply
is sent immediately, so any delay a test observes is the client's own.

Scripted symbols:
  HANG  -- reqContractDetails is never answered (a stalled Gateway)
  NOPE  -- contract not found (empty contractDetailsEnd)
  MSFT  -- like other, but market data has a last price only, no bid/ask
  other -- one US stock contract, 20 daily bars, bid/ask/last ticks

Account values are sent with the ExchangeRate BASE row *last*, the order
that made a tag-keyed lookup pick 1.00 instead of the USD rate.

Not a test module (no test_ prefix); imported by tests that exercise the
real bridge.py against it.
"""

import socket
import struct
import threading

ACCOUNT = "DU000001"
CON_ID = 265598
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


def _contract_details(req_id: str, symbol: str) -> bytes:
    # Field order of ib_insync Decoder.contractDetails for serverVersion >= 164.
    return _frame(
        "10", req_id, symbol, "STK", "", "0", "", "SMART", "USD", symbol,
        "NMS", "NMS", CON_ID, "0.01",
        "", "LMT,MKT", "SMART,NASDAQ", "1", "0", f"{symbol} INC", "NASDAQ", "",
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
        ("ExchangeRate", "1.00", "BASE"),
    ]
    return b"".join(_frame("6", "2", tag, value, cur, ACCOUNT) for tag, value, cur in rows)


class FakeIBGateway:
    """Serves the fake Gateway on 127.0.0.1:<port> from a daemon thread."""

    def __init__(self) -> None:
        self._srv = socket.socket()
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen()
        self.port = self._srv.getsockname()[1]
        self.requests: list[tuple] = []   # (msg_id, symbol-or-None)
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self) -> None:
        while True:
            try:
                conn, _ = self._srv.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn: socket.socket) -> None:
        try:
            assert _recv_exact(conn, 4) == b"API\0"
            _recv_exact(conn, struct.unpack(">I", _recv_exact(conn, 4))[0])
            conn.sendall(_frame("176", "20260928 12:00:00 UTC"))
            while True:
                n = struct.unpack(">I", _recv_exact(conn, 4))[0]
                f = _recv_exact(conn, n).decode().split("\0")[:-1]
                self._handle(conn, int(f[0]), f)
        except (ConnectionError, OSError):
            return

    def _handle(self, conn: socket.socket, msg_id: int, f: list) -> None:
        if msg_id == 71:                                   # startApi
            conn.sendall(_frame("9", "1", "1") + _frame("15", "1", ACCOUNT))
        elif msg_id == 61:                                 # reqPositions
            conn.sendall(_frame("62", "1"))
        elif msg_id == 6:                                  # reqAccountUpdates
            conn.sendall(_account_values() + _frame("54", "1", ACCOUNT))
        elif msg_id == 76:                                 # reqAccountUpdatesMulti
            conn.sendall(_frame("74", "1", f[2]))
        elif msg_id == 7:                                  # reqExecutions
            conn.sendall(_frame("55", "1", f[2]))
        elif msg_id == 9:                                  # reqContractDetails
            req_id, symbol = f[2], f[4]
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
        # Everything else (reqMarketDataType, cancelMktData, ...) needs no reply.

    def close(self) -> None:
        self._srv.close()
