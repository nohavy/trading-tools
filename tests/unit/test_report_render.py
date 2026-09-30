"""Smoke tests for the standalone HTML report."""

import json
from pathlib import Path

import polars as pl

from tradingv2.report.render import render_report

S = 1_000_000_000


def build_run(tmp_path: Path, *, with_trades: bool = True) -> Path:
    run_dir = tmp_path / "run-001"
    run_dir.mkdir(parents=True)
    (run_dir / "config.yaml").write_text(
        json.dumps(
            {
                "data": {"market": "um", "kind": "klines", "symbol": "BTCUSDT", "interval": "1s",
                          "start": "2026-08-01", "end": "2026-08-01", "tape": "aggTrades"},
                "account": {"type": "margin", "balance": 1000, "leverage": 5, "mmr": 0.004},
                "costs": {"maker_bps": 2, "taker_bps": 5, "slippage_bps": 0.5,
                          "latency": {"mean_ms": 150, "jitter_ms": 50, "seed": 42}},
                "strategy": {"name": "meanrev_zscore", "params": {"window": 120}},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "summary.json").write_text(
        json.dumps({"n_bars": 10, "n_fills": 2, "final_equity": 1004.97}), encoding="utf-8"
    )
    trades = pl.DataFrame(
        {
            "ts_ns": [1 * S, 5 * S],
            "order_id": [1, 2],
            "side": ["buy", "sell"],
            "price": [5000.0, 5010.0],
            "qty": [0.002, 0.002],
            "fee": [0.5, 0.5],
            "role": ["taker", "taker"],
            "realized_gross": [0.0, 0.02],
            "slippage_cost": [0.0, 0.01],
        }
    )
    trades.write_csv(run_dir / "trades.csv")
    equity = pl.DataFrame(
        {
            "ts_ns": [(i + 1) * S for i in range(10)],
            "equity": [1000.0 + 0.5 * i for i in range(10)],
        }
    )
    equity.write_csv(run_dir / "equity.csv")
    metrics = {
        "n_bars": 10,
        "total_return": 0.00497,
        "max_drawdown": 0.0,
        "calmar": None,
        "sharpe": 4.2,
        "sortino": 5.1,
        "n_trades": 1 if with_trades else 0,
        "win_rate": 1.0 if with_trades else None,
        "avg_win": 0.01 if with_trades else None,
        "avg_loss": None,
        "payoff": None,
        "profit_factor": None,
        "expectancy_bps": 9.94 if with_trades else None,
        "avg_hold_ns": 4 * S if with_trades else None,
        "gross_total": 0.02 if with_trades else None,
        "fees_total": 1.0 if with_trades else None,
        "slippage_total": 0.01 if with_trades else None,
        "funding_total": 0.0 if with_trades else None,
        "net_total": -0.99 if with_trades else None,
        "fee_drag": 50.0 if with_trades else None,
        "t_stat": None,
    }
    (run_dir / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    return run_dir


def test_report_generated_autonomous_and_small(tmp_path: Path) -> None:
    run_dir = build_run(tmp_path)
    report = render_report(run_dir)
    assert report == run_dir / "report.html"
    content = report.read_text(encoding="utf-8")
    assert len(content.encode("utf-8")) < 2_000_000
    assert 'src="http' not in content
    assert 'href="http' not in content
    assert 'link rel="stylesheet"' not in content


def test_report_sections_present(tmp_path: Path) -> None:
    run_dir = build_run(tmp_path)
    content = (render_report(run_dir)).read_text(encoding="utf-8")
    assert "Équité" in content
    assert "Drawdown" in content
    assert "Métriques" in content
    assert "Coûts" in content
    assert "meanrev_zscore" in content
    assert "BTCUSDT" in content
    assert "<svg" in content  # inline charts, no external JS


def test_report_is_deterministic(tmp_path: Path) -> None:
    run_dir = build_run(tmp_path)
    first = render_report(run_dir).read_bytes()
    second = render_report(run_dir).read_bytes()
    assert first == second


def test_report_zero_trades_note(tmp_path: Path) -> None:
    run_dir = build_run(tmp_path, with_trades=False)
    content = render_report(run_dir).read_text(encoding="utf-8")
    assert "Aucun trade" in content
