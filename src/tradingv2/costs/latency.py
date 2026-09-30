"""Latency cost model: seeded, deterministic per instance."""

import numpy as np


class LatencyModel:
    """Simulated order latency: mean ± gaussian jitter, clamped at zero.

    Determinism: two models built with the same seed produce identical
    sample sequences (constitution III).
    """

    def __init__(self, mean_ms: float, jitter_ms: float, seed: int) -> None:
        if mean_ms < 0 or jitter_ms < 0:
            raise ValueError(
                f"latency parameters must be non-negative, got mean={mean_ms} jitter={jitter_ms}"
            )
        self.mean_ms = mean_ms
        self.jitter_ms = jitter_ms
        self._rng = np.random.default_rng(seed)

    def sample_ns(self) -> int:
        """Sample one latency in nanoseconds."""
        value_ms = self.mean_ms + float(self._rng.normal(0.0, self.jitter_ms))
        return int(round(max(0.0, value_ms) * 1_000_000))
