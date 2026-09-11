"""Portable test subprocess isolation, enabled only by the test runner."""
import os
from pathlib import Path
import socket
import sys

if os.environ.get("IBKR_TEST_ISOLATION") == "1":
    root = Path(os.environ["IBKR_TEST_ROOT"]).resolve()
    def isolated_home(cls):
        fixture = os.environ.get("HOME")
        if fixture:
            candidate = Path(fixture).resolve()
            if candidate.is_relative_to(root):
                return candidate
        return root / "home"
    Path.home = classmethod(isolated_home)
    original_connect = socket.socket.connect
    pair_code = socket._fallback_socketpair.__code__
    def blocked_connect(sock, address):
        caller = sys._getframe(1)
        if caller.f_code is pair_code:
            listener = caller.f_locals.get("lsock")
            if listener is not None and tuple(address) == listener.getsockname()[:2]:
                return original_connect(sock, address)
        raise OSError("Network disabled in portable tests")
    socket.socket.connect = blocked_connect
    socket.socket.connect_ex = blocked_connect
