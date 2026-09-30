"""Walk-forward: chronological train/test folds, no overlap, OOS aggregate."""

from dataclasses import dataclass, field
from pathlib import Path

from tradingv2.backtest.runner import run_backtest
from tradingv2.backtest.sweep import sweep_grid


class WalkForwardError(Exception):
    """Raised when the period is too short for the requested folds."""


@dataclass(frozen=True)
class Fold:
    """One train/test segment pair and the OOS evaluation of the best params."""

    train_start_ns: int
    train_end_ns: int
    test_start_ns: int
    test_end_ns: int
    best_params: dict[str, float | int]
    test_metrics: dict[str, object]


@dataclass
class WalkForwardResult:
    """All folds plus the out-of-sample aggregate."""

    folds: list[Fold] = field(default_factory=list)
    oos: dict[str, float | int] = field(default_factory=dict)
    pct_positive_folds: float = 0.0


def make_folds(
    bar_close_ts: list[int], train_bars: int, test_bars: int
) -> list[tuple[int, int, int, int]]:
    """Chronological (train_start, train_end, test_start, test_end) bounds.

    Segments are consecutive, non-overlapping; trailing bars without a full
    test segment are unused.
    """
    if train_bars <= 0 or test_bars <= 0:
        raise WalkForwardError(
            f"train/test bar counts must be positive, got {train_bars}/{test_bars}"
        )
    folds: list[tuple[int, int, int, int]] = []
    cursor = 0
    n = len(bar_close_ts)
    while cursor + train_bars + test_bars <= n:
        train_start = bar_close_ts[cursor]
        train_end = bar_close_ts[cursor + train_bars - 1]
        test_start = bar_close_ts[cursor + train_bars]
        test_end = bar_close_ts[cursor + train_bars + test_bars - 1]
        folds.append((train_start, train_end, test_start, test_end))
        cursor += train_bars + test_bars
    return folds


def walk_forward(
    config_path: Path,
    grid: dict[str, list[float | int]],
    *,
    train_bars: int,
    test_bars: int,
    data_root: Path,
    runs_root: Path,
    workers: int = 1,
    min_trades: int = 30,
) -> WalkForwardResult:
    """Optimize the grid on each train segment, evaluate on the following test segment."""
    from tradingv2.backtest.config import load_backtest_config
    from tradingv2.backtest.runner import _load_bars

    cfg = load_backtest_config(config_path)
    bars = _load_bars(cfg, data_root)
    if not bars:
        raise WalkForwardError("no bar data for the configured period")
    closes = [bar.ts_close_ns for bar in bars]
    fold_bounds = make_folds(closes, train_bars, test_bars)
    if not fold_bounds:
        raise WalkForwardError(
            f"period too short: {len(bars)} bars cannot fit train={train_bars} + test={test_bars}"
        )

    folds: list[Fold] = []
    for train_start, train_end, test_start, test_end in fold_bounds:
        sweep = sweep_grid(
            config_path,
            grid,
            data_root=data_root,
            runs_root=runs_root,
            workers=workers,
            min_trades=min_trades,
            bar_bounds=(train_start, train_end),
        )
        best = sweep.entries[0]
        best_params = dict(best.params)
        variant_cfg = _config_with_params(config_path, best_params)
        test_run = run_backtest(
            variant_cfg,
            data_root=data_root,
            runs_root=runs_root,
            bar_bounds=(test_start, test_end),
        )
        metrics = _read_metrics(test_run)
        folds.append(
            Fold(
                train_start_ns=train_start,
                train_end_ns=train_end,
                test_start_ns=test_start,
                test_end_ns=test_end,
                best_params=best_params,
                test_metrics=metrics,
            )
        )
    return _aggregate(folds)


def _config_with_params(config_path: Path, params: dict[str, float | int]) -> Path:
    import yaml

    base = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    variant = yaml.safe_load(yaml.safe_dump(base))
    variant["strategy"]["params"].update(params)
    out = config_path.parent / f".wf-{id(params):x}-{abs(hash(tuple(params.items())))}.yaml"
    out.write_text(yaml.safe_dump(variant), encoding="utf-8")
    return out


def _read_metrics(run_dir: Path) -> dict[str, object]:
    import json

    return json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))


def _aggregate(folds: list[Fold]) -> WalkForwardResult:
    n_trades = sum(int(f.test_metrics["n_trades"]) for f in folds)
    net_total = sum(float(f.test_metrics["net_total"] or 0.0) for f in folds)
    gross_total = sum(float(f.test_metrics["gross_total"] or 0.0) for f in folds)
    fees_total = sum(float(f.test_metrics["fees_total"] or 0.0) for f in folds)
    slippage_total = sum(float(f.test_metrics["slippage_total"] or 0.0) for f in folds)
    funding_total = sum(float(f.test_metrics["funding_total"] or 0.0) for f in folds)
    expectancy_quote = net_total / n_trades if n_trades else 0.0
    positive = sum(1 for f in folds if float(f.test_metrics["net_total"] or 0.0) > 0)
    pct_positive = positive / len(folds) if folds else 0.0
    oos: dict[str, float | int] = {
        "n_trades": n_trades,
        "net_total": net_total,
        "gross_total": gross_total,
        "fees_total": fees_total,
        "slippage_total": slippage_total,
        "funding_total": funding_total,
        "expectancy_quote": expectancy_quote,
    }
    return WalkForwardResult(folds=folds, oos=oos, pct_positive_folds=pct_positive)
