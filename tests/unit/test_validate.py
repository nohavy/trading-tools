"""Tests for the go/no-go verdict and the holdout attempts counter."""

import json
from datetime import date
from pathlib import Path

import pytest

from tradingv2.backtest.validate import (
    Verdict,
    go_no_go,
    read_holdout_attempts,
    register_holdout_attempt,
    register_if_touches,
)

GOOD_METRICS = {
    "n_trades": 350,
    "expectancy_bps": 1.5,
    "t_stat": 2.5,
    "profit_factor": 1.4,
    "max_drawdown": 0.10,
}


def test_go_when_all_criteria_pass() -> None:
    verdict = go_no_go(GOOD_METRICS, stress_ok=True, pct_positive_folds=0.8, holdout_attempts=2)
    assert verdict.go is True
    assert all(c.ok for c in verdict.criteria)
    assert len(verdict.criteria) == 7
    assert verdict.holdout_attempts == 2


@pytest.mark.parametrize(
    ("metrics", "field"),
    [
        ({**GOOD_METRICS, "n_trades": 299}, "trades_oos"),
        ({**GOOD_METRICS, "expectancy_bps": -0.1}, "expectancy"),
        ({**GOOD_METRICS, "t_stat": 1.5}, "t_stat"),
        ({**GOOD_METRICS, "profit_factor": 1.1}, "profit_factor"),
        ({**GOOD_METRICS, "max_drawdown": 0.3}, "drawdown"),
    ],
)
def test_no_go_per_failing_metric(metrics: dict[str, float | int], field: str) -> None:
    verdict = go_no_go(metrics, stress_ok=True, pct_positive_folds=0.8, holdout_attempts=1)
    assert verdict.go is False
    failed = [c for c in verdict.criteria if not c.ok]
    assert len(failed) == 1
    assert failed[0].name == field


def test_no_go_when_stress_fails() -> None:
    verdict = go_no_go(GOOD_METRICS, stress_ok=False, pct_positive_folds=0.8, holdout_attempts=1)
    assert verdict.go is False
    failed = [c.name for c in verdict.criteria if not c.ok]
    assert failed == ["stress"]


def test_no_go_when_folds_fail() -> None:
    verdict = go_no_go(GOOD_METRICS, stress_ok=True, pct_positive_folds=0.5, holdout_attempts=1)
    failed = [c.name for c in verdict.criteria if not c.ok]
    assert failed == ["folds"]


def test_missing_inputs_fail_with_detail() -> None:
    verdict = go_no_go(GOOD_METRICS, stress_ok=None, pct_positive_folds=None, holdout_attempts=None)
    assert verdict.go is False
    failed = {c.name for c in verdict.criteria if not c.ok}
    assert failed == {"stress", "folds"}


def test_verdict_is_json_serializable() -> None:
    verdict = go_no_go(GOOD_METRICS, stress_ok=True, pct_positive_folds=0.8, holdout_attempts=3)
    raw = verdict.to_dict()
    json.dumps(raw)
    assert raw["go"] is True


def test_holdout_counter_persistent(tmp_path: Path) -> None:
    path = tmp_path / "attempts.json"
    assert read_holdout_attempts(path) == 0
    assert register_holdout_attempt(path) == 1
    assert register_holdout_attempt(path) == 2
    assert read_holdout_attempts(path) == 2


def test_holdout_counter_repaired_on_corruption(tmp_path: Path) -> None:
    path = tmp_path / "attempts.json"
    path.write_text("corrupted{", encoding="utf-8")
    assert read_holdout_attempts(path) == 0
    assert register_holdout_attempt(path) == 1


def test_register_only_when_touching_holdout(tmp_path: Path) -> None:
    path = tmp_path / "attempts.json"
    holdout = (date(2026, 9, 1), date(2026, 9, 30))
    assert register_if_touches((date(2026, 8, 1), date(2026, 8, 31)), holdout, path) == 0
    assert register_if_touches((date(2026, 9, 5), date(2026, 9, 10)), holdout, path) == 1
    assert register_if_touches((date(2026, 8, 15), date(2026, 9, 2)), holdout, path) == 2
    assert register_if_touches((date(2026, 10, 1), date(2026, 10, 5)), holdout, path) == 2


def test_verdict_type() -> None:
    verdict = go_no_go(GOOD_METRICS, stress_ok=True, pct_positive_folds=0.8, holdout_attempts=0)
    assert isinstance(verdict, Verdict)
