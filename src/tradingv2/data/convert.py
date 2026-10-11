"""CSV parsing and timestamp normalization for Binance historical data."""

import io
import re
from collections.abc import Callable

import polars as pl

from tradingv2.config import Market

MS_IN_NS = 1_000_000
US_IN_NS = 1_000

_NS_THRESHOLD = 10**18
_US_THRESHOLD = 10**15
_MS_THRESHOLD = 10**12

KLINE_COLUMNS = (
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "count",
    "taker_buy_volume",
    "taker_buy_quote_volume",
    "ignore",
)

BAR_SCHEMA = {
    "ts_open_ns": pl.Int64,
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Float64,
    "quote_volume": pl.Float64,
    "n_trades": pl.UInt32,
    "taker_buy_volume": pl.Float64,
    "taker_buy_quote_volume": pl.Float64,
}

AGGTRADES_COLUMNS_SPOT = (
    "agg_trade_id",
    "price",
    "quantity",
    "first_trade_id",
    "last_trade_id",
    "transact_time",
    "is_buyer_maker",
    "is_best_match",
)

AGGTRADES_COLUMNS_UM = AGGTRADES_COLUMNS_SPOT[:-1]

TRADETICK_SCHEMA = {
    "ts_ns": pl.Int64,
    "price": pl.Float64,
    "qty": pl.Float64,
    "agg_id": pl.UInt64,
    "buyer_is_maker": pl.Boolean,
}

FUNDING_SCHEMA = {
    "ts_ns": pl.Int64,
    "interval_hours": pl.UInt32,
    "rate": pl.Float64,
}


class DataParseError(Exception):
    """Raised when a source CSV row or file cannot be parsed."""


class TimestampScaleError(DataParseError):
    """Raised when a raw timestamp magnitude is out of the plausible range."""


def normalize_ts(raw: int) -> int:
    """Normalize a raw timestamp to UTC nanoseconds by magnitude detection."""
    if raw < 0:
        raise TimestampScaleError(f"negative timestamp: {raw}")
    if raw >= _NS_THRESHOLD:
        return raw
    if raw >= _US_THRESHOLD:
        return raw * US_IN_NS
    if raw >= _MS_THRESHOLD:
        return raw * MS_IN_NS
    raise TimestampScaleError(f"timestamp magnitude out of range: {raw}")


_INTERVAL_UNITS_NS = {"s": 1_000_000_000, "m": 60_000_000_000, "h": 3_600_000_000_000}
_INTERVAL_RE = re.compile(r"^(\d+)([smh])$")


def parse_interval_ns(interval: str) -> int:
    """Parse a Binance-style interval ('1s', '5s', '1m', '15m', '1h') to nanoseconds."""
    match = _INTERVAL_RE.match(interval)
    if match is None:
        raise ValueError(f"invalid interval '{interval}': expected '<n><unit>' with unit in s/m/h")
    value = int(match.group(1))
    if value <= 0:
        raise ValueError(f"invalid interval '{interval}': value must be positive")
    return value * _INTERVAL_UNITS_NS[match.group(2)]


def _is_int(text: str) -> bool:
    try:
        int(text)
    except ValueError:
        return False
    return True


