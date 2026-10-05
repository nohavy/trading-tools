# Plan d'implémentation: validation événementielle du trend temporel

## Architecture

- `src/tradingv2/strategies/time_series_trend.py`: stratégie trend sur clôtures daily extraites des barres 1m; modes `long_flat` et `buy_hold`.
- `src/tradingv2/execution/exchange.py`: vérification de marge corrigée pour les ordres qui réduisent/ferment une position existante.
- `src/tradingv2/strategies/builtin.py`: enregistrement sous `time_series_trend`.
- `configs/research-trend-{btc,eth}.yaml`: configuration reproductible OOS, 1m, capital et coûts identiques.
- `scripts/run_trend_engine_validation.py`: exécute les deux configs et résume l'equity au pas daily sur l'OOS.
- `tests/unit/test_strategy_time_series_trend.py`: TDD de timing, warmup, ordres pending et benchmark.
- `docs/time-series-trend-2026-10.md`: append les résultats événementiels au screening vectorisé.

## Hypothèses d'exécution

1. La clôture daily est la barre 1m close dont `ts_close_ns % 86_400e9 == 0`.
2. Une décision après la clôture ne peut être remplie avant la barre 1m suivante.
3. L'entrée long/flat vise au plus 1× equity, quantifiée par l'exchange; la quantité reste fixe jusqu'à la sortie.
4. `trade_start_ns` interdit les entrées avant le début OOS tout en conservant les clôtures daily de warmup.
5. Benchmark buy-and-hold: même capital initial, frais, slippage, latence, funding et timestamp d'entrée.
6. Les résultats OOS 2023-07..2026-08 ont déjà été consultés au niveau vectoriel: ils servent à tester la fidélité d'exécution, pas à revendiquer une validation holdout.

## Ordre TDD

1. RED/GREEN: signal daily, warmup et absence de lookahead sur moteur synthétique.
2. RED/GREEN: soumission/fill/exit, gestion pending/rejet, début OOS et benchmark.
3. Runner/configs BTC et ETH sur 1m avec funding réel.
4. Agrégation equity quotidienne OOS et comparaison équitable.
5. Rapport, quality gates, verdict prudent.

## Hors périmètre

- Optimiser de nouveaux lookbacks sur cette période ou changer le signal après lecture des résultats moteur.
- Paper/live, levier >1, volatility targeting ou stop-loss.
- Qualifier le résultat de holdout indépendant ou de GO.
