"""Tests for the frozen threshold calibration (flows only, never returns)."""

import numpy as np
import pytest

from tradingv2.research.onchain_screen import calibrate_entry_net


def test_calibration_quantiles_on_the_is_window_only() -> None:
    # the runner feeds only FULL-coverage days; mask aligns day-by-day
    net = np.array(
        [
            100.0, 200.0, 300.0, 400.0, 500.0,   # IS window
            1000.0, 2000.0,                       # OOS: ignored
            50.0, 60.0, 70.0, 80.0, 90.0, 100.0, 110.0, 100.0, 120.0, 130.0,  # IS cont.
        ]
    )
    mask = np.array([*([True] * 5), *([False] * 2), *([True] * 10)])  # same size as net
    entry, exit_ = calibrate_entry_net(net, mask, quantile=0.90)
    is_positives = net[mask][net[mask] > 0.0]
    assert entry == pytest.approx(float(np.quantile(is_positives, 0.90)))
    assert exit_ == pytest.approx(float(np.quantile(is_positives, 0.25)))
    assert entry > exit_


def test_calibration_rejects_a_tiny_window() -> None:
    with pytest.raises(ValueError, match="at least 10"):
        calibrate_entry_net(
            np.array([1.0, 2.0, 3.0]), np.array([True, True, True]), quantile=0.9
        )
