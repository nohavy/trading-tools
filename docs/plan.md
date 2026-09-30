# Plan de référence — tradingv2

Validé les 29-30/09/2026. Microtrading crypto sur Binance : analyser les marchés en temps réel, identifier les variations, évaluer les gains espérés nets de frais, passer des ordres — après validation complète par backtesting.

## 1. Choix validés

- **Marché** : crypto Binance, spot + futures USDⓈ-M (produit générique long/short avec funding).
- **Horizon** : positions de quelques secondes à quelques minutes ; données bougies 1s + aggTrades.
- **Approche** : moteur de backtest maison en Python ; CLI + rapports HTML.
- **Processus** : Spec Kit + TDD pragmatique ; docs/commits FR, code EN ; git local.

## 2. Le point décisif : les frais

| Produit (grille VIP0, à revérifier) | Coût aller-retour (entrée + sortie) |
|---|---|
| Spot, marché ×2 | 20 bps (15 avec remise BNB) |
| Futures, marché ×2 | 10 bps |
| Futures, limite puis marché | 7 bps |
| Futures, limite ×2 | 4 bps |

À ajouter : spread, slippage, latence, funding (perps). Conséquences :

- Sur quelques secondes, les variations sont souvent inférieures à ces seuils → l'outil doit mesurer si un signal bat les frais **avant** tout backtest complet.
- Les ordres limites (frais maker) sont la voie réaliste ; leur simulation doit être bornée (pessimiste/optimiste).

## 3. Données disponibles (vérifiées sur data.binance.vision)

- **Spot** : klines (tous intervalles, dont 1s), aggTrades, trades. Timestamps en microsecondes depuis le 2025-01-01, millisecondes avant.
- **Futures UM** : klines **à partir de 1m seulement** (pas de 1s), aggTrades, trades, prix mark/index, fundingRate (mensuel) → le sub-minute UM se construit depuis les aggTrades (`bars_from_trades`, validé : 2,5M barres 1s depuis 35,7M trades en ~1s).
- **Pas de carnet L1/L2 gratuit récent** : bookTicker futures publié seulement de mai 2023 à mars 2024 → spread et file d'attente estimés avec bornes ; enregistrement en direct optionnel (`tv2 record`).
- **Déséquilibre acheteurs/vendeurs** calculable dès les klines (volume taker buy inclus).
- **Volumes BTCUSDT** : ~75 Mo/mois en klines 1s, 300-550 Mo/mois en aggTrades (zippés).

## 4. Architecture

**Principe** : le même code de stratégie tourne en backtest, paper et live ; seule la brique « exchange » change.

Deux niveaux :

- **Recherche (rapide, vectorisé)** : signaux et rendements suivants calculés sur colonnes entières (Polars).
- **Validation (événementiel, réaliste)** : exécution réaliste des ordres, réservée aux configurations retenues.

```
src/tradingv2/
  core/        types : Instrument, Bar, TradeTick, Order, Fill, Position, horloge
  data/        téléchargement, exchangeInfo, funding, catalogue, contrôles qualité
  features/    indicateurs (vectorisé + incrémental, parité testée)
  costs/       frais maker/taker, slippage, latence, funding, round_trip_bps()
  execution/   exchange simulé : règles Binance, matching des ordres
  portfolio/   comptes Spot & Futures, ledger brut/frais/slippage/funding
  strategy/    classe Strategy, Context, aide stop-loss/take-profit
  strategies/  buy_hold, random_null, meanrev_zscore, breakout_volume, orderflow_imbalance
  risk/        sizing, limites, filtre « edge > coûts + marge »
  backtest/    boucle de simulation, sweeps, walk-forward, Monte Carlo
  research/    rendements après signal (1s→15min), MFE/MAE vs coûts
  metrics/  report/  cli.py (tv2)
```

**Stack** : Python 3.12 via uv ; Polars, NumPy, Parquet, DuckDB ; pydantic (configs) + dataclasses/msgspec (événements) ; httpx, websockets ; Typer + rich ; Plotly + Jinja2 ; Optuna (optionnel) ; pytest + hypothesis ; ruff + mypy ; numba seulement si benchmark.

**Conventions** : timestamps int64 nanosecondes UTC partout ; floats arrondis strictement aux pas de Binance (tick/step/minNotional) ; `Decimal` réservé à la frontière API live.

## 5. Réalisme de la simulation

