"""Parity property tests: vectorized (lot) == incremental (step), the live contract."""

import polars as pl
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tradingv2.features.incremental import (
    EmaIncr,
    FlowImbalanceIncr,
    RealizedVolIncr,
    VwapIncr,
    ZScoreIncr,
)
from tradingv2.features.vectorized import (
    ema,
    flow_imbalance,
    realized_vol,
    vwap_session,
    zscore,
)

TOL = 1e-9


def same(a: float | None, b: float | None, scale: float = 1.0) -> bool:
    """Loose equality treating NaN and None as the same 'undefined' state."""
    a_undef = a is None or a != a
    b_undef = b is None or b != b
    if a_undef or b_undef:
        return a_undef == b_undef
    assert a is not None and b is not None
    # absolute tolerance with relative tail: near-zero values (z-score around
    # 0) amplify summation-order noise, so pure relative would be meaningless
    del scale
    return abs(a - b) <= TOL * max(1.0, abs(a))


floats = st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_subnormal=False)
positive_floats = st.floats(min_value=0.0, max_value=1e6, allow_nan=False, allow_subnormal=False)


@settings(max_examples=60)
@given(values=st.lists(floats, min_size=1, max_size=120))
def test_ema_parity_random(values: list[float]) -> None:
    lot = ema(pl.Series(values), span=5).to_list()
    incr = EmaIncr(span=5)
    for i, x in enumerate(values):
        assert same(lot[i], incr.update(x)), f"index {i}"


@settings(max_examples=40)
@given(
    values=st.lists(floats, min_size=2, max_size=80),
    window=st.integers(min_value=2, max_value=10),
)
def test_zscore_parity_random(values: list[float], window: int) -> None:
    lot = zscore(pl.Series(values), window=window).to_list()
    incr = ZScoreIncr(window=window)
    for i, x in enumerate(values):
        assert same(lot[i], incr.update(x), scale=abs(x)), f"index {i}"


@settings(max_examples=40)
@given(
    values=st.lists(
        st.floats(min_value=1.0, max_value=1e5, allow_nan=False), min_size=3, max_size=80
    ),
    window=st.integers(min_value=2, max_value=10),
)
def test_realized_vol_parity_random(values: list[float], window: int) -> None:
    lot = realized_vol(pl.Series(values), window=window).to_list()
    incr = RealizedVolIncr(window=window)
    for i, x in enumerate(values):
        assert same(lot[i], incr.update(x), scale=x), f"index {i}"


@settings(max_examples=40)
@given(
    ts=st.lists(
        st.integers(min_value=0, max_value=10**15),
        min_size=4,
        max_size=60,
    ),
    prices=st.lists(
        st.floats(min_value=1.0, max_value=1e5, allow_nan=False), min_size=60, max_size=60
    ),
    volumes=st.lists(positive_floats, min_size=60, max_size=60),
)
def test_vwap_parity_random(ts: list[int], prices: list[float], volumes: list[float]) -> None:
    ordered_ts = sorted(ts)
    n = len(ordered_ts)
    prices, volumes = prices[:n], volumes[:n]
    lot = vwap_session(
        pl.Series(ordered_ts, dtype=pl.Int64), pl.Series(prices), pl.Series(volumes)
    ).to_list()
    incr = VwapIncr()
    for i, t in enumerate(ordered_ts):
        assert same(lot[i], incr.update(t, prices[i], volumes[i])), f"index {i}"


@settings(max_examples=40)
@given(
    volumes=st.lists(positive_floats, min_size=4, max_size=60),
    taker_buy=st.lists(
        st.floats(min_value=0.0, max_value=1e6, allow_nan=False), min_size=60, max_size=60
    ),
    window=st.integers(min_value=2, max_value=8),
)
def test_flow_parity_random(
    volumes: list[float], taker_buy: list[float], window: int
) -> None:
    n = min(len(volumes), len(taker_buy))
    volumes, taker_buy = volumes[:n], taker_buy[:n]
    lot = flow_imbalance(pl.Series(volumes), pl.Series(taker_buy), window=window).to_list()
    incr = FlowImbalanceIncr(window=window)
    for i in range(n):
        assert same(lot[i], incr.update(volumes[i], taker_buy[i])), f"index {i}"


def test_real_month_parity_all_indicators() -> None:
    path = "data/parquet/spot/klines/BTCUSDT/1s/BTCUSDT-1s-2026-08.parquet"
    try:
        df = pl.read_parquet(path)
    except Exception:
        pytest.skip("august 2026 data not downloaded yet")
    df = df[::100]  # subsample for speed; parity math is unchanged
    close = df["close"]
    volume = df["volume"]
    taker_buy = df["taker_buy_volume"]
    ts = df["ts_open_ns"]

    checks = [
        (ema(close, span=120).to_list(), _incr_ema(close.to_list(), 120)),
        (zscore(close, window=300).to_list(), _incr_zscore(close.to_list(), 300)),
        (realized_vol(close, window=300).to_list(), _incr_vol(close.to_list(), 300)),
        (
            vwap_session(ts, close, volume).to_list(),
            _incr_vwap(ts.to_list(), close.to_list(), volume.to_list()),
        ),
        (
            flow_imbalance(volume, taker_buy, window=120).to_list(),
            _incr_flow(volume.to_list(), taker_buy.to_list(), 120),
        ),
    ]
    for lot, step in checks:
        assert len(lot) == len(step)
        mismatches = sum(0 if same(a, b) else 1 for a, b in zip(lot, step, strict=True))
        assert mismatches == 0


def _incr_ema(values: list[float], span: int) -> list[float | None]:
    incr = EmaIncr(span=span)
    return [incr.update(x) for x in values]


def _incr_zscore(values: list[float], window: int) -> list[float | None]:
    incr = ZScoreIncr(window=window)
    return [incr.update(x) for x in values]


def _incr_vol(values: list[float], window: int) -> list[float | None]:
    incr = RealizedVolIncr(window=window)
    return [incr.update(x) for x in values]


def _incr_vwap(ts: list[int], prices: list[float], volumes: list[float]) -> list[float | None]:
    incr = VwapIncr()
    return [incr.update(t, p, v) for t, p, v in zip(ts, prices, volumes, strict=True)]


def _incr_flow(volumes: list[float], taker_buy: list[float], window: int) -> list[float | None]:
    incr = FlowImbalanceIncr(window=window)
    return [incr.update(v, b) for v, b in zip(volumes, taker_buy, strict=True)]
