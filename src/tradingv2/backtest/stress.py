"""Cost stress scenarios: replay the same run with degraded costs only."""

import json
from dataclasses import dataclass
from pathlib import Path

import yaml

from tradingv2.backtest.runner import run_backtest

# scenario name -> (fee multiplier, slippage multiplier, added latency ms)
STRESS_SCENARIOS: dict[str, tuple[float, float, float]] = {
    "fees_x1.5": (1.5, 1.0, 0.0),
    "slippage_x2": (1.0, 2.0, 0.0),
    "latency_plus_250ms": (1.0, 1.0, 250.0),
    "combined": (1.5, 2.0, 250.0),
}


@dataclass(frozen=True)
class StressScenarioResult:
    """Outcome of one stress scenario."""

    name: str
    run_dir: Path
    expectancy_bps: float | None
    net_total: float | None
    survived: bool


def stress_test(
    config_path: Path,
    *,
    data_root: Path,
    runs_root: Path,
) -> list[StressScenarioResult]:
    """Replay the run once per scenario, changing ONLY the costs block.

    Survival: net expectancy (bps) strictly positive under the scenario.
    """
    base = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    results: list[StressScenarioResult] = []
    for name, (fee_mult, slip_mult, latency_add) in STRESS_SCENARIOS.items():
        variant = yaml.safe_load(yaml.safe_dump(base))
        costs = variant["costs"]
        costs["maker_bps"] = float(costs["maker_bps"]) * fee_mult
        costs["taker_bps"] = float(costs["taker_bps"]) * fee_mult
        costs["slippage_bps"] = float(costs["slippage_bps"]) * slip_mult
        costs["latency"]["mean_ms"] = float(costs["latency"]["mean_ms"]) + latency_add
        scenario_cfg = runs_root / f".stress-{name.replace('.', '_')}.yaml"
        scenario_cfg.parent.mkdir(parents=True, exist_ok=True)
        scenario_cfg.write_text(yaml.safe_dump(variant), encoding="utf-8")
        run_dir = run_backtest(scenario_cfg, data_root=data_root, runs_root=runs_root)
        scenario_cfg.unlink()
        metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
        expectancy = metrics["expectancy_bps"]
        results.append(
            StressScenarioResult(
                name=name,
                run_dir=run_dir,
                expectancy_bps=expectancy,
                net_total=metrics["net_total"],
                survived=expectancy is not None and expectancy > 0,
            )
        )
    return results
