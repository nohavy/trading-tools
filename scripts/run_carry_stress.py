"""Cost stress for the always-covered carry hedge, in the event engine.

Replays both legs per symbol under the shared degraded-cost scenarios
(STRESS_SCENARIOS) and judges survival on the frozen project criteria
(t Newey-West >= 2, drawdown <= 25 %, OOS return > 0) rather than a trade
expectancy, since a single-entry hedge never closes and has no round trips.
"""

import argparse
import copy
import json
from pathlib import Path
from typing import Any

import yaml
from run_carry_engine_validation import run_symbol_cfg

from tradingv2.backtest.stress import STRESS_SCENARIOS

SCENARIOS = ("fees_x1.5", "slippage_x2", "latency_plus_250ms", "combined")


def _stressed_cfg(
    base: dict[str, Any], fee_mult: float, slip_mult: float, latency_add_ms: float
) -> dict[str, Any]:
    cfg = copy.deepcopy(base)
    for leg in cfg["legs"].values():
        costs = leg["costs"]
        costs["maker_bps"] = float(costs["maker_bps"]) * fee_mult
        costs["taker_bps"] = float(costs["taker_bps"]) * fee_mult
        costs["slippage_bps"] = float(costs["slippage_bps"]) * slip_mult
        costs["latency"]["mean_ms"] = float(costs["latency"]["mean_ms"]) + latency_add_ms
    return cfg


def _frozen_verdict(oos: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    stats = oos["full"]
    verdict = (
        stats["total_return"] is not None
        and stats["total_return"] > 0
        and stats["t_stat_nw"] is not None
        and stats["t_stat_nw"] >= 2.0
        and stats["max_drawdown"] <= 0.25
    )
    return verdict, stats


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--runs-root", type=Path, default=Path("runs/carry-stress-2026-10"))
    parser.add_argument("--out", type=Path, default=Path("data/carry_stress.json"))
    parser.add_argument("--symbols", default="btc,eth")
    args = parser.parse_args()

    rows: list[dict[str, Any]] = []
    for stem in args.symbols.split(","):
        config_path = Path(f"configs/research-carry-engine-{stem.strip()}.yaml")
        base = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        for name in SCENARIOS:
            fee_mult, slip_mult, latency_add = STRESS_SCENARIOS[name]
            print(
                f"{stem} scenario {name} (fees x{fee_mult}, slip x{slip_mult}, "
                f"+{latency_add} ms)...", flush=True
            )
            result = run_symbol_cfg(
                _stressed_cfg(base, fee_mult, slip_mult, latency_add),
                data_root=args.data_root,
                runs_root=args.runs_root,
            )
            verdict, stats = _frozen_verdict(result["oos"])
            rows.append(
                {
                    "symbol": result["symbol"],
                    "scenario": name,
                    "survived_frozen_criteria": verdict,
                    "oos_full": result["oos"],
                    "legs": result["legs"],
                    "coverage_ratio": result["coverage_ratio"],
                }
            )
            print(
                f"  total={stats['total_return']:+.2%} t={stats['t_stat_nw']} "
                f"DD={stats['max_drawdown']:.2%} -> "
                f"{'SURVIT' if verdict else 'NON SURVIVANT'}", flush=True
            )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rows, indent=2, allow_nan=False), encoding="utf-8")
    by_symbol: dict[str, dict[str, bool]] = {}
    for row in rows:
        by_symbol.setdefault(row["symbol"], {})[row["scenario"]] = (
            row["survived_frozen_criteria"]
        )
    for symbol, scenarios in by_symbol.items():
        flags = " ".join(f"{name}={'OK' if ok else 'FAIL'}" for name, ok in scenarios.items())
        print(f"{symbol}: {flags}")
    survived_all = all(row["survived_frozen_criteria"] for row in rows)
    print(f"verdict global stress: {'SURVIT PARTOUT' if survived_all else 'ECHEC'}")
    print(f"written: {args.out}")


if __name__ == "__main__":
    main()