- **Anti-lookahead** : bougie transmise à sa clôture seulement ; ordre émis à t arrive à t + latence (150 ms ± 50, seedé) ; à timestamp égal : exchange → fills → market data → timers → stratégie.
- **Exécution prédictive sur trades** : pour chaque ordre actif, recherche vectorisée (searchsorted) de l'instant de prochaine exécution possible, inséré dans la file d'événements (annulé si l'ordre est annulé avant) — pas de boucle Python trade par trade.
- **Marché** : rempli aux transactions suivantes, du bon côté du carnet (flag buyer_is_maker) ; ordre plus gros qu'une transaction → VWAP des suivantes.
- **Limite / post-only** : bornes pessimiste (trade-through) et optimiste (touch) ; capture l'adverse selection.
- **Stop** : première transaction franchissant le seuil, puis marché + slippage.
- **Mode bougies seules** : SL et TP dans la même bougie → cas le plus défavorable.
- **Filtres Binance** : rejets identiques à l'API (tick, step, minNotional).
- **Futures** : position signée, levier, funding historique aux échéances, liquidation approximée.
- **Ledger** : net = gross − fees − slippage ± funding, réconciliable à chaque trade et cumulé.

## 6. Gains espérés, frais compris

- **Avant chaque trade** : risk gate — edge espéré (bps) vs coût aller-retour ; refuse si edge < coût + marge.
- **`tv2 research edge`** : rendements à 1s/5s/15s/30s/1min/5min/15min après chaque signal, comparés aux coûts par produit et type d'ordre.
- **Après un backtest** : gross vs net, détail frais/slippage/funding, part mangée par les frais, frais de break-even, courbe de sensibilité aux coûts.

## 7. Phases et features Spec Kit

| Feature Spec Kit | Phase | Contenu |
|---|---|---|
| 001 | 0+1 | Socle (uv, CLI `tv2`, config YAML) + données (téléchargement vérifié, Parquet ns, catalogue, `data check`, exchangeInfo, funding, resample) |
| 002 | 2 | Moteur : types, boucle d'événements, exchange simulé, coûts, comptes Spot/Perp, API Strategy |
| 003 | 3 | Features (parité), stratégies de base, métriques, rapport HTML, `tv2 compare` |
| 004 | 4 | Étude d'edge, sweeps, walk-forward, Monte Carlo, stress, régimes, holdout compté, verdict go/no-go |
| — | 5-7 | Temps réel (websocket, signaux, alertes), paper trading, live (testnet puis réel) |

**Go/no-go phase 4** (sur données non utilisées pour l'optimisation) : ≥ 300 trades OOS ; expectancy net positive et significative ; profit factor net ≥ 1,2 ; ≥ 70 % des fenêtres walk-forward positives ; résiste au stress (frais ×1,5, slippage ×2, latence +250 ms) ; drawdown < seuil.

## 8. Paramètres par défaut

- **Symboles** : BTCUSDT, ETHUSDT (spot + futures UM).
- **Périodes** : 1 mois pour développer ; mars → août 2026 pour valider ; septembre 2026 = holdout verrouillé.
- **Simulation** : 1 000 USDT, latence 150 ms ± 50, frais VIP0 sans BNB.

```yaml
data:     {market: um, symbol: BTCUSDT, bars: 1s, execution_tape: aggTrades, start: 2026-06-01, end: 2026-06-30}
costs:    {fees: binance_um_vip0, slippage: {model: fixed_bps, bps: 0.5}, latency: {mean_ms: 150, jitter_ms: 50, seed: 42}}
strategy: {name: meanrev_zscore, entry_order: limit_maker, params: {window: 120, entry_z: 2.5, exit_z: 0.5, stop_bps: 25, max_hold_s: 300}}
risk:     {sizing: {mode: fixed_notional, notional: 500}, max_daily_loss_pct: 3, min_edge_over_cost_bps: 2}
```

## 9. Risques

- La plupart des stratégies sub-minute ne battent pas les frais au niveau retail — l'étude d'edge vs coûts le vérifie vite.
- Sans carnet historique, l'exécution des ordres limites reste une estimation bornée.
- La simulation suppose que nos petits ordres ne font pas bouger le marché.
- L'accès aux futures dépend du pays de résidence : à vérifier avant la phase 7.

## 10. Contrats techniques validés (feature 001)

- **URLs** : `https://data.binance.vision/data/{spot|futures/um}/{daily|monthly}/{klines|aggTrades|fundingRate}/{SYMBOL}/...` ; checksum = même chemin + `.CHECKSUM` (SHA256).
- **CSV klines** (12 colonnes) → `Bar{ts_open_ns, open, high, low, close, volume, quote_volume, n_trades, taker_buy_volume, taker_buy_quote}`.
- **CSV aggTrades** : spot 8 colonnes (avec is_best_match), futures 7 → `TradeTick{ts_ns, price, qty, agg_id, buyer_is_maker}`.
- Ligne d'en-tête parfois présente (détection auto) ; erreurs de parsing explicites avec fichier + n° de ligne.
- **Normalisation des timestamps** par magnitude (≥1e17 → µs ; ≥1e14 → ms) → int64 ns.
- **Stockage** : `data/parquet/{market}/{type}/{symbol}/{interval}/{stem}.parquet` (zstd, 1 fichier = 1 source) + `data/catalog.json` (checksums, bornes, nb lignes, idempotent).
- **Choix mensuel/journalier** : mensuel pour un mois complet écoulé, journalier sinon.
- **exchangeInfo** : spot `api.binance.com`, futures `fapi.binance.com` → tick_size, step_size, min_notional par symbole.
- **`tv2 data check`** : trous de bougies, doublons d'ids, timestamps non monotones, high < low, prix aberrants.
- **Resample** 1s → 5s/15s/1m : OHLCV + agrégation taker_buy, barre partielle finale rejetée.
- **Téléchargement** : reprise sur interruption (`.part` + renommage atomique), skip des fichiers valides, backoff exponentiel sur 429/5xx, concurrence limitée.