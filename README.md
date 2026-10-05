# tradingv2 — falsification de stratégies crypto

Outil de recherche et de backtest pour le microtrading crypto : **Binance spot
et futures USDⓈ-M**. Un pipeline falsifié en continu : chaque hypothèse de
stratégie est écranée « avant/après coûts », validée chronologiquement (IS/OOS,
walk-forward, holdout pré-enregistré) puis rejouée dans un moteur
événementiel réaliste (fills 1m, latence, slippage, marge) avant tout go/no-go.

## Philosophie (constitution)

- **Backtest réaliste d'abord** ; temps réel, paper et live ensuite.
- **Pré-enregistrement** : règles et seuils figés avant de voir les rendements
  (`docs/*-prereg.md`) ; aucun seuil ajusté après lecture de la grille.
- **Coûts systématiques** : fees maker/taker, slippage, latence, funding réel
  Binance ; jamais d'edge brut sans frais.
- **Statistiques honnêtes** : t-stat Newey-West (HAC), drawdown, comparaison
  systématique à un benchmark ; les sous-périodes OOS ne sont pas des
  validations indépendantes.
- Spéc-kit : une feature = `specs/NNN-nom/` (spec → plan → tasks → TDD), un
  cycle Red→Green→Refactor = un commit conventionnel en français.

## Verdicts de recherche à ce jour

| Feature | Hypothèse | Verdict |
|---|---|---|
| 005–006 | Funding momentum + scan 524 perpétuels | **NO-GO** — l'edge brut du scan ne survit pas à la stratégie réaliste |
| 007–008 | Trend temporel 60j long/flat BTC/ETH | **NO-GO** — t = 1,53 < 2,0 et DD 36,8 % > 25 % |
| — | Holdout pré-enregistré septembre 2026 (trend 60j) | **NO-GO** — équivalent à buy-and-hold, aucune valeur ajoutée |
| 009 | Carry neutre spot/perp pré-enregistré | **Premier écran validé** (t 4-6, DD 0,2-0,6 %) mais le filtre de timing détruit la valeur ; **le toujours couvert** (+49,4 % OOS) devient le candidat |
| 010 | Carry toujours couvert dans le moteur 1m | **Validé moteur** — t 7,20/6,04, DD 0,38/0,29 %, fidélité vectorielle établie, stress franchi ; holdout pré-enregistré = prochaine étape |

## Installation

```bash
uv sync                    # Python 3.12 + dépendances
uv run tv2 --help          # CLI du projet
```

## Données (feature 001)

Le téléchargement est idempotent (checksums sha256, fichiers mensuels Binance
Vision convertis en Parquet int64 ns, catalogue `data/catalog.json`) :

```bash
uv run tv2 data download --config configs/reference.yaml         # spot 1s
uv run tv2 data download --config configs/download-um-1m.yaml    # futures 1m
uv run tv2 data check --config configs/reference.yaml            # QC (trous, doublons, OHLC, outliers)
uv run tv2 data instruments --market spot --symbol BTCUSDT       # règles de trading (tick, step, minNotional)
```

Configs de référence dans `configs/` : spot 1s, UM 1m, aggTrades, funding
historique, jambes d'étude (`download-spot-1d-*`, `download-spot-1m-*`,
`download-holdout-*`).

## Recherche et validation (features 002-004)

```bash
uv run tv2 research edge --config configs/edge-meanrev.yaml    # rendements après signal vs coûts (filtre pré-backtest)
uv run tv2 backtest sweep --config configs/backtest.yaml --grid "window=60..300:60"
uv run tv2 backtest walkforward --config ... --grid ... --train-bars N --test-bars M
uv run tv2 backtest monte-carlo runs/<id> --sims 1000          # percentiles du PnL final
uv run tv2 backtest stress --config ...                        # frais ×1,5, slippage ×2, latence +250 ms, combiné
uv run tv2 validate run runs/<id>                              # verdict go/no-go (7 critères)
```

## Scripts d'étude (features 007-010)

| Script | Rôle |
|---|---|
| `scripts/time_series_trend_study.py` | Écran vectoriel trend quotidien BTC/ETH avec funding réel (007) |
| `scripts/run_trend_engine_validation.py` | Rejeu événementiel 1m du trend 60j + buy-and-hold (008) |
| `scripts/run_trend_holdout.py` | Holdout pré-enregistré septembre 2026, funding via endpoint officiel |
| `scripts/spot_perp_carry_study.py` | Écran carry neutre spot/perp pré-enregistré, cellules figées (009) |
| `scripts/run_carry_engine_validation.py` | Validation moteur des jambes carry (010, en cours) |

Les cellules primaires et les sensibilités sont figées dans les scripts et les
pré-enregistrements `docs/*-prereg.md` ; les résultats complets sont écrits en
JSON dans `data/` (ignoré par git) et le verdict est rendu dans
`docs/*-result-*.md`.

## Qualité

```bash
uv run pytest                 # tout doit être vert avant commit
uv run pytest -m "not net"    # sans les tests réseau
uv run pytest -m net          # intégration réseau uniquement
uv run ruff check             # lint
uv run mypy                   # types (strict)
```

Marqueurs : `net` (accès réseau), `slow` (benchmarks longs, dont un sweep de
données réelles dont le budget temps documenté est dépassé sur les machines
actuelles — voir tasks 008/009).

## Layout

- `src/tradingv2/` : `core` (types), `data` (téléchargement, catalogue, QC),
  `features`, `costs`, `execution`, `portfolio`, `strategy`/`strategies`,
  `risk`, `backtest`, `research`, `metrics`, `report`, `cli.py`
- `tests/` : `unit/`, `property/`, `integration/` (marque `net`), `fixtures/`
- `configs/` : YAML (données, coûts, backtests) · `specs/` : spec-kit ·
  `docs/` : pré-enregistrements et verdicts

## Secrets et licence

Aucune clé API dans le repository (téléchargements publics Binance Vision
anonymes) ; les clés ne servent qu'au live et ne sont jamais versionnées.
Licence : MIT (voir `LICENSE`).
