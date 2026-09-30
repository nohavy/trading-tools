"""Parameter grid sweep: parallel full backtests ranked by net expectancy."""

import json
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import product
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

from tradingv2.backtest.runner import run_backtest

_TEMPLATE_DIR = Path(__file__).parent.parent / "report" / "templates"
_ENV = Environment(
    loader=FileSystemLoader(_TEMPLATE_DIR), autoescape=select_autoescape(("html", "xml"))
)


@dataclass(frozen=True)
class SweepEntry:
    """Result of one grid combination."""

    params: dict[str, float | int]
    run_dir: Path
    expectancy_bps: float | None
    n_trades: int
    few_trades: bool
    sharpe: float | None
    net_total: float | None


@dataclass
class SweepResult:
    """Ranked sweep results + HTML report path."""

    entries: list[SweepEntry]
    html_path: Path


def parse_grid(grid_str: str) -> dict[str, list[float | int]]:
    """Parse 'param=lo..hi:step' ranges or 'param=a,b,c' lists."""
    import re

    out: dict[str, list[float | int]] = {}
    if not grid_str:
        return out
    # split on commas that are followed by a new 'key=' section
    sections = re.split(r",(?=\s*[A-Za-z_]\w*\s*=)", grid_str)
    for part in sections:
        if "=" not in part:
            raise ValueError(f"invalid grid entry '{part}': expected 'param=...'")
        key, values_str = part.split("=", 1)
        key = key.strip()
        values: list[float | int]
        if ".." in values_str:
            if ":" not in values_str:
                raise ValueError(f"invalid grid range '{values_str}': expected 'lo..hi:step'")
            lo_str, rest = values_str.split("..", 1)
            hi_str, step_str = rest.split(":", 1)
            is_int = all("." not in s for s in (lo_str, hi_str, step_str))
            lo, hi, step = float(lo_str), float(hi_str), float(step_str)
            if step <= 0:
                raise ValueError(f"invalid grid step in '{values_str}'")
            values = []
            x = lo
            while x <= hi + 1e-9:
                values.append(int(round(x)) if is_int else x)
                x += step
        else:
            is_int = all("." not in s for s in values_str.split(","))
            try:
                values = [
                    int(s) if is_int else float(s) for s in values_str.split(",") if s.strip()
                ]
            except ValueError as exc:
                raise ValueError(f"invalid grid values for '{key}': {exc}") from exc
        if not values:
            raise ValueError(f"empty grid values for '{key}'")
        out[key] = values
    return out


def _run_one(
    index: int,
    combo: tuple[float | int, ...],
    param_names: list[str],
    base_config: dict[str, object],
    data_root: str,
    runs_root: str,
    min_trades: int,
    bar_bounds: tuple[int, int] | None,
) -> SweepEntry:
    params: dict[str, float | int] = dict(zip(param_names, combo, strict=True))
    variant = yaml.safe_load(yaml.safe_dump(base_config))  # deep copy, dates preserved
    variant["strategy"]["params"].update(params)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    config_path = Path(runs_root) / f".sweep-config-{stamp}-{index}.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump(variant), encoding="utf-8")
    run_dir = run_backtest(
        config_path, data_root=Path(data_root), runs_root=Path(runs_root), bar_bounds=bar_bounds
    )
    config_path.unlink()
    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    return SweepEntry(
        params=params,
        run_dir=run_dir,
        expectancy_bps=metrics["expectancy_bps"],
        n_trades=metrics["n_trades"],
        few_trades=metrics["n_trades"] < min_trades,
        sharpe=metrics["sharpe"],
        net_total=metrics["net_total"],
    )


def _color(expectancy: float | None, entries: list[SweepEntry]) -> str:
    """Cell background: red (worst) to green (best) on the sweep range."""
    values = [e.expectancy_bps for e in entries if e.expectancy_bps is not None]
    if expectancy is None or not values:
        return ""
    lo, hi = min(values), max(values)
    if hi <= lo:
        return "background:#d1d5db"
    frac = (expectancy - lo) / (hi - lo)
    red, green = int(220 * (1 - frac)), int(160 * frac + 60)
    return f"background:rgb({red},{green},{min(red, green) // 2})"


def sweep_grid(
    config_path: Path,
    grid: dict[str, list[float | int]],
    *,
    data_root: Path,
    runs_root: Path,
    workers: int = 1,
    min_trades: int = 30,
    bar_bounds: tuple[int, int] | None = None,
) -> SweepResult:
    """Run every grid combination as a full backtest, rank by net expectancy.

    Deterministic: results are collected in grid order (never completion order).
    """
    base_config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    param_names = list(grid.keys())
    combos = list(product(*[grid[key] for key in param_names]))
    runs_root.mkdir(parents=True, exist_ok=True)
    args = [
        (i, combo, param_names, base_config, str(data_root), str(runs_root), min_trades, bar_bounds)
        for i, combo in enumerate(combos)
    ]
    if workers <= 1:
        entries = [_run_one(*a) for a in args]
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            columns = list(zip(*args, strict=True))
            entries = list(pool.map(_run_one, *columns))
    entries.sort(
        key=lambda e: -(e.expectancy_bps if e.expectancy_bps is not None else float("-inf"))
    )
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    html_path = runs_root / f"sweep-{stamp}.html"
    rows = [
        {
            "params": ", ".join(f"{k}={v}" for k, v in entry.params.items()),
            "expectancy": (
                f"{entry.expectancy_bps:.2f}" if entry.expectancy_bps is not None else "n/a"
            ),
            "color": _color(entry.expectancy_bps, entries),
            "n_trades": entry.n_trades,
            "few_trades": entry.few_trades,
            "sharpe": f"{entry.sharpe:.2f}" if entry.sharpe is not None else "n/a",
            "net_total": f"{entry.net_total:.4f}" if entry.net_total is not None else "n/a",
        }
        for entry in entries
    ]
    html = _ENV.get_template("sweep.html.j2").render(rows=rows, n=len(entries))
    html_path.write_text(html, encoding="utf-8")
    return SweepResult(entries=entries, html_path=html_path)
