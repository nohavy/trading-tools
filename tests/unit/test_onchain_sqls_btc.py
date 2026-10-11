"""Tests for the BTC SQL builders (012, UTXO model)."""

import pytest

from tradingv2.data.onchain.sqls import btc_flow_daily_sql, btc_hub_degree_sql


def test_btc_hub_sql_deterministic_and_timeboxed() -> None:
    a = btc_hub_degree_sql(year=2020, top=30)
    b = btc_hub_degree_sql(year=2020, top=30)
    assert a == b  # the same replay reproduces the same text
    assert "BETWEEN '2020-01-01'" in a and "'2021-01-01'" in a
    assert "UNNEST(addresses)" in a
    assert "HAVING COUNT(DISTINCT transaction_hash) >= 50000" in a
    assert "LIMIT 30" in a


def test_btc_flow_daily_uses_the_frozen_set_on_both_sides() -> None:
    sqls = btc_flow_daily_sql(
        addresses=("3bbb", "3aaa"), start="2021-01-01", end="2021-12-31"
    )
    assert set(sqls) == {"btc_in_flows", "btc_out_flows"}
    for text in sqls.values():
        assert text == text  # deterministic text
        assert "'3aaa', '3bbb'" in text  # sorted, inlined once
        assert "amount_btc" in text
        assert "BETWEEN '2021-01-01'" in text
    assert "bigquery-public-data.crypto_bitcoin.outputs" in sqls["btc_in_flows"]
    assert "bigquery-public-data.crypto_bitcoin.inputs" in sqls["btc_out_flows"]


def test_btc_builders_reject_bad_inputs() -> None:
    with pytest.raises(ValueError, match="top"):
        btc_hub_degree_sql(year=2020, top=0)
    with pytest.raises(ValueError, match="addresses"):
        btc_flow_daily_sql(addresses=(), start="2021-01-01", end="2021-12-31")
    with pytest.raises(ValueError, match="window"):
        btc_flow_daily_sql(addresses=("a",), start="2021-12-01", end="2021-01-01")
