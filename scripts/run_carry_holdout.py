"""One-shot October 2026 holdout of the frozen always-covered carry hedge.

Runs only on or after 2026-11-01 UTC, increments the holdout attempts
counter twice (one per asset) BEFORE any data access, then applies the
preregistered checklist from docs/carry-holdout-2026-10-prereg.md:

1. execution: exactly one fill per leg, zero rejected orders,spot/perp
   coverage >= 0.99 - otherwise: technical failure, result not interpretable;
2. hypothesis "the carry survives the month": BTC+ETH equal-weight net > 0,
   net BTC > 0, net ETH > 0, monthly drawdown <= 2 %.

No parameter may be adjusted after this run, whatever the outcome.
"""

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

import yaml
from run_carry_engine_validation import run_symbol_cfg

from tradingv2.backtest.validate import read_holdout_attempts, register_holdout_attempt

HOLDOUT_OPEN_GATE = dt.datetime(2026, 11, 1, tzinfo=dt.UTC)
HOLDOUT_COUNTER = Path("data/holdout_attempts.json")
STARTED_MARKER = Path("data/carry-holdout-2026-10.started.json")
EXPECTED_ATTEMPTS_BEFORE_LAUNCH = 2
SYMBOLS = ("btc", "eth")
DD_LIMIT = 0.02
COVERAGE_LIMIT = 0.99


def _frozen_verdict(result: dict[str, Any]) -> dict[str, Any]:
    stats = result["oos"]["full"]
    coverage = result["coverage_ratio"]
    fills_ok = all(leg["n_fills"] == 1 for leg in result["legs"].values())
    rejects_ok = all(leg["n_rejected"] == 0 for leg in result["legs"].values())
    execution_ok = fills_ok and rejects_ok and coverage >= COVERAGE_LIMIT
    end = result["combined_equity_end_usdt"]
    start = result["combined_equity_start_usdt"]
    return {
        "execution_ok": execution_ok,
        "coverage_ratio": coverage,
        "n_fills_spot": result["legs"]["spot"]["n_fills"],
        "n_fills_perp": result["legs"]["perp"]["n_fills"],
        "n_rejected": sum(leg["n_rejected"] for leg in result["legs"].values()),
        "net_total": stats["total_return"],
        "drawdown": stats["max_drawdown"],
        "dd_ok": stats["max_drawdown"] <= DD_LIMIT,
        "net_ok": end is not None and end > start,
        "equity_start_usdt": start,
        "equity_end_usdt": end,
        "survived_the_month": (
            execution_ok
            and stats["max_drawdown"] <= DD_LIMIT
            and end > start
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--runs-root", type=Path, default=Path("runs/carry-holdout-2026-10"))
    parser.add_argument("--out", type=Path, default=Path("data/carry-holdout-2026-10.json"))
    args = parser.parse_args()

    now = dt.datetime.now(dt.UTC)
    if now < HOLDOUT_OPEN_GATE:
        print(
            f"gated: holdout stays locked until {HOLDOUT_OPEN_GATE.isoformat()} "
            f"(UTC now: {now.isoformat()})"
        )
        return

    attempts = read_holdout_attempts(HOLDOUT_COUNTER)
    if attempts != EXPECTED_ATTEMPTS_BEFORE_LAUNCH:
        sys.exit(
            f"holdout attempts counter = {attempts}, expected "
            f"{EXPECTED_ATTEMPTS_BEFORE_LAUNCH}: aborting per preregistration"
        )
    register_holdout_attempt(HOLDOUT_COUNTER)
    register_holdout_attempt(HOLDOUT_COUNTER)
    STARTED_MARKER.write_text(json.dumps({"opened_at": now.isoformat()}), encoding="utf-8")
    print(f"holdout opened {now.isoformat()}; attempts counter now "
          f"{read_holdout_attempts(HOLDOUT_COUNTER)}")

    results: list[dict[str, Any]] = []
    verdicts: list[bool] = []
    for stem in SYMBOLS:
        config_path = Path(f"configs/research-carry-holdout-2026-10-{stem}.yaml")
        cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        print(f"running {stem} holdout legs...", flush=True)
        result = run_symbol_cfg(cfg, data_root=args.data_root, runs_root=args.runs_root)
        verdict = _frozen_verdict(result)
        results.append({**result, "frozen_checklist": verdict})
        verdicts.append(verdict["survived_the_month"])
        print(
            f"  net={verdict['net_total']:+.2%} DD={verdict['drawdown']:.2%} "
            f"coverage={verdict['coverage_ratio']:.4f} rejects={verdict['n_rejected']} "
            f"-> {'survives' if verdict['survived_the_month'] else 'FAILS'}", flush=True
        )

    args.out.write_text(json.dumps(results, indent=2, allow_nan=False), encoding="utf-8")
    global_ok = all(verdicts)
    print(f"FROZEN VERDICT: {'HOLDOUT PASSED' if global_ok else 'HOLDOUT FAILED'}")
    print(
        "per prereg: NO paper/live retuning either way; the 3.2y engine OOS "
        "remains the base demonstration; a passing month alone is never a GO."
    )
    print(f"written: {args.out}")


if __name__ == "__main__":
    main()
