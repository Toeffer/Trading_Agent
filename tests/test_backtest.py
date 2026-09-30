"""sim/backtest.py — bounded variants, no look-ahead, holdout once (2026-09-30).

The backtester is research input for Hermes (hermes-research). These tests pin
what makes its numbers honest: a variant can never be looser than the live
guard (stop from guard.calc_stop, size from guard.compute_final_max_shares,
caps at the rules ceilings, allowlist, sector cap, trades/day), a decision on
day t uses nothing after t, train results do not depend on the holdout, and
the holdout is looked at once. SYNTHETIC data only; results are BACKTEST.
"""

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

import guard  # noqa: E402
from sim import backtest as bt  # noqa: E402
from test_ibkr_owner_thread import RULES_YAML  # noqa: E402

SECTORS = {"AAPL": "IT", "MSFT": "IT", "NVDA": "SEMI", "AMD": "SEMI",
           "JPM": "FIN", "XOM": "EN", "KO": "CS", "CAT": "IND"}


@pytest.fixture(scope="module")
def rules():
    r = yaml.safe_load(RULES_YAML)
    r["symbol_allowlist"]["allow"] = sorted(SECTORS)
    r["symbol_sectors"] = dict(SECTORS)
    return r


@pytest.fixture(scope="module")
def bars():
    # TSLA is in the data but not on the allowlist.
    return bt.synthetic_bars(sorted(SECTORS) + ["TSLA", "SPY"], days=700)


@pytest.fixture(scope="module")
def base(bars, rules):
    return bt.run_backtest(bars, {"name": "base"}, rules)


class TestVariants:
    def test_defaults_are_valid_and_inside_the_ceilings(self, rules):
        v = bt.validate_variant({"name": "base"}, rules)
        assert v["atr_multiplier"] == guard.ATR_MULTIPLIER
        assert v["risk_pct"] <= rules["max_risk_per_trade"]["value"]
        assert v["max_exposure_pct"] <= rules["max_total_exposure"]["value"]

    @pytest.mark.parametrize("spec, needle", [
        ({"name": "x", "atr_multiplier": 2.5}, "atr_multiplier"),       # looser stop
        ({"name": "x", "risk_pct": 2.5}, "risk_pct"),                   # above 2% ceiling
        ({"name": "x", "max_position_pct": 6}, "max_position_pct"),
        ({"name": "x", "max_exposure_pct": 31}, "max_exposure_pct"),
        ({"name": "x", "max_new_trades_per_day": 3}, "max_new_trades_per_day"),
        ({"name": "x", "short": True}, "unknown variant fields"),
        ({"name": "x", "rs_filter": "yes"}, "rs_filter"),
        ({"name": "x", "trend_sma_days": 20.5}, "whole number"),
        ({"name": "x", "risk_pct": float("nan")}, "risk_pct"),
        ({"name": "Bad Name"}, "variant name"),
    ])
    def test_out_of_bounds_is_rejected(self, rules, spec, needle):
        with pytest.raises(bt.VariantError, match=needle):
            bt.validate_variant(spec, rules)

    def test_ceilings_follow_the_rules_file(self, rules):
        tighter = {**rules, "max_risk_per_trade": {"value": 0.5}}
        with pytest.raises(bt.VariantError):
            bt.validate_variant({"name": "x", "risk_pct": 1.0}, tighter)


