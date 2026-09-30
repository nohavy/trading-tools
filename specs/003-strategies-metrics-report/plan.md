# Implementation Plan: Stratégies, métriques et rapport

**Branch**: `003-strategies-metrics-report` | **Date**: 2026-09-30 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/003-strategies-metrics-report/spec.md`

## Summary

Indicateurs en double implémentation (lot vectorisé + pas à pas) avec parité testée, quatre stratégies paramétrables branchées sur le registre existant, métriques complètes nettes de frais calculées depuis les artefacts de run, rapport HTML autonome (SVG inline, < 2 Mo) et comparaison de runs.

## Technical Context

**Language/Version**: Python 3.12 (uv) — infrastructure en place

**Primary Dependencies**: polars + numpy (features lot), dataclasses (pas à pas), jinja2 (rendu), pytest + hypothesis

**Storage**: métriques dans chaque run (`metrics.json`), rapport `report.html`, comparaisons dans `runs/compare-*.html`

**Testing**: pytest + hypothesis ; goldens courts calculés à la main ; parité sur données réelles d'août 2026

**Target Platform**: Linux CLI

**Performance Goals**: SC-005 — run + rapport sur le mois réel < 60 s ; le run moteur prend 22 s (mesuré, feature 002)

**Constraints**: rapport autonome sans JS externe (Plotly = 4,5 Mo de JS > budget 2 Mo) → graphiques SVG générés maison ; parité lot/pas-à-pas non négociable

**Scale/Scope**: 5 indicateurs, 4 stratégies, ~20 métriques, rapport mono-run, comparaison N runs

## Constitution Check

| Principe | Statut | Note |
|---|---|---|
| I. Test-First | PASS | Cycles par module ci-dessous ; rendu HTML = smoke tests (exception validée) |
| II. Réalisme économique | PASS | Métriques nettes + décomposition coûts ; parité = la stratégie backtestée est celle qui tournera en live |
| III. Anti-lookahead / déterminisme | PASS | Les indicateurs pas à pas ne voient que les barres closes ; rendu déterministe (stamp exclu) |
| IV. Un code, trois exécutions | PASS | La version pas à pas est LA version live future ; parité testée |
| V. Simplicité | PASS | SVG maison vs Plotly (justifié par le budget de taille) ; fenêtres en nb de barres |

## Project Structure

```text
src/tradingv2/
├── features/__init__.py, vectorized.py, incremental.py
├── metrics/__init__.py, compute.py        # MetricsReport depuis equity + fills/round trips
├── report/__init__.py, render.py, compare.py
├── strategies/{builtin,meanrev,breakout,flow,null}.py
└── backtest/{engine,runner}.py            # engine: +funding events +ledger ; runner: +report
tests/unit/test_{features_vectorized,features_incremental,metrics,metrics_edge,
  strategies_meanrev,strategies_breakout,strategies_flow,engine_funding,
  report_render,report_compare,runner_report,cli}.py
