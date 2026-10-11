"""Tests for the on-chain SQL builders (012): pure, deterministic, gated."""

import pytest

from tradingv2.data.onchain.sqls import eth_flow_daily_sql, eth_hub_degree_sql


def test_eth_hub_degree_sql_filters_by_window_and_is_deterministic() -> None:
    sql1 = eth_hub_degree_sql(start="2020-01-01", end="2020-02-01")
    sql2 = eth_hub_degree_sql(start="2020-01-01", end="2020-02-01")
    assert sql1 == sql2
    assert "TIMESTAMP('2020-01-01')" in sql1
    assert "TIMESTAMP('2020-02-01')" in sql1
    assert "COUNT(DISTINCT to_address)" in sql1
    assert "COUNT(DISTINCT from_address)" in sql1
    assert "value > 0" in sql1
    assert "crypto_ethereum.transactions" in sql1


def test_eth_hub_degree_sql_rejects_inverted_window() -> None:
    with pytest.raises(ValueError, match="window"):
        eth_hub_degree_sql(start="2020-02-01", end="2020-01-01")


def test_eth_flow_daily_inlines_frozen_addresses_sorted() -> None:
    sqls = eth_flow_daily_sql(
        addresses=("0xbbb", "0xaaa"),
        start="2021-01-01",
        end="2021-12-31",
    )
    assert sqls["eth_flows"] == sqls["eth_flows"]  # deterministic
    assert "'0xaaa', '0xbbb'" in sqls["eth_flows"]  # sorted literals
    assert "2021-01-01" in sqls["eth_flows"]
    assert "2021-12-31" in sqls["eth_flows"]
    assert "deposit_clients" in sqls["eth_flows"]
    assert "withdraw_clients" in sqls["eth_flows"]