class TestEngine:
    def test_is_labelled_and_deterministic(self, bars, rules, base):
        assert base["label"].startswith("BACKTEST")
        assert base["metrics"]["entries"] > 10, base["skipped_entries"]
        again = bt.run_backtest(bars, {"name": "base"}, rules)
        assert again["trades"] == base["trades"] and again["equity_curve"] == base["equity_curve"]

    def test_no_look_ahead(self, rules):
        """A run on data that ends at a cut must match the full run up to it.
        Checked at many cuts, so a peek of a few days anywhere shows up."""
        data = bt.synthetic_bars(sorted(SECTORS), days=360, seed=11)
        fast = {"name": "fast", "regime_filter": False, "vol_scaling": False,
                "trend_sma_days": 20, "rs_lookback_days": 20, "max_hold_days": 10}
        full = bt.run_backtest(data, fast, rules)
        dates = [p["date"] for p in full["equity_curve"]]
        assert full["metrics"]["entries"] > 30
        for cut in dates[60:-1:12]:
            upto = bt.truncate_before(data, (date.fromisoformat(cut) + timedelta(days=1)).isoformat())
            part = bt.run_backtest(upto, fast, rules)
            assert part["equity_curve"] == full["equity_curve"][:len(part["equity_curve"])], cut
            assert part["trades"] == [t for t in full["trades"] if t["exit_date"] <= cut], cut

    def test_only_allowlisted_symbols_trade(self, base):
        traded = {t["symbol"] for t in base["trades"]} | {p["symbol"] for p in base["open_at_end"]}
        assert traded and traded <= set(SECTORS)

    def test_stop_is_the_guards_stop_on_bars_before_entry(self, bars, base):
        """atr_multiplier 2.0 (the default) reproduces guard.calc_stop exactly,
        on the 30 calendar days before the entry day and nothing from it."""
        slip = 1 + base["assumptions"]["slippage_bps"] / 10_000
        for t in base["trades"]:
            first = (date.fromisoformat(t["entry_date"]) - timedelta(days=30)).isoformat()
            window = [b for b in bars[t["symbol"]] if first <= b["date"] < t["entry_date"]]
            opened = next(b["open"] for b in bars[t["symbol"]] if b["date"] == t["entry_date"])
            assert t["stop"] == guard.calc_stop(opened * slip, window)["stop_price"], t

    def test_tighter_atr_multiplier_tightens_stops(self, bars, rules, base):
        tight = bt.run_backtest(bars, {"name": "tight", "atr_multiplier": 1.0}, rules)
        first = tight["trades"][0]
        same = next(t for t in base["trades"] if t["symbol"] == first["symbol"]
                    and t["entry_date"] == first["entry_date"])
        assert first["stop"] >= same["stop"]

    def test_size_respects_risk_and_notional_caps(self, base):
        v = base["variant"]
        for t in base["trades"]:
            risk = t["shares"] * (t["entry_price"] - t["stop"])
            assert risk <= v["risk_pct"] / 100 * t["equity_at_entry"] * 1.001, t
            assert t["shares"] * t["entry_price"] <= v["max_position_pct"] / 100 * t["equity_at_entry"] * 1.001

    def test_exposure_stays_under_the_ceiling(self, base, rules):
        ceiling = rules["max_total_exposure"]["value"]
        # entries are sized at the open; the close can drift a little above
        assert max(p["exposure_pct"] for p in base["equity_curve"]) <= ceiling * 1.2

    def test_trades_per_day_counts_entries_and_signal_exits(self, base, rules):
        per_day = {}
        for t in base["trades"]:
            per_day[t["entry_date"]] = per_day.get(t["entry_date"], 0) + 1
            if not t["exit_reason"].startswith("stop"):
                per_day[t["exit_date"]] = per_day.get(t["exit_date"], 0) + 1
        for p in base["open_at_end"]:
            per_day[p["entry_date"]] = per_day.get(p["entry_date"], 0) + 1
        assert max(per_day.values()) <= rules["max_trades_per_day"]["value"]

    def test_sector_cap_holds_at_every_entry(self, base):
        trades = base["trades"] + [dict(p, exit_date="9999-12-31", exit_reason="open")
                                   for p in base["open_at_end"]]
        for new in trades:
            d = new["entry_date"]
            held = [t for t in trades if t is not new and t["entry_date"] < d and
                    (t["exit_date"] > d or (t["exit_date"] == d and t["exit_reason"].startswith("stop")))]
            assert all(SECTORS[t["symbol"]] != SECTORS[new["symbol"]] for t in held), (new, held)

    def test_risk_off_means_no_entries(self, bars, rules):
        falling = [dict(b, open=round(400 - i * 0.2, 2), high=round(401 - i * 0.2, 2),
                        low=round(399 - i * 0.2, 2), close=round(400 - i * 0.2, 2))
                   for i, b in enumerate(bars["SPY"])]
        r = bt.run_backtest({**bars, "SPY": falling}, {"name": "base"}, rules)
        assert r["metrics"]["entries"] == 0 and r["metrics"]["risk_on_share_pct"] == 0

    def test_regime_needs_the_benchmark(self, bars, rules):
        no_spy = {k: v for k, v in bars.items() if k != "SPY"}
        with pytest.raises(bt.BacktestError, match="SPY"):
            bt.run_backtest(no_spy, {"name": "base"}, rules)
        r = bt.run_backtest(no_spy, {"name": "plain", "regime_filter": False, "vol_scaling": False}, rules)
        assert r["metrics"]["entries"] > 0


