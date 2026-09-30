"""Standalone HTML report rendering (SVG inline, no external resources)."""

import json
from pathlib import Path

import polars as pl
import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

_TEMPLATE_DIR = Path(__file__).parent / "templates"

_ENV = Environment(
    loader=FileSystemLoader(_TEMPLATE_DIR),
    autoescape=select_autoescape(("html", "xml")),
)


def _svg_path(
    values: list[float], width: int = 800, height: int = 200, color: str = "#2563eb"
) -> str:
    """SVG polyline of a value series, scaled to the box."""
    if len(values) < 2:
        return ""
    lo, hi = min(values), max(values)
    span = hi - lo if hi > lo else 1.0
    step_x = width / (len(values) - 1)
    points = [
        f"{i * step_x:.1f},{height - (v - lo) / span * (height - 10) - 5:.1f}"
        for i, v in enumerate(values)
    ]
    return (
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
        f'width="100%" preserveAspectRatio="none">'
        f'<polyline fill="none" stroke="{color}" stroke-width="1.5" points="{" ".join(points)}"/>'
        f"</svg>"
    )


def _svg_drawdown(equity: list[float], width: int = 800, height: int = 120) -> str:
    """SVG area of the drawdown from the running peak."""
    if len(equity) < 2:
        return ""
    peak = equity[0]
    dds: list[float] = []
    for value in equity:
        peak = max(peak, value)
        dds.append((peak - value) / peak if peak > 0 else 0.0)
    hi = max(dds) if max(dds) > 0 else 1.0
    step_x = width / (len(dds) - 1)
    top = " ".join(
        f"{i * step_x:.1f},{height - dd / hi * (height - 10) - 5:.1f}" for i, dd in enumerate(dds)
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
        f'width="100%" preserveAspectRatio="none">'
        f'<polygon fill="rgba(220,38,38,0.35)" stroke="#dc2626" stroke-width="1" '
        f'points="0,{height} {top} {width},{height}"/></svg>'
    )


def _svg_histogram(pnls: list[float], width: int = 800, height: int = 160) -> str:
    """SVG bar histogram of per-trade net PnL."""
    if not pnls:
        return ""
    lo, hi = min(pnls), max(pnls)
    if hi == lo:
        hi = lo + 1.0
    bins = 20
    counts = [0] * bins
    for pnl in pnls:
        idx = int((pnl - lo) / (hi - lo) * bins)
        counts[min(idx, bins - 1)] += 1
    max_count = max(counts) or 1
    bar_w = width / bins
    bars = []
    for i, count in enumerate(counts):
        h = count / max_count * (height - 10)
        bars.append(
            f'<rect x="{i * bar_w + 1:.1f}" y="{height - h:.1f}" width="{bar_w - 2:.1f}" '
            f'height="{h:.1f}" fill="#2563eb"/>'
        )
    return (
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
        f'width="100%" preserveAspectRatio="none">{"".join(bars)}</svg>'
    )


def _fmt(value: float | None, suffix: str = "") -> str:
    if value is None:
        return "n/a"
    return f"{value:.4f}{suffix}"


def render_report(run_dir: Path) -> Path:
    """Render the standalone report.html inside a run directory."""
    config = yaml.safe_load((run_dir / "config.yaml").read_text(encoding="utf-8"))
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    trades_path = run_dir / "trades.csv"
    equity_path = run_dir / "equity.csv"
    trades = pl.read_csv(trades_path) if trades_path.is_file() else pl.DataFrame()
    equity_df = pl.read_csv(equity_path) if equity_path.is_file() else pl.DataFrame()

    equity = equity_df["equity"].to_list() if equity_df.height else []
    pnls: list[float] = []
    if trades.height and "realized_gross" in trades.columns:
        closed = trades.filter(trades["realized_gross"] != 0.0)
        pnls = closed["realized_gross"].to_list()

    data = config.get("data", {})
    strategy = config.get("strategy", {})
    html = _ENV.get_template("report.html.j2").render(
        strategy_name=strategy.get("name", "?"),
        params=strategy.get("params", {}),
        symbol=data.get("symbol", "?"),
        market=data.get("market", "?"),
        period=f"{data.get('start', '?')} -> {data.get('end', '?')}",
        interval=data.get("interval", "?"),
        n_bars=summary.get("n_bars", 0),
        n_fills=summary.get("n_fills", 0),
        final_equity=_fmt(summary.get("final_equity")),
        metrics=metrics,
        fmt=_fmt,
        svg_equity=_svg_path(equity),
        svg_drawdown=_svg_drawdown(equity),
        svg_hist=_svg_histogram(pnls),
        has_trades=metrics.get("n_trades", 0) > 0,
    )
    path = run_dir / "report.html"
    path.write_text(html, encoding="utf-8")
    return path
