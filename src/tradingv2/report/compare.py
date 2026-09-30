"""Multi-run comparison: metrics table + standalone HTML."""

import json
from datetime import UTC, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from tradingv2.report.render import _TEMPLATE_DIR  # shared template loader

_ENV = Environment(
    loader=FileSystemLoader(_TEMPLATE_DIR),
    autoescape=select_autoescape(("html", "xml")),
)

# display order and French labels of compared metrics
_ROWS: list[tuple[str, str]] = [
    ("total_return", "Rendement total"),
    ("sharpe", "Sharpe"),
    ("sortino", "Sortino"),
    ("max_drawdown", "Drawdown max"),
    ("calmar", "Calmar"),
    ("t_stat", "t-stat espérance"),
    ("n_trades", "Trades"),
    ("win_rate", "Taux de réussite"),
    ("payoff", "Payoff"),
    ("profit_factor", "Profit factor"),
    ("expectancy_bps", "Espérance (bps)"),
    ("gross_total", "Brut"),
    ("fees_total", "Frais"),
    ("slippage_total", "Slippage"),
    ("funding_total", "Funding"),
    ("net_total", "Net"),
    ("fee_drag", "Drag des frais"),
]


def _fmt(value: object) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def comparison_table(run_dirs: list[Path]) -> dict[str, list[str]]:
    """Rows of metrics side by side: {metric: [value_run1, value_run2, ...]}."""
    reports = []
    names = []
    for run_dir in run_dirs:
        metrics_path = run_dir / "metrics.json"
        reports.append(json.loads(metrics_path.read_text(encoding="utf-8")))
        names.append(run_dir.name)
    del names
    table: dict[str, list[str]] = {}
    for key, _label in _ROWS:
        table[key] = [_fmt(report.get(key)) for report in reports]
    return table


def compare_runs(run_dirs: list[Path], runs_root: Path) -> Path:
    """Write and return a comparison HTML (metrics side by side)."""
    reports = [json.loads((run / "metrics.json").read_text(encoding="utf-8")) for run in run_dirs]
    names = [run.name for run in run_dirs]
    rows = [
        {"label": label, "vals": [_fmt(report.get(key)) for report in reports]}
        for key, label in _ROWS
    ]
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    html = _ENV.get_template("compare.html.j2").render(names=names, rows=rows, n_runs=len(run_dirs))
    path = runs_root / f"compare-{stamp}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path
