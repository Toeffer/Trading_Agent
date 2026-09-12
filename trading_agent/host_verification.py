"""Read-only Linux ownership and gateway access evidence."""

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from typing import Any


def run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
        check=False,
    )


def verify(
    release: Path, state: Path, config: Path, port: int, advisory_user: str
) -> dict[str, Any]:
    if sys.platform != "linux":
        raise ValueError("Host verification requires the actual Linux deployment")
    if os.geteuid() != 0:
        raise ValueError(
            "Run read-only host verification as administrator to test service identities"
        )
    import pwd

    users = ("ibkr-exec", "ibkr-ui", "ibkr-gateway", advisory_user)
    ids = {user: pwd.getpwnam(user).pw_uid for user in users}
    checks: dict[str, bool] = {
        "separate_service_identities": len(set(ids.values())) == 4
        and 0 not in ids.values()
    }
    bad_paths = []
    for path in [release, *release.rglob("*"), config, *config.rglob("*")]:
        info = path.stat()
        if info.st_uid != 0 or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            bad_paths.append(str(path))
    checks["administrator_owned_code_and_config"] = not bad_paths
    info = state.stat()
    checks["private_execution_state"] = (
        info.st_uid == ids["ibkr-exec"] and stat.S_IMODE(info.st_mode) == 0o700
    )
    token = config / "h1_token"
    info = token.stat()  # Never read the secret.
    checks["private_human_credential"] = (
        info.st_uid == 0 and stat.S_IMODE(info.st_mode) == 0o600
    )
    socket_probe = "import socket,sys; s=socket.socket(); s.settimeout(2); sys.exit(s.connect_ex(('127.0.0.1',int(sys.argv[1]))) != 0)"
    gateway_access = {}
    for user in users:
        probe = run(
            [
                "runuser",
                "-u",
                user,
                "--",
                sys.executable,
                "-I",
                "-c",
                socket_probe,
                str(port),
            ]
        )
        gateway_access[user] = probe.returncode == 0
    checks["execution_gateway_access"] = gateway_access["ibkr-exec"]
    checks["advisory_gateway_denied"] = not gateway_access[advisory_user]
    checks["ui_gateway_denied"] = not gateway_access["ibkr-ui"]
    # Use actual OS access checks under each unprivileged UID, including ACLs.
    access_probe = (
        "import os,sys; sys.exit(any(os.access(p,os.W_OK) for p in sys.argv[1:]))"
    )
    for user in users:
        denied = run(
            [
                "runuser",
                "-u",
                user,
                "--",
                sys.executable,
                "-I",
                "-c",
                access_probe,
                str(release),
                str(config),
            ]
        )
        checks[user + "_cannot_modify_installation"] = denied.returncode == 0
    units = {}
    for unit, user in (
        ("ibkr-bridge.service", "ibkr-exec"),
        ("ibkr-approval-ui.service", "ibkr-ui"),
        ("ibkr-gateway.service", "ibkr-gateway"),
    ):
        result = run(
            [
                "systemctl",
                "show",
                unit,
                "--property=User,Group,FragmentPath,ActiveState,NoNewPrivileges,ProtectSystem",
            ]
        )
        units[unit] = dict(
            line.split("=", 1) for line in result.stdout.splitlines() if "=" in line
        )
        checks[unit + "_identity"] = (
            result.returncode == 0 and units[unit].get("User") == user
        )
    commit = run(["git", "-C", str(release), "rev-parse", "HEAD"])
    clean = run(["git", "-C", str(release), "status", "--porcelain"])
    checks["clean_release"] = (
        commit.returncode == 0 and clean.returncode == 0 and not clean.stdout.strip()
    )
    firewall = run(["nft", "-j", "list", "table", "inet", "ibkr_boundary"])
    checks["gateway_firewall_installed"] = firewall.returncode == 0
    return {
        "schema_version": 1,
        "passed": all(checks.values()),
        "checks": checks,
        "release": commit.stdout.strip(),
        "gateway_access": gateway_access,
        "units": units,
        "incorrectly_owned_paths": bad_paths,
        "firewall": json.loads(firewall.stdout) if firewall.returncode == 0 else None,
        "paper_acceptance_verified": False,
    }
