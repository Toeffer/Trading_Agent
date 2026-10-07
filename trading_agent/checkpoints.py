"""Historical guard switches mapped to isolated current behavioral checks."""

from pathlib import Path
import subprocess
import sys

CHECKS = {
    "_run_self_test": ["tests/test_execution_regressions.py"],
    "_run_step2_tests": [
        "tests/test_execution_durability.py",
        "tests/test_execution_migration.py",
    ],
    "_run_step3_tests": ["tests/test_broker_contract.py"],
    "_run_step4_tests": ["tests/test_p5_bracket_stops.py"],
    "_run_step5_tests": ["tests/test_execution_application.py"],
    "_run_step6_tests": ["tests/test_execution_durability.py"],
    "_run_step7a_tests": ["tests/test_execution_http.py"],
    "_run_step2c_tests": [
        "tests/test_approval_lookup_single_source.py",
        "tests/test_invariant12_restart_invalidation.py",
    ],
}


def run(name: str) -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "scripts/run_ci.py"), "-q", *CHECKS[name]], cwd=root
    )
    if result.returncode:
        raise SystemExit(result.returncode)


def main() -> int:
    argument = sys.argv[1] if len(sys.argv) == 2 else ""
    if argument == "--test":
        run("_run_step2c_tests")
        run("_run_step2_tests")
        run("_run_step3_tests")
        run("_run_step5_tests")
        return 0
    name = "_run_" + argument.removeprefix("--test-") + "_tests"
    if name not in CHECKS:
        print(
            "Usage: guard.py --test | --test-step2 | --test-step3 | --test-step4 | --test-step5 | --test-step6 | --test-step7a | --test-step2c"
        )
        return 2
    run(name)
    return 0
