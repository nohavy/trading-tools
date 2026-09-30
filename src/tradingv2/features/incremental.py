"""Incremental indicators (step mode). Same conventions as features/vectorized.

These classes are the live-parity contract (constitution IV): the parity
tests prove the lot and step implementations produce identical values, so a
strategy validated on the vectorized version behaves identically in real time.
"""

from collections import deque


class EmaIncr:
    """EMA seeded with the first value, alpha = 2/(span+1)."""

    def __init__(self, span: int) -> None:
        if span <= 0:
            raise ValueError(f"span must be positive, got {span}")
        self._alpha = 2 / (span + 1)
        self.value: float | None = None

    def update(self, x: float) -> float | None:
        if self.value is None:
            self.value = x
        else:
            self.value = (1 - self._alpha) * self.value + self._alpha * x
        return self.value


class ZScoreIncr:
    """Rolling z-score (population std); None while the window is not full."""

    def __init__(self, window: int) -> None:
        if window <= 0:
            raise ValueError(f"window must be positive, got {window}")
        self._window = window
        self._values: deque[float] = deque(maxlen=window)

    def update(self, x: float) -> float | None:
        self._values.append(x)
        if len(self._values) < self._window:
            return None
        n = len(self._values)
        mean = sum(self._values) / n
        variance = sum((v - mean) ** 2 for v in self._values) / n
        std = float(variance**0.5)
        if std == 0.0:
            return None
        return float((x - mean) / std)


class VwapIncr:
    """Session VWAP (UTC day reset); None while the cumulative volume is zero."""

    def __init__(self) -> None:
        self._day = -1
        self._pv = 0.0
        self._cv = 0.0

    def update(self, ts_ns: int, price: float, volume: float) -> float | None:
        day = ts_ns // 86_400_000_000_000
        if day != self._day:
            self._day = day
            self._pv = 0.0
            self._cv = 0.0
        self._pv += price * volume
        self._cv += volume
        return float(self._pv / self._cv) if self._cv > 0 else None


class RealizedVolIncr:
    """Rolling std (population) of simple returns; None until `window` returns."""

    def __init__(self, window: int) -> None:
        if window <= 0:
            raise ValueError(f"window must be positive, got {window}")
        self._window = window
        self._returns: deque[float] = deque(maxlen=window)
        self._prev_close: float | None = None

    def update(self, close: float) -> float | None:
        if self._prev_close is None:
            self._prev_close = close
            return None
        self._returns.append(close / self._prev_close - 1)
        self._prev_close = close
        if len(self._returns) < self._window:
            return None
        n = len(self._returns)
        mean = sum(self._returns) / n
        variance = sum((r - mean) ** 2 for r in self._returns) / n
        return float(variance**0.5)


class FlowImbalanceIncr:
    """Taker-buy share over a bar window mapped to [-1, 1]; None if volume 0."""

    def __init__(self, window: int) -> None:
        if window <= 0:
            raise ValueError(f"window must be positive, got {window}")
        self._window = window
        self._volume: deque[float] = deque(maxlen=window)
        self._buy: deque[float] = deque(maxlen=window)

    def update(self, volume: float, taker_buy_volume: float) -> float | None:
        self._volume.append(volume)
        self._buy.append(taker_buy_volume)
        if len(self._volume) < self._window:
            return None
        total = sum(self._volume)
        buy = sum(self._buy)
        if total == 0:
            return None
        return float(2 * buy / total - 1)
