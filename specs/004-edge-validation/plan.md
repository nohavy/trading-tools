# Implementation Plan: Étude d'edge et validation des stratégies

**Branch**: `004-edge-validation` | **Date**: 2026-09-30 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/004-edge-validation/spec.md`

## Summary

Chaîne de validation complète : étude d'edge signal×horizon×coûts avant backtest, sweep de grilles en parallèle avec cartes de stabilité, walk-forward chronologique, monte carlo sur les trades, stress des coûts, ventilation par régimes de volatilité, holdout verrouillé compté, verdict go/no-go sur les critères du plan.

## Technical Context

**Language/Version**: Python 3.12 (uv) — infrastructure en place

**Primary Dependencies**: numpy (edge forward returns, monte carlo vectorisé), polars (données), concurrent.futures ProcessPoolExecutor (sweeps), jinja2 (rapports)

**Storage**: résultats de validation dans `runs/` (edge-*.json/html, sweep-*.html, validation.json, holdout counter dans `data/holdout_attempts.json`)

**Testing**: pytest + hypothesis ; goldens synthétiques ; données réelles d'août pour l'intégration

**Target Platform**: Linux CLI, 12 cœurs

**Performance Goals**: sweep 20 configs < 10 min (parallèle 12) ; monte carlo 1000 tirages < 10 s ; edge sur 1 mois < 30 s

**Constraints**: déterminisme à graine fixée partout ; les numba/optimisations restent interdites sans benchmark

**Scale/Scope**: 3 signaux × 7 horizons × N paires d'ordres ; grilles explicites ; 1 instrument par étude

## Constitution Check

| Principe | Statut | Note |
|---|---|---|
| I. Test-First | PASS | Cycles ci-dessous ; rapport HTML en smoke |
| II. Réalisme économique | PASS | L'edge est mesuré net de coûts ; le verdict exige la survie au stress |
| III. Anti-lookahead / déterminisme | PASS | Les forward returns d'edge sont postérieurs au signal par définition ; folds chronologiques sans recouvrement |
| IV. Un code, trois exécutions | PASS | Le stress rejoue le MÊME moteur/config, coûts seuls changés |
| V. Simplicité | PASS | Grilles explicites (pas d'Optuna v1), numpy pur pour monte carlo |

## Project Structure

```text
src/tradingv2/
├── research/__init__.py, edge.py, signals.py
├── backtest/sweep.py, walkforward.py, montecarlo.py, stress.py, validate.py
├── report/ (compare + edge/sweep/validation templates)
└── cli.py  # research edge, backtest sweep/walkforward/monte-carlo/stress, tv2 validate
tests/unit/test_{edge,signals,sweep,walkforward,montecarlo,stress,validate,regimes,cli_validation}.py
tests/integration/test_edge_month.py (net? non — données locales, marque slow)
```

## Contrats techniques

### Edge (`research/edge.py`, `research/signals.py`)

- `SignalEvent = (ts_ns, direction)` ; signaux fournis sur les barres (features lot) :
  - `signal_meanrev(close, window, entry_z)` : ts où |z| franchit +entry_z (direction opposée au z) ;
  - `signal_breakout(highs, lows, closes, volumes, lookback, volume_factor)` ;
  - `signal_flow(volume, taker_buy, window, threshold)`.
- `forward_returns(ts, close, event_ts, horizons_ns)` : vectorisé (searchsorted) — rendement (close[t+h] − close[t_event])/close[t_event] en bps.
- `edge_table(events, close, ts, horizons, cost_pairs)` → lignes : horizon, n, mean_bps, median_bps, hit_rate, mfe_bps, mae_bps, + pour chaque paire d'ordres (produit × entry/exit) : round_trip_bps, edge_bps = mean − round_trip.
- MFE/MAE : excursions max favorables/défavorables entre l'événement et chaque horizon — calculées par fenêtres max/min glissantes vectorisées (numpy), pas par boucle.

### Sweep (`backtest/sweep.py`)

- `sweep_grid(base_config, grid: dict[str, list], runs_root, data_root, workers=12)` → liste de métriques (runs complets réutilisant `run_backtest` via des configs générées) ; classement par expectancy_bps net ; marque `few_trades` si n_trades < 30 ; heatmap SVG (espérance par cellule) + tableau HTML.
- Parallélisme : ProcessPoolExecutor (les runs sont des process indépendants), graine par run = base + index (déterminisme).

### Walk-forward (`backtest/walkforward.py`)

- `walk_forward(base_config, grid, train_bars, test_bars, data_root, runs_root)` : découpage CHRONOLOGIQUE en (train, test) consécutifs sans recouvrement (bornes sur les ts de clôture, golden testé) ; pour chaque fold : meilleur param sur train (espérance nette, même marque few_trades) → évaluation sur test ; sortie : métriques OOS agrégées (round trips des tests concaténés) + par fold + `pct_positive_folds`.
- Le holdout est hors du walk-forward (verrouillé).

### Monte Carlo (`backtest/montecarlo.py`)

- `bootstrap_trips(nets: list[float], n_sims, seed, dd_threshold)` : numpy `default_rng.choice(..., replace=True)` — distribution du PnL final (p5/p50/p95) + proba de drawdown > seuil sur les séquences tirées (max DD de la séquence cumulée, vectorisé par matrice n_sims × n_trades).
- Run sans trade → `MonteCarloError`.

### Stress (`backtest/stress.py`)

- Scénarios constants : fees ×1.5 ; slippage ×2 ; latency +250 ms ; combiné. `stress_test(config, data_root, runs_root)` rejoue `run_backtest` avec les coûts modifiés (seul bloc `costs` touché) → espérance nette par scénario + verdict de survie (espérance > 0).

### Verdict (`backtest/validate.py`)

- `go_no_go(metrics: dict, stress_ok, pct_positive_folds, holdout_attempts) -> Verdict` — critères (défauts du plan §7) :
  - n_trades_oos ≥ 300 ; expectancy_bps > 0 et t_stat ≥ 2 ; profit_factor ≥ 1.2 ; pct_positive_folds ≥ 0.7 ; stress survivant ; max_drawdown ≤ 0.25 (défaut).
  - Chaque critère → (ok, détail) ; GO ssi tous ok ; sérialisé en `validation.json` + tableau HTML.
- Compteur d'essais holdout : `data/holdout_attempts.json` `{count, last_updated}` ; `register_holdout_attempt(config)` incrémente si la période du run intersecte la période holdout déclarée ; corruption/absence → recréé.

### Régimes (`metrics/compute.py` extension)

- `regime_split(equity, close, interval_ns) -> list[RegimeMetrics]` : terciles de volatilité réalisée des rendements (low/mid/high) → total_return, sharpe, max_dd par régime ; trop peu de barres → régime unique.

### CLI

- `tv2 research edge --config <research.yaml>` (signal + horizons + coûts) → tableau texte + `runs/edge-*.json|html`.
- `tv2 backtest sweep --config --grid "window=60..300:60,entry_z=1.5..3.5:0.5"` ; `tv2 backtest walkforward --config --train-bars N --test-bars M` ; `tv2 backtest monte-carlo --run <dir> --sims 1000` ; `tv2 backtest stress --config` ; `tv2 validate --run <dir> --wf <dir>`.

## Backlog TDD (cycles, 1 cycle ≈ 1 commit)

1. `test_signals` — signaux sur barres synthétiques (événements exacts, directions) → `feat: signaux recherche`
2. `test_edge` — forward returns vectorisés + edge_table golden (SC-001) + MFE/MAE → `feat: étude edge`
3. `test_sweep` — grille → runs parallèles déterministes, classement, marque few_trades, heatmap → `feat: sweep grille`
4. `test_walkforward` — folds chronologiques exacts (golden bornes), OOS agrégé, pct positif (SC-003) → `feat: walkforward`
5. `test_montecarlo` — bootstrap golden exact (percentiles recalculés), déterm. graine, erreur sans trade (SC-004) → `feat: monte carlo`
6. `test_stress` — 4 scénarios, coûts seuls modifiés, verdict survie (SC-005 via octet-identique des trades?) → `feat: stress`
7. `test_validate` — verdict golden GO/NO-GO par critère, holdout counter persistant et réparable (SC-006) → `feat: verdict go/no-go`
8. `test_regimes` — terciles sur série connue → `feat: régimes volatilité`
9. `test_cli_validation` — commandes research/sweep/wf/mc/stress/validate (smoke + erreurs propres) → `feat: cli validation`
10. Intégration données réelles (marque `slow`) : edge sur le mois d'août réel < 30 s ; sweep 8 configs < 5 min → `test: validation données réelles`

## Complexity Tracking

Aucune violation de constitution à justifier.