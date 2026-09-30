"""Backtest strategy variants on historical daily bars — BACKTEST, hypothetical.

Research input for Chris and Hermes (`ibkr-operator hermes-research`). Results
are hypothetical and are never paper-run evidence, never a readiness claim and
never an input to the trade path. Every result carries LABEL.

A variant is a small, bounded set of parameters (VARIANT_FIELDS). It can be
tighter than the live guard, never looser:

  stop     guard.calc_stop() on the same 30-day bar window the guard fetches;
           atr_multiplier <= 2.0 can only move the ATR leg closer to entry
  size     guard.compute_final_max_shares() with the variant's caps, each
           capped at the paper-trading-rules ceiling
  budget   strategy_v1_1_core regime + inverse-vol scalar, never above the
           ceiling's max_total_exposure
  gates    allowlist only, long only, Gate I sector cap, trades/day (exits
           that go through preflight count, broker-side stop fills do not),
           weekly loss halt

Execution model: signals at the close of day t, orders at the open of t+1
with slippage_bps against you; a stop fills at the stop, or at the open when
the open gaps through it. Daily bars only, so the intraday daily loss halt and
the 9:30-9:45 / 15:45-16:00 entry blackouts are not modelled. No partial fills,
no market impact, prices in USD (the guard's percentages are the same in EUR).

Discipline (Decision 11.6, proposal §15): at most MAX_VARIANTS variants per
study, every one reported; Hermes sees the train period only; the holdout is
evaluated once, for one chosen variant, and the ledger refuses a second look.

    python -m sim.backtest --data DIR --rules RULES.yaml --variants V.json --out DIR
    python -m sim.backtest --study DIR/study.json --data DIR --holdout VARIANT_NAME
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import re
import statistics
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import guard  # noqa: E402  — the live stop and sizing formulas, not copies
import strategy_v1_1_core as core  # noqa: E402

LABEL = "BACKTEST — hypothetical; not paper-run evidence, not a readiness claim"
MAX_VARIANTS = 5
BENCHMARK = "SPY"
STOP_WINDOW_DAYS = 30        # guard.fetch_bars() default duration "30 D"
REGIME_BARS = 252            # 200d SMA and 12-month momentum
VOL_BARS = 21                # 20 daily returns

# name: (type, minimum, maximum or the rules key that caps it, default)
VARIANT_FIELDS = {
    "trend_sma_days": (int, 10, 250, 50),
    "trend_exit": (bool, None, None, True),
    "rs_filter": (bool, None, None, True),
    "rs_lookback_days": (int, 20, 252, 60),
    "rs_top_fraction": (float, 0.1, 1.0, 0.5),
    "regime_filter": (bool, None, None, True),
    "vol_scaling": (bool, None, None, True),
    "atr_multiplier": (float, 0.5, float(guard.ATR_MULTIPLIER), float(guard.ATR_MULTIPLIER)),
    "max_hold_days": (int, 0, 250, 0),
    "risk_pct": (float, 0.05, "max_risk_per_trade", 0.25),
    "max_position_pct": (float, 0.5, "max_position_notional", 5.0),
    "max_exposure_pct": (float, 1.0, "max_total_exposure", 25.0),
    "max_positions": (int, 1, 22, 6),
    "max_new_trades_per_day": (int, 1, "max_trades_per_day", 2),
}
_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")


class VariantError(ValueError):
    """A variant outside the schema or the rules ceilings."""


class BacktestError(RuntimeError):
    """Inputs a backtest cannot honestly run on."""


# ── data ────────────────────────────────────────────────────────────────────

def clean_bars(raw: list) -> tuple[list, int]:
    """Valid daily bars sorted by date, one per date; returns (bars, dropped)."""
    by_date = {}
    dropped = 0
    for bar in raw or []:
        ok, _ = core.is_valid_daily_bar(bar)
        d = str(bar.get("date", ""))[:10] if isinstance(bar, dict) else ""
        if not ok or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
            dropped += 1
            continue
        by_date[d] = {"date": d, **{k: float(bar[k]) for k in ("open", "high", "low", "close")},
                      "volume": float(bar["volume"])}
    return [by_date[d] for d in sorted(by_date)], dropped


def load_csv_dir(path) -> dict:
    """<SYMBOL>.csv files with a date,open,high,low,close,volume header."""
    import csv
    out = {}
    for f in sorted(Path(path).glob("*.csv")):
        with f.open(newline="") as fh:
            rows = [{k.strip().lower(): v for k, v in row.items()} for row in csv.DictReader(fh)]
        bars = []
        for row in rows:
            try:
                bars.append({"date": row["date"], **{k: float(row[k]) for k in
                             ("open", "high", "low", "close", "volume")}})
            except (KeyError, TypeError, ValueError):
                continue
        out[f.stem.upper()] = clean_bars(bars)[0]
    if not out:
        raise BacktestError(f"no <SYMBOL>.csv files in {path}")
    return out


def fetch_bridge_bars(symbols, duration="5 Y", bridge_url=None, timeout=60) -> dict:
    """Daily bars from the bridge's read-only POST /market/bars."""
    import os
    import urllib.request
    url = (bridge_url or os.environ.get("IBKR_BRIDGE_URL", "http://127.0.0.1:8790")).rstrip("/")
    out = {}
    for sym in symbols:
        body = json.dumps({"symbol": sym, "duration": duration, "bar_size": "1 day"}).encode()
        req = urllib.request.Request(f"{url}/market/bars", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        if not data.get("ok"):
            raise BacktestError(f"bridge returned no bars for {sym}: {data.get('error')}")
        out[sym.upper()] = clean_bars(data.get("bars", []))[0]
    return out


def synthetic_bars(symbols, days=700, seed=7, start="2022-01-03") -> dict:
    """SYNTHETIC random-walk daily bars (weekdays only) for tests and dry runs."""
    import random
    rng = random.Random(seed)
    dates, d = [], date.fromisoformat(start)
    while len(dates) < days:
        if d.weekday() < 5:
            dates.append(d.isoformat())
        d += timedelta(days=1)
    out = {}
    for i, sym in enumerate(symbols):
        drift = 0.0006 * ((i % 5) - 1.5)
        price, bars = 50.0 + 10 * i, []
        for dt in dates:
            o = price * math.exp(rng.gauss(0, 0.004))
            c = o * math.exp(drift + rng.gauss(0, 0.015))
            h = max(o, c) * math.exp(abs(rng.gauss(0, 0.006)))
            lo = min(o, c) * math.exp(-abs(rng.gauss(0, 0.006)))
            bars.append({"date": dt, "open": round(o, 2), "high": round(h, 2),
                         "low": round(lo, 2), "close": round(c, 2), "volume": 1_000_000.0})
            price = c
        out[sym.upper()] = bars
    return out


def truncate_before(bars_by_symbol: dict, cutoff: str | None) -> dict:
    """Drop every bar dated on or after cutoff (YYYY-MM-DD)."""
    if not cutoff:
        return bars_by_symbol
    return {s: [b for b in bars if b["date"] < cutoff] for s, bars in bars_by_symbol.items()}


def fingerprint(bars_by_symbol: dict) -> str:
    blob = json.dumps(bars_by_symbol, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def date_range(bars_by_symbol: dict) -> tuple[str | None, str | None]:
    dates = [b["date"] for bars in bars_by_symbol.values() for b in bars]
    return (min(dates), max(dates)) if dates else (None, None)


# ── variants ────────────────────────────────────────────────────────────────

def ceilings(rules: dict) -> dict:
    """The rules values a variant may not exceed, plus the tradeable universe."""
    try:
        return {
            "max_risk_per_trade": float(rules["max_risk_per_trade"]["value"]),
            "max_position_notional": float(rules["max_position_notional"]["value"]),
            "max_total_exposure": float(rules["max_total_exposure"]["value"]),
            "max_trades_per_day": int(rules["max_trades_per_day"]["value"]),
            "weekly_loss_halt_pct": float(rules["loss_halts"]["weekly"]["value"]),
            "allowlist": [s.upper() for s in rules["symbol_allowlist"]["allow"]],
            "sectors": {k.upper(): v for k, v in (rules.get("symbol_sectors") or {}).items()},
            "max_positions_per_sector": (rules.get("max_positions_per_sector") or {}).get("value"),
        }
    except (KeyError, TypeError, ValueError) as e:
        raise BacktestError(f"rules are missing a ceiling: {e!r}") from e


def validate_variant(spec: dict, rules: dict) -> dict:
    """Normalized variant, or VariantError. Unknown fields are rejected."""
    if not isinstance(spec, dict):
        raise VariantError("variant must be an object")
    caps = ceilings(rules)
    unknown = set(spec) - set(VARIANT_FIELDS) - {"name", "description"}
    if unknown:
        raise VariantError(f"unknown variant fields: {sorted(unknown)}")
    name = spec.get("name")
    if not isinstance(name, str) or not _NAME.match(name):
        raise VariantError(f"variant name {name!r} must match {_NAME.pattern}")
    out = {"name": name, "description": str(spec.get("description", ""))[:500]}
    for key, (typ, lo, hi, default) in VARIANT_FIELDS.items():
        value = spec.get(key, default)
        hi = caps[hi] if isinstance(hi, str) else hi
        if typ is bool:
            if not isinstance(value, bool):
                raise VariantError(f"{key} must be true or false")
        else:
            if isinstance(value, bool) or not isinstance(value, (int, float)) \
                    or not math.isfinite(value):
                raise VariantError(f"{key} must be a number")
            if typ is int and value != int(value):
                raise VariantError(f"{key} must be a whole number")
            value = typ(value)
            if not lo <= value <= hi:
                raise VariantError(f"{key}={value} outside [{lo}, {hi}]")
        out[key] = value
    return out


# ── engine ──────────────────────────────────────────────────────────────────

class _Series:
    def __init__(self, bars):
        self.bars = bars
        self.dates = [b["date"] for b in bars]
        self.index = {d: i for i, d in enumerate(self.dates)}

    def on(self, d):
        i = self.index.get(d)
        return None if i is None else self.bars[i]

    def upto(self, d, n=None, before=False):
        """Bars dated <= d (< d when before), the last n of them."""
        end = (bisect.bisect_left if before else bisect.bisect_right)(self.dates, d)
        return self.bars[max(0, end - n):end] if n else self.bars[:end]

    def since(self, first, d):
        """Bars dated in [first, d)."""
        return self.bars[bisect.bisect_left(self.dates, first):bisect.bisect_left(self.dates, d)]


def run_backtest(bars_by_symbol: dict, variant: dict, rules: dict, *, start=None, end=None,
                 initial_equity=100_000.0, slippage_bps=5.0, commission=1.0) -> dict:
    """Simulate one variant; trades only on dates in [start, end], indicators
    use every bar up to the decision date (the warm-up before start)."""
    v = validate_variant(variant, rules)
    caps = ceilings(rules)
    universe = sorted(s for s in bars_by_symbol if s in caps["allowlist"] and s != BENCHMARK)
    if not universe:
        raise BacktestError("no allowlisted symbol in the data")
    if (v["regime_filter"] or v["vol_scaling"]) and not bars_by_symbol.get(BENCHMARK):
        raise BacktestError(f"regime_filter / vol_scaling need {BENCHMARK} bars")
    series = {s: _Series(bars_by_symbol[s]) for s in universe}
    bench = _Series(bars_by_symbol.get(BENCHMARK) or [])
    calendar = sorted({d for s in universe for d in series[s].dates})
    days = [d for d in calendar if (not start or d >= start) and (not end or d <= end)]
    if len(days) < 2:
        raise BacktestError(f"fewer than 2 trading days in [{start}, {end}]")

    slip = slippage_bps / 10_000.0
    trades_cap = min(v["max_new_trades_per_day"], caps["max_trades_per_day"])
    sector_cap = caps["max_positions_per_sector"]
    cash = float(initial_equity)
    positions, closed, skipped = {}, [], {}
    pending_entries, pending_exits = [], {}          # exits: symbol -> reason
    equity_curve, regimes, budgets, binding = [], [], [], {}
    week, week_start_equity, last_equity = None, cash, cash
    halted_days = 0

    def skip(reason):
        skipped[reason] = skipped.get(reason, 0) + 1

    def close(sym, price, d, reason):
        nonlocal cash
        pos = positions.pop(sym)
        cash += pos["shares"] * price - commission
        pnl = pos["shares"] * (price - pos["entry_price"]) - 2 * commission
        closed.append({
            "symbol": sym, "entry_date": pos["entry_date"], "exit_date": d,
            "entry_price": round(pos["entry_price"], 4), "exit_price": round(price, 4),
            "shares": pos["shares"], "stop": pos["stop"], "exit_reason": reason,
            "hold_days": pos["days_held"], "pnl_usd": round(pnl, 2),
            "r_multiple": round(pnl / (pos["shares"] * pos["risk_per_share"]), 3),
            "binding": pos["binding"], "equity_at_entry": pos["equity_at_entry"],
        })

    def marked(d, before=False):
        """Position value at d's close, or at the prior close (before=True)."""
        value = 0.0
        for sym, pos in positions.items():
            bar = series[sym].upto(d, 1, before=before)
            value += pos["shares"] * (bar[-1]["close"] if bar else pos["entry_price"])
        return value

    for d in days:
        trades_today = 0
        iso = date.fromisoformat(d).isocalendar()[:2]
        if iso != week:
            week, week_start_equity = iso, last_equity

        # 1. exits decided at yesterday's close go through preflight: they count.
        for sym in sorted(pending_exits):
            bar = series[sym].on(d) if sym in positions else None
            if bar is None or trades_today >= trades_cap:
                continue                     # deferred to the next day
            close(sym, bar["open"] * (1 - slip), d, pending_exits[sym])
            trades_today += 1

        # 2. entries at the open.
        halted = last_equity <= week_start_equity * (1 - caps["weekly_loss_halt_pct"] / 100)
        halted_days += bool(halted and pending_entries)
        budget_pct = budgets[-1]["effective_budget_pct"] if budgets else 0.0
        for sym in pending_entries:
            if halted:
                skip("weekly_loss_halt")
                break
            if trades_today >= trades_cap:
                skip("trades_per_day")
                break
            if len(positions) >= v["max_positions"]:
                skip("max_positions")
                break
            sector = caps["sectors"].get(sym)
            if sector_cap and sector and sum(
                    caps["sectors"].get(p) == sector for p in positions) >= sector_cap:
                skip("sector_cap")
                continue
            bar = series[sym].on(d)
            if bar is None or sym in positions:
                continue
            entry = bar["open"] * (1 + slip)
            window = series[sym].since(
                (date.fromisoformat(d) - timedelta(days=STOP_WINDOW_DAYS)).isoformat(), d)
            try:
                gstop = guard.calc_stop(entry, window)
            except (ValueError, ZeroDivisionError):
                skip("stop_uncomputable")
                continue
            stop = max(gstop["stop_price"], round(entry - v["atr_multiplier"] * gstop["atr14"], 2))
            if stop >= bar["open"]:
                skip("stop_at_or_above_open")
                continue
            distance = round(entry - stop, 2)
            held = marked(d, before=True)
            equity_now = cash + held
            sizing = guard.compute_final_max_shares(
                {"max_position_notional": {"value": v["max_position_pct"]},
                 "max_risk_per_trade": {"value": v["risk_pct"]}},
                equity_now, 1.0, entry, distance)
            room = equity_now * budget_pct / 100 - held
            by_budget = math.floor(max(room, 0) / entry)
            by_cash = math.floor(max(cash - commission, 0) / entry)
            shares = min(sizing["final_max_shares"], by_budget, by_cash)
            if shares < 1:
                skip("no_budget" if by_budget < 1 else "size_below_one_share")
                continue
            cap = sizing["binding_cap"] if shares == sizing["final_max_shares"] else "budget"
            binding[cap] = binding.get(cap, 0) + 1
            cash -= shares * entry + commission
            positions[sym] = {"shares": shares, "entry_price": entry, "entry_date": d,
                              "stop": stop, "risk_per_share": entry - stop, "days_held": 0,
                              "binding": cap, "equity_at_entry": round(equity_now, 2)}
            trades_today += 1

        # 3. broker-side stops; they do not go through preflight.
        for sym in sorted(positions):
            bar = series[sym].on(d)
            pos = positions[sym]
            if bar is None:
                continue
            if bar["open"] <= pos["stop"] and pos["entry_date"] != d:
                close(sym, bar["open"] * (1 - slip), d, "stop_gap")
            elif bar["low"] <= pos["stop"]:
                close(sym, pos["stop"] * (1 - slip), d, "stop")

        # 4. mark at the close, then decide tomorrow's orders.
        for pos in positions.values():
            pos["days_held"] += 1
        last_equity = cash + marked(d)
        exposure = marked(d)
        equity_curve.append({"date": d, "equity": round(last_equity, 2),
                             "exposure_pct": round(100 * exposure / last_equity, 3)})

        regime = "RISK_ON"
        scalar = 1.0
        if v["regime_filter"]:
            regime = core.compute_regime_state(bench.upto(d, REGIME_BARS))["regime"]
        if v["vol_scaling"]:
            vol = core.compute_realized_vol(bench.upto(d, VOL_BARS))
            scalar = core.compute_gross_scalar(vol["sigma_ref"])["gross_scalar"]
        budgets.append(core.compute_effective_budget(
            max_total_exposure_pct=v["max_exposure_pct"], gross_scalar=scalar, regime=regime))
        if budgets[-1]["effective_budget_pct"] > caps["max_total_exposure"]:
            raise BacktestError("effective budget above the rules ceiling")  # F14, by construction
        regimes.append(regime)

        pending_exits = {s: r for s, r in pending_exits.items() if s in positions}
        for sym, pos in positions.items():
            closes = series[sym].upto(d, v["trend_sma_days"])
            sma = core.compute_sma(closes, v["trend_sma_days"])
            if v["trend_exit"] and sma is not None and closes[-1]["close"] < sma:
                pending_exits.setdefault(sym, "trend_exit")
            elif v["max_hold_days"] and pos["days_held"] >= v["max_hold_days"]:
                pending_exits.setdefault(sym, "time_exit")

        pending_entries = []
        if budgets[-1]["effective_budget_pct"] > 0:
            today = {s: series[s].upto(d, max(v["trend_sma_days"], v["rs_lookback_days"]))
                     for s in universe if series[s].on(d) is not None}
            top = None
            if v["rs_filter"]:
                rs = core.compute_cross_sectional_rs(
                    {s: b[-v["rs_lookback_days"]:] for s, b in today.items()},
                    lookback_days=v["rs_lookback_days"], min_bars=v["rs_lookback_days"],
                    top_fraction=v["rs_top_fraction"], total_allowlist=len(universe))
                top = set() if rs["no_trade"] else set(rs["top_half_symbols"])
            ranked = []
            for s, b in today.items():
                if s in positions or (top is not None and s not in top):
                    continue
                sma = core.compute_sma(b, v["trend_sma_days"])
                if sma is None or b[-1]["close"] <= sma or len(b) < v["rs_lookback_days"]:
                    continue
                ret = b[-1]["close"] / b[-v["rs_lookback_days"]]["close"] - 1
                ranked.append((-ret, s))
            pending_entries = [s for _, s in sorted(ranked)]

    last_day = days[-1]
    open_positions = [{"symbol": s, "shares": p["shares"], "entry_date": p["entry_date"],
                       "entry_price": round(p["entry_price"], 4), "stop": p["stop"]}
                      for s, p in sorted(positions.items())]
    return {
        "label": LABEL,
        "variant": v,
        "period": {"start": days[0], "end": last_day, "trading_days": len(days)},
        "universe": universe,
        "assumptions": {"initial_equity_usd": initial_equity, "slippage_bps": slippage_bps,
                        "commission_usd_per_order": commission, "fills": "next open",
                        "stop_window": f"{STOP_WINDOW_DAYS} calendar days (guard.fetch_bars)",
                        "not_modelled": ["intraday daily loss halt", "entry blackout windows",
                                         "partial fills", "market impact", "FX"]},
        "metrics": _metrics(equity_curve, closed, regimes, budgets, binding, days),
        "skipped_entries": dict(sorted(skipped.items())),
        "weekly_halt_days": halted_days,
        "trades": closed,
        "open_at_end": open_positions,
        "equity_curve": equity_curve,
    }


def _metrics(curve, trades, regimes, budgets, binding, days) -> dict:
    equities = [p["equity"] for p in curve]
    rets = [b / a - 1 for a, b in zip(equities, equities[1:]) if a > 0]
    peak, max_dd = equities[0], 0.0
    for e in equities:
        peak = max(peak, e)
        max_dd = max(max_dd, 1 - e / peak)
    years = len(days) / core.TRADING_DAYS_PER_YEAR
    total = equities[-1] / equities[0] - 1
    sd = statistics.pstdev(rets) if len(rets) > 1 else 0.0
    entries = sum(binding.values())
    rs = [t["r_multiple"] for t in trades]
    return {
        "total_return_pct": round(100 * total, 3),
        "cagr_pct": round(100 * ((1 + total) ** (1 / years) - 1), 3) if years > 0 and total > -1 else None,
        "max_drawdown_pct": round(100 * max_dd, 3),
        "volatility_pct": round(100 * sd * math.sqrt(core.TRADING_DAYS_PER_YEAR), 3),
        "sharpe": round(statistics.mean(rets) / sd * math.sqrt(core.TRADING_DAYS_PER_YEAR), 3) if sd else None,
        "entries": entries,
        "entries_per_week": round(entries / max(len(days) / 5, 1), 3),
        "closed_trades": len(trades),
        "win_rate_pct": round(100 * sum(t["pnl_usd"] > 0 for t in trades) / len(trades), 2) if trades else None,
        "avg_r_multiple": round(statistics.mean(rs), 3) if rs else None,
        "median_r_multiple": round(statistics.median(rs), 3) if rs else None,
        "stop_exit_share_pct": round(100 * sum(t["exit_reason"].startswith("stop") for t in trades) / len(trades), 2) if trades else None,
        "avg_hold_days": round(statistics.mean(t["hold_days"] for t in trades), 2) if trades else None,
        "avg_exposure_pct": round(statistics.mean(p["exposure_pct"] for p in curve), 3),
        "risk_cap_binding_share_pct": round(100 * binding.get("risk", 0) / entries, 2) if entries else None,
        "binding_caps": dict(sorted(binding.items())),
        "risk_on_share_pct": round(100 * regimes.count("RISK_ON") / len(regimes), 2),
        "median_gross_scalar": round(statistics.median(b["gross_scalar"] for b in budgets), 4),
    }


def summarize(result: dict) -> dict:
    """The result without per-day and per-trade detail (what a prompt carries)."""
    return {k: v for k, v in result.items() if k not in ("equity_curve", "trades")}


# ── study: train / holdout, variant budget, holdout once ────────────────────

def split_period(bars_by_symbol: dict, holdout_fraction=0.3, holdout_start=None) -> dict:
    """Train is everything before holdout_start; the holdout runs to the last bar."""
    calendar = sorted({b["date"] for s, bars in bars_by_symbol.items() if s != BENCHMARK
                       for b in bars})
    if len(calendar) < REGIME_BARS + 40:
        raise BacktestError(f"need at least {REGIME_BARS + 40} trading days, have {len(calendar)}")
    usable = calendar[REGIME_BARS:]          # the first year only warms the regime up
    if holdout_start is None:
        if not 0.1 <= holdout_fraction <= 0.5:
            raise BacktestError("holdout_fraction must be in [0.1, 0.5]")
        holdout_start = usable[int(len(usable) * (1 - holdout_fraction))]
    train = [d for d in usable if d < holdout_start]
    hold = [d for d in usable if d >= holdout_start]
    if len(train) < 20 or len(hold) < 20:
        raise BacktestError("train and holdout need at least 20 trading days each")
    return {"train": {"start": train[0], "end": train[-1]},
            "holdout": {"start": hold[0], "end": hold[-1]}}


def run_study(bars_by_symbol: dict, variants: list, rules: dict, out_dir, *,
              periods: dict | None = None, **engine_kw) -> dict:
    """Every variant on the train period only; writes study.json."""
    if not 1 <= len(variants) <= MAX_VARIANTS:
        raise VariantError(f"a study takes 1..{MAX_VARIANTS} variants, got {len(variants)}")
    specs = [validate_variant(v, rules) for v in variants]
    if len({s["name"] for s in specs}) != len(specs):
        raise VariantError("variant names must be unique")
    periods = periods or split_period(bars_by_symbol)
    results = [summarize(run_backtest(bars_by_symbol, s, rules, start=periods["train"]["start"],
                                      end=periods["train"]["end"], **engine_kw)) for s in specs]
    study = {
        "label": LABEL,
        "created_utc": _now(),
        "data_fingerprint": fingerprint(bars_by_symbol),
        "data_range": dict(zip(("first", "last"), date_range(bars_by_symbol))),
        "periods": periods,
        "engine": engine_kw,
        "variant_budget": MAX_VARIANTS,
        "variants": specs,
        "train_results": results,
    }
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "study.json").write_text(json.dumps(study, indent=2))
    return study


def evaluate_holdout(study_path, bars_by_symbol: dict, variant_name: str, rules: dict) -> dict:
    """The one holdout look for a study. A second call raises."""
    study_path = Path(study_path)
    ledger = study_path.with_name("holdout.json")
    if ledger.exists():
        prior = json.loads(ledger.read_text())
        raise BacktestError(f"holdout already evaluated for {prior['variant']['name']!r} "
                            f"at {prior['evaluated_utc']}; a study gets one look")
    study = json.loads(study_path.read_text())
    if fingerprint(bars_by_symbol) != study["data_fingerprint"]:
        raise BacktestError("data differ from the study's data (fingerprint mismatch)")
    spec = next((s for s in study["variants"] if s["name"] == variant_name), None)
    if spec is None:
        raise BacktestError(f"{variant_name!r} is not one of the study's variants")
    result = run_backtest(bars_by_symbol, spec, rules, start=study["periods"]["holdout"]["start"],
                          end=study["periods"]["holdout"]["end"], **study["engine"])
    record = {"label": LABEL, "evaluated_utc": _now(), "variant": spec, "result": summarize(result)}
    with ledger.open("x") as fh:            # exclusive create: one look, even when racing
        fh.write(json.dumps(record, indent=2))
    return record


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── CLI ─────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", required=True, help="directory of <SYMBOL>.csv daily bars")
    ap.add_argument("--rules", help="paper-trading-rules.yaml (default: the guard's RULES_PATH)")
    ap.add_argument("--variants", help="JSON list of variants (train run)")
    ap.add_argument("--out", help="study directory for study.json (train run)")
    ap.add_argument("--holdout-fraction", type=float, default=0.3)
    ap.add_argument("--study", help="study.json (holdout run)")
    ap.add_argument("--holdout", metavar="VARIANT", help="evaluate this variant on the holdout, once")
    args = ap.parse_args(argv)

    import yaml
    rules = yaml.safe_load(Path(args.rules or guard.RULES_PATH).read_text())
    bars = load_csv_dir(args.data)
    try:
        if args.holdout:
            if not args.study:
                ap.error("--holdout needs --study")
            print(json.dumps(evaluate_holdout(args.study, bars, args.holdout, rules), indent=2))
        else:
            if not (args.variants and args.out):
                ap.error("a train run needs --variants and --out")
            variants = json.loads(Path(args.variants).read_text())
            periods = split_period(bars, args.holdout_fraction)
            study = run_study(bars, variants, rules, args.out, periods=periods)
            print(json.dumps({k: study[k] for k in ("label", "periods", "train_results")}, indent=2))
    except (BacktestError, VariantError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
