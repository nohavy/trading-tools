"""Deterministic BigQuery SQL builders for the on-chain research (012).

Pure string generators: the SQL is a function of its explicit inputs so the
same replays re-produce the same result byte-for-byte (catalogue checksums).
"""

_DAY = 60 * 60 * 24


def eth_hub_degree_sql(*, start: str, end: str) -> str:
    """In/out degree aggregation over ETH transfers for a discovery window.

    Exchange hubs show both high in-degree (deposits) and high out-degree
    (withdrawals) on raw native transfers. The candidate set is derived by
    pure topology — value-agnostic, frozen BEFORE any window upstream.
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


def flow_daily_sql(
    *, addresses: tuple[str, ...], start: str, end: str, dataset: str
) -> dict[str, str]:
    """Daily aggregate flows for a FROZEN address set; deterministic inline.

    ETH (account ledger): deposits = to_address ∈ set, withdrawals =
    from_address ∈ set — no joins needed.
    """
    from datetime import date

    if not addresses:
        raise ValueError("the frozen address set must be non-empty")
    if date.fromisoformat(start) >= date.fromisoformat(end):
        raise ValueError("window must satisfy start < end")
    literals = ", ".join(f"'{a.lower()}'" for a in sorted(set(a.lower() for a in addresses)))
    window = f"block_timestamp BETWEEN TIMESTAMP('{start}') AND TIMESTAMP('{end}')"
    table = f"`bigquery-public-data.{dataset}.transactions`"
    return {
        "eth_flows": f"""
SELECT
  DATE(block_timestamp) AS day,
  SUM(IF(to_address IN ({literals}), value, 0))/1e18   AS deposit_eth,
  SUM(IF(from_address IN ({literals}), value, 0))/1e18 AS withdraw_eth,
  COUNT(DISTINCT to_address) AS deposit_clients,
  COUNT(DISTINCT from_address) AS withdraw_clients
FROM {table}
WHERE {window}
GROUP BY day ORDER BY day
""",
    }
