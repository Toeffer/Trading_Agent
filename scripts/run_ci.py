"""Cross-platform discovery runner; no broker, production home, or credentials."""
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parent.parent
temporary = root / ".test-tmp"
temporary.mkdir(exist_ok=True)
(temporary / "home").mkdir(exist_ok=True)
(temporary / "temp").mkdir(exist_ok=True)
results = root / ".test-results"
results.mkdir(exist_ok=True)
env = dict(os.environ)
env.update(PYTHONUTF8="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", IBKR_TEST_ISOLATION="1",
           IBKR_TEST_ROOT=str(temporary), IBKR_ALLOW_ORDERS="false", H1_APPROVAL_TOKEN_HASH="",
           IBKR_STATE_DIR=str(temporary / "home" / "state"),
           TEMP=str(temporary / "temp"), TMP=str(temporary / "temp"), TMPDIR=str(temporary / "temp"),
           PYTHONPATH=str(root / "tests" / "isolation") + os.pathsep + str(root))
args = sys.argv[1:] or ["-q", "tests"]
command = [sys.executable, "-m", "pytest", *args, "-m", "not integration and not live and not host and not acceptance",
           "--basetemp", str(temporary / ("pytest-" + str(os.getpid()))),
           "--junitxml", str(results / "portable.xml")]
raise SystemExit(subprocess.call(command, cwd=root, env=env))
