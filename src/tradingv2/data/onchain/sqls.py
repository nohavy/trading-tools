"""Deterministic BigQuery SQL builders for the on-chain research (012).

Pure string generators: the SQL is a function of its explicit inputs so the
same replays re-produce the same result byte-for-byte (catalogue checksums).
"""

_DAY_NS = 60 * 60 * 24 * 1_000_000_000


def eth_hub_degree_sql(*, start: str, end: str) -> str:
    """In/out degree aggregation over ETH transfers for a discovery window.

    Exchange hubs show both high in-degree (deposits) and high out-degree
    (withdrawals) on raw native transfers. The candidate set is derived by
    pure topology — value-agnostic at the ranking step, frozen BEFORE any
    evaluation window.
    """
    from datetime import date

    if date.fromisoformat(start) >= date.fromisoformat(end):
        raise ValueError("window must satisfy start < end")
    window = f"block_timestamp BETWEEN TIMESTAMP('{start}') AND TIMESTAMP('{end}')"

    return f"""
SELECT _x, in_deg, out_deg, vol_eth
FROM (
  SELECT to_address AS _x,
         COUNT(DISTINCT from_address) AS in_deg, 0 AS out_deg,
         SUM(value/1e18) AS vol_eth
  FROM `bigquery-public-data.crypto_ethereum.transactions`
  WHERE {window} AND value > 0 AND to_address IS NOT NULL
    AND from_address IS NOT NULL
  GROUP BY to_address
) UNION ALL (
  SELECT from_address,
         0, COUNT(DISTINCT to_address), SUM(value/1e18)
  FROM `bigquery-public-data.crypto_ethereum.transactions`
  WHERE {window} AND value > 0 AND to_address IS NOT NULL
    AND from_address IS NOT NULL
  GROUP BY from_address
)
"""


def eth_flow_daily_sql(*, addresses: tuple[str, ...], start: str, end: str) -> dict[str, str]:
    """Daily aggregate flows for a FROZEN address set (account ledger).

    Deposits = to_address ∈ set, withdrawals = from_address ∈ set — no
    joins needed.
    """
    from datetime import date

    if not addresses:
        raise ValueError("the frozen address set must be non-empty")
    if date.fromisoformat(start) >= date.fromisoformat(end):
        raise ValueError("window must satisfy start < end")
    literals = ", ".join(f"'{a.lower()}'" for a in sorted(set(a.lower() for a in addresses)))
    window = f"block_timestamp BETWEEN TIMESTAMP('{start}') AND TIMESTAMP('{end}')"
    table = "`bigquery-public-data.crypto_ethereum.transactions`"
    return {
        "eth_flows": f"""
SELECT
  DATE(block_timestamp) AS day,
  SUM(IF(to_address IN ({literals}), value, 0))/1e18   AS deposit_eth,
  SUM(IF(from_address IN ({literals}), value, 0))/1e18 AS withdraw_eth,
  COUNT(DISTINCT IF(to_address IN ({literals}), from_address, NULL)) AS deposit_clients,
  COUNT(DISTINCT IF(from_address IN ({literals}), to_address, NULL)) AS withdraw_clients
FROM {table}
WHERE {window}
GROUP BY day ORDER BY day
""",
    }


def btc_hub_degree_sql(*, year: int, top: int) -> str:
    """BTC hub candidates for a calendar year: the year's top receivers.

    Discovery is value-based topology (no price data, no prior returns):
    each candidate must behave like a deposit sink. The funding-transaction
    floor (>= 50 000 distinct txs paying in) filters single-investor or
    miner-payout addresses.
    """
    if top <= 0:
        raise ValueError("top must be positive")
    return f"""
SELECT a AS hub,
       SUM(value)/1e8 AS received_btc,
       COUNT(DISTINCT transaction_hash) AS funding_txs
FROM `bigquery-public-data.crypto_bitcoin.outputs`, UNNEST(addresses) AS a
WHERE DATE(TIMESTAMP_MILLIS(block_timestamp)) BETWEEN '{year}-01-01'
  AND '{year + 1}-01-01'
  AND a IS NOT NULL
GROUP BY a
HAVING COUNT(DISTINCT transaction_hash) >= 50000
ORDER BY received_btc DESC
LIMIT {top}
"""


def btc_flow_daily_sql(*, addresses: tuple[str, ...], start: str, end: str) -> dict[str, str]:
    """Daily deposits/withdrawals of a frozen BTC address set (no joins).

    BTC carries the account picture directly: `outputs.addresses` receives,
    `inputs.addresses` spends — the SAME address set on both tables,
    aggregated per day.
    """
    if not addresses:
        raise ValueError("addresses must be non-empty")
    from datetime import date

    if date.fromisoformat(start) >= date.fromisoformat(end):
        raise ValueError("window must satisfy start < end")
    literals = ", ".join(f"'{a}'" for a in sorted(set(addresses)))
    sqls: dict[str, str] = {}
    for side, table in (("in", "outputs"), ("out", "inputs")):
        window = f"DATE(TIMESTAMP_MILLIS(block_timestamp)) BETWEEN '{start}' AND '{end}'"
        sqls[f"btc_{side}_flows"] = f"""
SELECT DATE(TIMESTAMP_MILLIS(block_timestamp)) AS day,
       SUM(value)/1e8 AS amount_btc,
       COUNT(DISTINCT transaction_hash) AS txs
FROM `bigquery-public-data.crypto_bitcoin.{table}`, UNNEST(addresses) AS a
WHERE a IN ({literals}) AND {window}
GROUP BY day ORDER BY day
"""
    return sqls