tests/property/test_features_parity.py
```

## Contrats techniques

### Indicateurs (`features/`)

- `ema(values, span)` : alpha = 2/(span+1) ; seed = première valeur ; défini dès la barre 1.
- `zscore(values, window)` : (x − mean_rolling) / std_rolling, std population (ddof=0) ; NaN si fenêtre non pleine.
- `vwap(ts, price, volume)` : cumulatif, reset à minuit UTC (session journalière) ; NaN avant le premier volume > 0.
- `realized_vol(close, window)` : std roulant (ddof=0) des rendements simples ; NaN tant que fenêtre non pleine (fenêtre-1 rendements).
- `flow_imbalance(volume, taker_buy_volume, window)` : 2 × Σbuy/Σvol − 1 ∈ [−1, 1] ; NaN si Σvol = 0 dans la fenêtre.
- Versions pas à pas : classes `EmaIncr(span)`, `ZScoreIncr(window)`, `VwapIncr()`, `RealizedVolIncr(window)`, `FlowImbalanceIncr(window)` avec `update(...) -> float | None` (None = pas encore défini), reset() si besoin. Convention identique à la version lot.
- Parité testée : lot vs pas à pas sur barres réelles (propriété : échantillons aléatoires + golden mois réel).

### Engine : funding + registre (rattrapage nécessaire)

- Le moteur 002 n'appliquait jamais le funding ni le registre. Ajout :
  - `Engine.run(..., funding_events: list[FundingEvent] | None)` : événements aux ts du fichier funding (priority 1, seq avant les barres à ts égal — insérés d'abord) ; sur MarginAccount : `account.apply_funding(...)` + accumulateur `funding_since_entry`.
  - Moteur : à chaque fill → accumule fees/slippage/gross du round trip en cours ; quand la position repasse à 0 (expose `exchange.position_qty`) → `ledger.record_trade(...)` + émet `TradeClosed` dans le résultat.
- `EngineResult` gagne : `round_trips: list[RoundTrip]` (entry_ts, exit_ts, side, qty, entry_price, exit_price, gross, fees, slippage, funding, net, hold_ns) et `ledger_totals`.

### Métriques (`metrics/compute.py`)

- `compute_metrics(equity: pl.DataFrame, round_trips, interval_ns) -> MetricsReport` :
  - `total_return` = final/initial − 1 ; `sharpe` = mean(r)/std(r, ddof=0) × sqrt(365×86400/interval_s) ; `sortino` = mean(r)/downside_std × même facteur ; `max_drawdown` = max((peak−eq)/peak) ; `calmar` = total_return/max_dd (si dd > 0) ;
  - `n_trades`, `win_rate`, `avg_win`, `avg_loss`, `payoff`, `profit_factor` (∞ → None), `expectancy_bps` (net moyen en bps du notional d'entrée moyen), `avg_hold_ns` ;
  - coûts : `gross_total, fees_total, slippage_total, funding_total, net_total, fee_drag` (fees/gross si gross > 0 sinon None) ;
  - `t_stat` = expectancy_net / (std_net/sqrt(n)) si n ≥ 2 et std > 0 sinon None.
- Toutes les valeurs `float | None` ; zéro trade → trades/costs à None (sauf n_bars, total_return).
- Persisté en `metrics.json` dans le run.

### Stratégies (`strategies/`)

- Paramètres communs (chacun son dataclass) : `qty`, `stop_bps | None`, `max_hold_bars | None`, `entry_order = "market"` (v1).
- `MeanRevZScore(window, entry_z, exit_z, stop_bps, max_hold_bars, qty)` : z du **close** ; z ≤ −entry_z → BUY ; z ≥ +entry_z → SELL ; sortie quand |z| ≤ exit_z ; stop market posé à l'entrée (ref = close courant) annulé à la sortie ; une position à la fois ; max_hold_bars force la sortie.
- `BreakoutVolume(lookback, volume_factor, stop_bps, max_hold_bars, qty)` : close > max(high des `lookback` barres précédentes) ET volume > volume_factor × mean(volume fenêtre) → BUY ; symétrique SELL.
- `OrderFlowImbalance(window, threshold, stop_bps, max_hold_bars, qty)` : imbalance (version pas à pas) ≥ threshold → BUY ; ≤ −threshold → SELL.
- `BuyHold` : achète à la première barre, conserve.
- Enregistrement dans `STRATEGIES` du registre builtin (meanrev, breakout, flow, buy_hold).

### Rapport (`report/`)

- `render_report(run_dir) -> Path` : lit config/summary/trades/equity/metrics → HTML autonome :
  - en-tête : stratégie, période, paramètres ;
  - tableau métriques (perf / trades / coûts) ;
  - SVG équité (polyline) + zone drawdown ; SVG histogramme PnL par trade ; barres coûts (brut/frais/slippage/funding) ;
  - « aucun trade » si n_trades = 0 ; valeurs None → « n/a ».
- Déterminisme : aucune horloge dans le HTML (stamp = manifest du run).
- `compare_runs(run_dirs, runs_root) -> Path` : `metrics.json` de chaque run → tableau HTML côte à côte + sortie texte CLI.

### Runner/CLI

- `run_backtest` ajoute : round trips → `compute_metrics` → `metrics.json` → `render_report`.
- `tv2 compare <run1> <run2> ...` : affiche le tableau texte et écrit le HTML.

## Backlog TDD (cycles, 1 cycle ≈ 1 commit)

1. `test_features_vectorized` — goldens EMA/zscore/vwap/vol/imbalance → `feat: indicateurs vectorisés`
2. `test_features_incremental` — mêmes goldens pas à pas + classe par indicateur → `feat: indicateurs incrémentaux`
3. `test_features_parity` (hypothesis + mois réel) — lot == pas à pas → `test: parité indicateurs`
4. `test_engine_funding` — funding events appliqués au margin + round trips + ledger branché → `feat: funding et registre moteur`
5. `test_metrics` — golden à la main (toutes les métriques) → `feat: métriques`
6. `test_metrics_edge` — zéro trade, PF infini, variance nulle, dd nul → `test: métriques dégénérées`
7. `test_strategies_meanrev` — entrée/sortie/stop/max_hold vérifiés trade par trade → `feat: stratégie meanrev`
8. `test_strategies_breakout` — cassure + confirmation volume, symétrie short → `feat: stratégie breakout`
9. `test_strategies_flow` — seuils de déséquilibre → `feat: stratégie orderflow`
10. `test_strategies_buyhold` + registre → `feat: stratégie buy_hold`
11. `test_report_render` — sections, autonomie, taille, déterminisme, aucun-trade (smoke assertions sur le HTML) → `feat: rapport html`
12. `test_report_compare` — tableau N runs + HTML → `feat: comparaison runs`
13. `test_runner_report` — run génère metrics.json + report.html → `feat: run génère métriques et rapport`
14. `test_cli_compare` — `tv2 compare` → `feat: cli comparaison`
15. Benchmark SC-005 mois réel < 60 s (marque `slow`) → `test: benchmark run rapport`

## Complexity Tracking

Aucune violation de constitution à justifier.