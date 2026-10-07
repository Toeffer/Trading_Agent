"""An OS-held deployment lock, released by the kernel after a crash."""

import sys
from pathlib import Path
from typing import BinaryIO


class ServiceLock:
    def __init__(self, path: Path):
        self.path = path
        self.file: BinaryIO | None = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open("a+b")
        try:
            if sys.platform == "win32":
                import msvcrt

                if not self.path.stat().st_size:
                    stream.write(b"0")
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            stream.close()
            raise RuntimeError("EXECUTION_SERVICE_ALREADY_RUNNING") from None
        self.file = stream

    def close(self) -> None:
        if self.file:
            self.file.close()
            self.file = None