def _is_float(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def _looks_like_kline_header(first_line: str) -> bool:
    parts = first_line.split(",")
    return len(parts) == len(KLINE_COLUMNS) and parts[0] == "open_time"


def _split_header_body(lines: list[str], is_header: Callable[[str], bool]) -> tuple[list[str], int]:
    """Split CSV lines into (body, first_body_line_no), skipping a header row if present."""
    header_present = is_header(lines[0])
    body = lines[1:] if header_present else lines
    return body, (2 if header_present else 1)


def parse_klines_csv(data: bytes, file: str = "<input>") -> pl.DataFrame:
    """Parse Binance klines CSV bytes into the canonical Bar dataframe."""
    text = data.decode("utf-8")
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise DataParseError(f"{file}:1: empty file")

    body, first_line_no = _split_header_body(lines, _looks_like_kline_header)

    ts: list[int] = []
    floats: dict[str, list[float]] = {
        name: [] for name in BAR_SCHEMA if BAR_SCHEMA[name] == pl.Float64
    }
    trades: list[int] = []

    for offset, line in enumerate(body):
        line_no = first_line_no + offset
        parts = line.split(",")
        if len(parts) != len(KLINE_COLUMNS):
            raise DataParseError(f"{file}:{line_no}: expected 12 fields, got {len(parts)}")
        if not _is_int(parts[0]):
            raise DataParseError(f"{file}:{line_no}: bad open_time '{parts[0]}'")
        for idx, name in enumerate(
            (
                "open",
                "high",
                "low",
                "close",
                "volume",
                "quote_volume",
                "taker_buy_volume",
                "taker_buy_quote_volume",
            ),
            start=1,
        ):
            if not _is_float(parts[idx]):
                raise DataParseError(f"{file}:{line_no}: bad {name} '{parts[idx]}'")
        if not _is_int(parts[8]):
            raise DataParseError(f"{file}:{line_no}: bad count '{parts[8]}'")
        ts.append(normalize_ts(int(parts[0])))
        for name, idx in (
            ("open", 1),
            ("high", 2),
            ("low", 3),
            ("close", 4),
            ("volume", 5),
            ("quote_volume", 7),
            ("taker_buy_volume", 9),
            ("taker_buy_quote_volume", 10),
        ):
            floats[name].append(float(parts[idx]))
        trades.append(int(parts[8]))

    return pl.DataFrame(
        {
            "ts_open_ns": pl.Series(ts, dtype=pl.Int64),
            **{name: pl.Series(values, dtype=pl.Float64) for name, values in floats.items()},
            "n_trades": pl.Series(trades, dtype=pl.UInt32),
        },
        schema=BAR_SCHEMA,
    )


def _looks_like_aggtrades_header(first_line: str) -> bool:
    parts = first_line.split(",")
    return len(parts) > 0 and parts[0] == "agg_trade_id"


def _aggtrades_columns(market: Market) -> tuple[str, ...]:
    return AGGTRADES_COLUMNS_SPOT if market == Market.SPOT else AGGTRADES_COLUMNS_UM


def _normalize_ts_series(raw: pl.Series) -> pl.Series:
    """Normalize a whole integer timestamp series (one unit per file) to nanoseconds."""
    maximum = raw.max()
    if maximum is None:
        raise TimestampScaleError("empty timestamp series")
    # polars stubs widen max() to a wide union; the column is Int64 at runtime.
    max_int = int(maximum)  # type: ignore[arg-type]
    if max_int >= _NS_THRESHOLD:
        factor = 1
    elif max_int >= _US_THRESHOLD:
        factor = US_IN_NS
    elif max_int >= _MS_THRESHOLD:
        factor = MS_IN_NS
    else:
        raise TimestampScaleError(f"timestamp magnitude out of range: {max_int}")
    return (raw * factor).cast(pl.Int64)


def _first_bad_aggtrades_line(data: bytes, expected: int, header_present: bool) -> int:
    start_line = 2 if header_present else 1
    lines = data.decode("utf-8", errors="replace").splitlines()
    body = lines[1:] if header_present else lines
    for offset, line in enumerate(body):
        parts = line.split(",")
        if len(parts) != expected:
            return start_line + offset
        if not _is_int(parts[0]) or not _is_float(parts[1]) or not _is_float(parts[2]):
            return start_line + offset
        if not _is_int(parts[5]):
            return start_line + offset
    return start_line


def parse_aggtrades_csv(data: bytes, market: Market, file: str = "<input>") -> pl.DataFrame:
    """Parse Binance aggTrades CSV bytes into the canonical TradeTick dataframe.

    Fast path: polars reads and casts everything vectorized. On any parse
    error we fall back to a line-by-line scan to report file and line number.
    """
    columns = _aggtrades_columns(market)
    expected = len(columns)
    head = data[:4096].decode("utf-8", errors="replace")
    first_line = head.splitlines()[0] if head.strip() else ""
    header_present = _looks_like_aggtrades_header(first_line)
    skip_rows = 1 if header_present else 0

    try:
        raw = pl.read_csv(
            io.BytesIO(data),
            has_header=False,
            skip_rows=skip_rows,
            infer_schema=False,
            new_columns=list(columns),
        )
        if raw.width != expected:
            raise ValueError(f"expected {expected} columns, got {raw.width}")
        flags = raw["is_buyer_maker"].str.strip_chars().str.to_lowercase()
        if not flags.is_in(["true", "false"]).all():
            raise ValueError("is_buyer_maker is not a boolean")
        frame = raw.select(
            raw["agg_trade_id"].cast(pl.UInt64).alias("agg_id"),
            raw["price"].cast(pl.Float64).alias("price"),
            raw["quantity"].cast(pl.Float64).alias("qty"),
            _normalize_ts_series(raw["transact_time"].cast(pl.Int64)).alias("ts_ns"),
            (flags == "true").alias("buyer_is_maker"),
        )
    except (pl.exceptions.PolarsError, ValueError):
        line_no = _first_bad_aggtrades_line(data, expected, header_present)
        raise DataParseError(f"{file}:{line_no}: malformed aggTrades row") from None

    return frame.select(TRADETICK_SCHEMA.keys())


def _looks_like_funding_header(first_line: str) -> bool:
    parts = first_line.split(",")
    return len(parts) == 3 and parts[0] == "calc_time"


def parse_funding_csv(data: bytes, file: str = "<input>") -> pl.DataFrame:
    """Parse a Binance fundingRate CSV (calc_time,funding_interval_hours,last_funding_rate)."""
    text = data.decode("utf-8")
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise DataParseError(f"{file}:1: empty file")

    body, first_line_no = _split_header_body(lines, _looks_like_funding_header)

    ts: list[int] = []
    hours: list[int] = []
    rate: list[float] = []

    for offset, line in enumerate(body):
        line_no = first_line_no + offset
        parts = line.split(",")
        if len(parts) != 3:
            raise DataParseError(f"{file}:{line_no}: expected 3 fields, got {len(parts)}")
        if not _is_int(parts[0]):
            raise DataParseError(f"{file}:{line_no}: bad calc_time '{parts[0]}'")
        if not _is_int(parts[1]):
            raise DataParseError(f"{file}:{line_no}: bad funding_interval_hours '{parts[1]}'")
        if not _is_float(parts[2]):
            raise DataParseError(f"{file}:{line_no}: bad last_funding_rate '{parts[2]}'")
        ts.append(normalize_ts(int(parts[0])))
        hours.append(int(parts[1]))
        rate.append(float(parts[2]))

    return pl.DataFrame(
        {
            "ts_ns": pl.Series(ts, dtype=pl.Int64),
            "interval_hours": pl.Series(hours, dtype=pl.UInt32),
            "rate": pl.Series(rate, dtype=pl.Float64),
        },
        schema=FUNDING_SCHEMA,
    )
