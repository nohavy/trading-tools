"""Go/no-go verdict on fixed criteria, and the holdout attempts counter.

The verdict is the gate to paper trading (founding plan section 7): it is
computed on out-of-sample data only, criterion by criterion, with no silent
exception (constitution II). The holdout attempts counter makes overfitting
visible: it never blocks, it reports.
"""

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class Criterion:
    """One evaluated criterion of the verdict."""

    name: str
    ok: bool
    detail: str


@dataclass
class Verdict:
    """Criterion-by-criterion go/no-go decision."""

    go: bool
    criteria: list[Criterion] = field(default_factory=list)
    holdout_attempts: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "go": self.go,
            "holdout_attempts": self.holdout_attempts,
            "criteria": [
                {"name": c.name, "ok": c.ok, "detail": c.detail} for c in self.criteria
            ],
        }


DEFAULT_THRESHOLDS = {
    "min_trades_oos": 300,
    "min_t_stat": 2.0,
    "min_profit_factor": 1.2,
    "min_pct_positive_folds": 0.7,
    "max_drawdown": 0.25,
}


def _num(metrics: dict[str, float | int | None], key: str) -> float | None:
    value = metrics.get(key)
    return float(value) if value is not None else None


def go_no_go(
    metrics: dict[str, float | int | None],
    *,
    stress_ok: bool | None,
    pct_positive_folds: float | None,
    holdout_attempts: int | None,
    thresholds: dict[str, float] | None = None,
) -> Verdict:
    """Evaluate every criterion; GO only if all pass. Missing inputs fail."""
    t = thresholds or DEFAULT_THRESHOLDS
    n_trades = metrics.get("n_trades")
    expectancy = _num(metrics, "expectancy_bps")
    t_stat = _num(metrics, "t_stat")
    profit_factor = _num(metrics, "profit_factor")
    drawdown = _num(metrics, "max_drawdown")

    criteria: list[Criterion] = []

    def add(name: str, ok: bool | None, detail: str) -> None:
        criteria.append(Criterion(name=name, ok=ok is True, detail=detail))

    if n_trades is None:
        add("trades_oos", False, "n_trades missing")
    else:
        add(
            "trades_oos",
            float(n_trades) >= t["min_trades_oos"],
            f"{n_trades} trades (min {int(t['min_trades_oos'])})",
        )
    if expectancy is None:
        add("expectancy", False, "expectancy_bps missing")
    else:
        add("expectancy", expectancy > 0, f"{expectancy:.4f} bps net per trade")
    if t_stat is None:
        add("t_stat", False, "t-stat missing")
    else:
        add("t_stat", t_stat >= t["min_t_stat"], f"t={t_stat:.2f} (min {t['min_t_stat']})")
    if profit_factor is None:
        add("profit_factor", False, "profit_factor missing")
    else:
        add(
            "profit_factor",
            profit_factor >= t["min_profit_factor"],
            f"PF={profit_factor:.2f} (min {t['min_profit_factor']})",
        )
    if drawdown is None:
        add("drawdown", False, "max_drawdown missing")
    else:
        add(
            "drawdown",
            drawdown <= t["max_drawdown"],
            f"DD={drawdown * 100:.1f}% (max {t['max_drawdown'] * 100:.0f}%)",
        )
    if stress_ok is None:
        add("stress", False, "stress not evaluated")
    else:
        detail = "survived degraded costs" if stress_ok else "did not survive stress"
        add("stress", stress_ok, detail)
    if pct_positive_folds is None:
        add("folds", False, "walk-forward not evaluated")
    else:
        add(
            "folds",
            pct_positive_folds >= t["min_pct_positive_folds"],
            f"{pct_positive_folds * 100:.0f}% folds positive"
            f" (min {t['min_pct_positive_folds'] * 100:.0f}%)",
        )

    go = all(c.ok for c in criteria)
    return Verdict(go=go, criteria=criteria, holdout_attempts=holdout_attempts)


def read_holdout_attempts(path: Path) -> int:
    """Read the persistent holdout attempts counter (0 when absent/corrupt)."""
    if not path.is_file():
        return 0
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return int(raw.get("count", 0))
    except (json.JSONDecodeError, ValueError, AttributeError):
        return 0


def register_holdout_attempt(path: Path) -> int:
    """Increment the holdout attempts counter; repair the file if corrupted."""
    count = read_holdout_attempts(path) + 1
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps({"count": count, "note": "runs touching the locked holdout period"}),
        encoding="utf-8",
    )
    tmp.replace(path)
    return count


def register_if_touches(
    run_period: tuple[date, date],
    holdout_period: tuple[date, date],
    path: Path,
) -> int:
    """Increment the counter only when the run period intersects the holdout."""
    run_start, run_end = run_period
    hold_start, hold_end = holdout_period
    if run_start <= hold_end and run_end >= hold_start:
        return register_holdout_attempt(path)
    return read_holdout_attempts(path)
