"""Tests for download plan construction (monthly vs daily)."""

from datetime import date

import pytest

from tradingv2.config import DataKind, Market
from tradingv2.data.plan import build_download_plan

TODAY = date(2026, 9, 30)


def test_single_complete_elapsed_month_is_monthly() -> None:
    plan = build_download_plan(
        Market.SPOT, DataKind.KLINES, "BTCUSDT", "1s", date(2026, 8, 1), date(2026, 8, 31), TODAY
    )
    assert len(plan) == 1
    item = plan[0]
    assert item.is_monthly
    assert item.stem == "BTCUSDT-1s-2026-08"
    assert item.url == "https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1s/BTCUSDT-1s-2026-08.zip"
    assert item.checksum_url == item.url + ".CHECKSUM"


def test_elapsed_partial_range_uses_monthly_for_start_month_too() -> None:
    # June 15 -> August 20, today September 30: all three months are fully elapsed.
    plan = build_download_plan(
        Market.SPOT, DataKind.KLINES, "BTCUSDT", "1s", date(2026, 6, 15), date(2026, 8, 20), TODAY
    )
    assert [item.stem for item in plan] == [
        "BTCUSDT-1s-2026-06",
        "BTCUSDT-1s-2026-07",
        "BTCUSDT-1s-2026-08",
    ]
    assert all(item.is_monthly for item in plan)


def test_current_month_falls_back_to_daily() -> None:
    plan = build_download_plan(
        Market.SPOT, DataKind.KLINES, "BTCUSDT", "1s", date(2026, 9, 26), date(2026, 9, 28), TODAY
    )
    stems = [item.stem for item in plan]
    assert stems == ["BTCUSDT-1s-2026-09-26", "BTCUSDT-1s-2026-09-27", "BTCUSDT-1s-2026-09-28"]
    assert not any(item.is_monthly for item in plan)


def test_mixed_plan_monthly_then_daily() -> None:
    plan = build_download_plan(
        Market.SPOT, DataKind.KLINES, "BTCUSDT", "1s", date(2026, 7, 15), date(2026, 9, 1), TODAY
    )
    stems = [item.stem for item in plan]
    assert stems == ["BTCUSDT-1s-2026-07", "BTCUSDT-1s-2026-08", "BTCUSDT-1s-2026-09-01"]
    assert [item.is_monthly for item in plan] == [True, True, False]


def test_future_days_are_skipped() -> None:
    plan = build_download_plan(
        Market.SPOT, DataKind.KLINES, "BTCUSDT", "1s", date(2026, 9, 29), date(2026, 10, 5), TODAY
    )
    assert [item.stem for item in plan] == ["BTCUSDT-1s-2026-09-29", "BTCUSDT-1s-2026-09-30"]


def test_funding_rate_only_for_elapsed_months() -> None:
    plan = build_download_plan(
        Market.UM,
        DataKind.FUNDING_RATE,
        "BTCUSDT",
        None,
        date(2026, 8, 1),
        date(2026, 9, 30),
        TODAY,
    )
    assert [item.stem for item in plan] == ["BTCUSDT-fundingRate-2026-08"]


def test_end_before_start_rejected() -> None:
    with pytest.raises(ValueError, match="start"):
        build_download_plan(
            Market.SPOT,
            DataKind.KLINES,
            "BTCUSDT",
            "1s",
            date(2026, 8, 10),
            date(2026, 8, 1),
            TODAY,
        )


def test_aggtrades_plan_golden_url() -> None:
    plan = build_download_plan(
        Market.UM, DataKind.AGGTRADES, "BTCUSDT", None, date(2026, 9, 26), date(2026, 9, 26), TODAY
    )
    assert plan[0].url == (
        "https://data.binance.vision/data/futures/um/daily/aggTrades/BTCUSDT/BTCUSDT-aggTrades-2026-09-26.zip"
    )