class TestStudy:
    def test_variant_budget(self, bars, rules, tmp_path):
        with pytest.raises(bt.VariantError, match="1..5"):
            bt.run_study(bars, [{"name": f"v{i}"} for i in range(6)], rules, tmp_path)
        with pytest.raises(bt.VariantError, match="unique"):
            bt.run_study(bars, [{"name": "a"}, {"name": "a"}], rules, tmp_path)

    def test_split_is_ordered_and_disjoint(self, bars):
        p = bt.split_period(bars)
        assert p["train"]["start"] < p["train"]["end"] < p["holdout"]["start"] <= p["holdout"]["end"]

    def test_train_results_do_not_depend_on_the_holdout(self, bars, rules, tmp_path):
        p = bt.split_period(bars)
        a = bt.run_study(bars, [{"name": "a"}], rules, tmp_path / "a", periods=p)
        shocked = {s: [dict(b, close=b["close"] * 0.5, low=b["low"] * 0.5)
                       if b["date"] >= p["holdout"]["start"] else b for b in bs]
                   for s, bs in bars.items()}
        b = bt.run_study(shocked, [{"name": "a"}], rules, tmp_path / "b", periods=p)
        assert a["train_results"] == b["train_results"]

    def test_holdout_is_evaluated_once(self, bars, rules, tmp_path):
        study = bt.run_study(bars, [{"name": "a"}, {"name": "b", "atr_multiplier": 1.5}],
                             rules, tmp_path)
        assert [r["variant"]["name"] for r in study["train_results"]] == ["a", "b"]
        with pytest.raises(bt.BacktestError, match="not one of"):
            bt.evaluate_holdout(tmp_path / "study.json", bars, "zzz", rules)
        with pytest.raises(bt.BacktestError, match="fingerprint"):
            bt.evaluate_holdout(tmp_path / "study.json", bt.truncate_before(bars, "2024-01-01"),
                                "a", rules)
        rec = bt.evaluate_holdout(tmp_path / "study.json", bars, "b", rules)
        assert rec["result"]["period"]["start"] == study["periods"]["holdout"]["start"]
        with pytest.raises(bt.BacktestError, match="one look"):
            bt.evaluate_holdout(tmp_path / "study.json", bars, "a", rules)


def test_cli_train_then_holdout(bars, rules, tmp_path, capsys):
    data = tmp_path / "data"
    data.mkdir()
    for sym, series in bars.items():
        lines = ["date,open,high,low,close,volume"] + [
            f"{b['date']},{b['open']},{b['high']},{b['low']},{b['close']},{b['volume']}" for b in series]
        (data / f"{sym}.csv").write_text("\n".join(lines) + "\n")
    (tmp_path / "rules.yaml").write_text(yaml.safe_dump(rules))
    (tmp_path / "v.json").write_text(json.dumps([{"name": "a"}]))
    common = ["--data", str(data), "--rules", str(tmp_path / "rules.yaml")]
    assert bt.main(common + ["--variants", str(tmp_path / "v.json"), "--out", str(tmp_path / "s")]) == 0
    assert json.loads(capsys.readouterr().out)["label"].startswith("BACKTEST")
    study = str(tmp_path / "s" / "study.json")
    assert bt.main(common + ["--study", study, "--holdout", "a"]) == 0
    capsys.readouterr()
    assert bt.main(common + ["--study", study, "--holdout", "a"]) == 2
