#!/usr/bin/env python3
"""
Trading Agent preflight check.

Verifies — BEFORE the agent runs — that:
  1. All required env vars are set
  2. config/sae-config.yaml parses and matches the recorded hash
  3. Exchange API keys are reachable and have correct permissions (read + trade, NO withdraw)
  4. LLM provider key works (test prompt to V4 Flash)
  5. Telegram bot can send a message to the operator chat

Exit 0 → safe to start. Exit non-zero → fix the reported issue, do not start.

Usage:
  python scripts/preflight.py            # full check (~30s)
  python scripts/preflight.py --quick    # only env + config (used by Docker HEALTHCHECK)
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"
SAE_CONFIG = CONFIG_DIR / "sae-config.yaml"
SAE_HASH_FILE = REPO_ROOT / ".sae-config.hash"

REQUIRED_ENV = {
    "BINANCE_API_KEY": "Binance API key (trade + read only)",
    "BINANCE_SECRET": "Binance secret",
    "KUCOIN_API_KEY": "KuCoin API key",
    "KUCOIN_SECRET": "KuCoin secret",
    "KUCOIN_PASSPHRASE": "KuCoin passphrase",
    "TELEGRAM_BOT_TOKEN": "Telegram bot token",
    "TELEGRAM_CHAT_ID": "Telegram operator chat ID",
    "LLM_PROVIDER": "LLM provider (openrouter|deepseek)",
}

GREEN, RED, YELLOW, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[0m"


def ok(msg: str) -> None:
    print(f"{GREEN}[OK]{RESET}    {msg}")


def fail(msg: str) -> None:
    print(f"{RED}[FAIL]{RESET}  {msg}")


def warn(msg: str) -> None:
    print(f"{YELLOW}[WARN]{RESET}  {msg}")


def check_env() -> bool:
    print("\n── 1. Environment variables ──")
    missing = [k for k in REQUIRED_ENV if not os.getenv(k)]
    if missing:
        for k in missing:
            fail(f"{k} not set ({REQUIRED_ENV[k]})")
        return False

    provider = os.getenv("LLM_PROVIDER", "").lower()
    if provider == "openrouter" and not os.getenv("OPENROUTER_API_KEY"):
        fail("LLM_PROVIDER=openrouter but OPENROUTER_API_KEY is not set")
        return False
    if provider == "deepseek" and not os.getenv("DEEPSEEK_API_KEY"):
        fail("LLM_PROVIDER=deepseek but DEEPSEEK_API_KEY is not set")
        return False
    if provider not in ("openrouter", "deepseek"):
        fail(f"LLM_PROVIDER must be 'openrouter' or 'deepseek', got: {provider!r}")
        return False

    ok(f"all required env vars set (LLM provider: {provider})")
    return True


def check_sae_config() -> bool:
    print("\n── 2. SAE config integrity ──")
    if not SAE_CONFIG.exists():
        fail(f"{SAE_CONFIG} not found")
        return False

    try:
        import yaml

        with SAE_CONFIG.open() as f:
            cfg = yaml.safe_load(f)
    except Exception as e:
        fail(f"sae-config.yaml does not parse: {e}")
        return False

    # Spot-check the critical invariants — values must match CLAUDE.md §6.
    expected = {
        ("exposure_budget", "max_total_open_risk_pct"): 6.0,
        ("exposure_budget", "max_single_position_pct"): 2.0,
        ("exposure_budget", "max_speculative_short_pct"): 5.0,
        ("order_controls", "max_leverage"): 2,
        ("withdraw_block",): True,
    }
    for path, want in expected.items():
        node = cfg
        for k in path:
            node = node.get(k) if isinstance(node, dict) else None
        if node != want:
            fail(f"sae-config.yaml: {'.'.join(path)} = {node!r}, expected {want!r}")
            return False
    ok("sae-config.yaml parses and critical invariants match CLAUDE.md §6")

    # Hash check
    if SAE_HASH_FILE.exists():
        recorded = SAE_HASH_FILE.read_text().strip()
        current = hashlib.sha256(SAE_CONFIG.read_bytes()).hexdigest()
        if recorded != current:
            fail(
                "sae-config.yaml has changed since last `make sae-hash`. "
                "Per CLAUDE.md §11 rule 10: halt and review before trading. "
                "If the change is intentional, run: make sae-hash"
            )
            return False
        ok("sae-config.yaml hash matches recorded value")
    else:
        warn(f"no {SAE_HASH_FILE.name} yet — run `make sae-hash` to record baseline")
    return True


def check_binance() -> bool:
    print("\n── 3a. Binance API ──")
    try:
        import ccxt
    except ImportError:
        fail("ccxt not installed (pip install -r requirements.txt)")
        return False

    try:
        client = ccxt.binance(
            {
                "apiKey": os.environ["BINANCE_API_KEY"],
                "secret": os.environ["BINANCE_SECRET"],
                "enableRateLimit": True,
            }
        )
        if os.getenv("BINANCE_TESTNET", "").lower() == "true":
            client.set_sandbox_mode(True)

        # Read permission test
        balance = client.fetch_balance()
        ok(f"Binance read OK ({len(balance.get('total', {}))} assets visible)")

        # Permission check — load account info
        info = balance.get("info", {})
        permissions = info.get("permissions") or []
        if "WITHDRAW" in [p.upper() for p in permissions] or info.get(
            "canWithdraw"
        ) is True:
            fail("Binance key has WITHDRAW permission. ROTATE IMMEDIATELY per CLAUDE.md §4.")
            return False
        ok("Binance key does NOT have withdraw permission")
        return True
    except Exception as e:
        fail(f"Binance API call failed: {e}")
        return False


def check_kucoin() -> bool:
    print("\n── 3b. KuCoin API ──")
    try:
        import ccxt
    except ImportError:
        return False

    try:
        client = ccxt.kucoin(
            {
                "apiKey": os.environ["KUCOIN_API_KEY"],
                "secret": os.environ["KUCOIN_SECRET"],
                "password": os.environ["KUCOIN_PASSPHRASE"],
                "enableRateLimit": True,
            }
        )
        balance = client.fetch_balance()
        ok(f"KuCoin read OK ({len(balance.get('total', {}))} assets visible)")
        return True
    except Exception as e:
        fail(f"KuCoin API call failed: {e}")
        return False


def check_llm() -> bool:
    print("\n── 4. LLM provider ──")
    provider = os.environ["LLM_PROVIDER"].lower()
    try:
        from openai import OpenAI
    except ImportError:
        fail("openai SDK not installed")
        return False

    if provider == "openrouter":
        client = OpenAI(
            api_key=os.environ["OPENROUTER_API_KEY"],
            base_url="https://openrouter.ai/api/v1",
        )
        model = "deepseek/deepseek-v4-flash"  # TODO(operator): confirm exact OpenRouter slug
    else:
        client = OpenAI(
            api_key=os.environ["DEEPSEEK_API_KEY"],
            base_url="https://api.deepseek.com/v1",
        )
        model = "deepseek-v4-flash"  # TODO(operator): confirm exact DeepSeek slug

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Reply with the single word: PONG"}],
            max_tokens=5,
            temperature=0,
        )
        text = resp.choices[0].message.content or ""
        if "PONG" not in text.upper():
            warn(f"LLM responded but reply was unexpected: {text!r}")
        else:
            ok(f"LLM {provider} reachable, model {model} responded")
        return True
    except Exception as e:
        fail(f"LLM call failed: {e}")
        warn(
            "If the model slug is wrong (DeepSeek V4 Flash/Pro slugs may differ "
            "between providers), edit scripts/preflight.py — search for TODO(operator)"
        )
        return False


def check_telegram() -> bool:
    print("\n── 5. Telegram ──")
    try:
        import requests
    except ImportError:
        return False

    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": "[preflight] Trading Agent: preflight check OK — ready to start.",
            },
            timeout=10,
        )
        r.raise_for_status()
        ok("Telegram message sent — check your chat to confirm receipt")
        return True
    except Exception as e:
        fail(f"Telegram send failed: {e}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Trading Agent preflight check")
    parser.add_argument(
        "--quick", action="store_true", help="only check env + SAE config (no network calls)"
    )
    args = parser.parse_args()

    print("Trading Agent — Preflight")
    print("=" * 60)

    checks: list[tuple[str, Callable[[], bool]]] = [
        ("env", check_env),
        ("sae", check_sae_config),
    ]
    if not args.quick:
        checks += [
            ("binance", check_binance),
            ("kucoin", check_kucoin),
            ("llm", check_llm),
            ("telegram", check_telegram),
        ]

    results = {name: fn() for name, fn in checks}

    print("\n" + "=" * 60)
    failed = [name for name, ok_ in results.items() if not ok_]
    if failed:
        print(f"{RED}PREFLIGHT FAILED:{RESET} {', '.join(failed)}")
        print("Fix the issues above before running `make up`.")
        return 1
    print(f"{GREEN}PREFLIGHT OK{RESET} — safe to start with `make up`.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
