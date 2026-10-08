"""Render a paper session's persisted state as a standalone HTML report."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_ENV = Environment(
    loader=FileSystemLoader(_TEMPLATE_DIR), autoescape=select_autoescape(("html", "xml"))
)


def _fmt_ts(ns: int) -> str:
    if not ns:
        return "—"
    return datetime.fromtimestamp(ns / 1e9, tz=UTC).strftime("%Y-%m-%d %H:%M")


def render_paper_state(state_dir: Path) -> Path:
    """Render state.json into paper_report.html next to it."""
    state: dict[str, Any] = json.loads((state_dir / "state.json").read_text(encoding="utf-8"))
    rows: list[dict[str, str]] = []
    for name, leg in state["legs"].items():
        kind = leg.get("kind", "?")
        if kind == "spot":
            balance = leg.get("base_balance", 0.0)
            position = balance  # long only
        else:
            position = leg.get("position", 0.0)
            balance = leg.get("balance")
        rows.append(
            {
                "name": name,
                "kind": kind,
                "balance": f"{balance:,.2f}" if isinstance(balance, (int, float)) else "—",
                "position": f"{position:+.8f}",
                "entry_price": (
                    f"{leg['entry_price']:,.2f}" if leg.get("entry_price") else "—"
                ),
                "equity": f"{leg.get('equity', 0.0):,.2f}",
                "last_close": _fmt_ts(int(leg.get("last_close_ns", 0))),
                "last_funding": _fmt_ts(int(leg.get("last_funding_ns", 0))),
                "n_bars": str(leg.get("n_bars", 0)),
            }
        )
    equity_curves: dict[str, list[float]] = {
        name: [float(mark[1]) for mark in leg_state.get("equity_curve", [])]
        for name, leg_state in state["legs"].items()
    }
    html_path = state_dir / "paper_report.html"
    html_path.write_text(
        _ENV.get_template("paper_state.html.j2").render(
            rows=rows,
            generated=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
            curves=equity_curves,
        ),
        encoding="utf-8",
    )
    return html_path
