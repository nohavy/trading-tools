# Plan d'implémentation: étude de trend temporel

## Architecture

- `src/tradingv2/research/time_series_trend.py`: calcul pur des expositions, PnL daily (prix + funding − coûts), statistiques et agrégation de portefeuille.
- `scripts/time_series_trend_study.py`: chargement des Parquet journaliers BTC/ETH et funding, grille lookback × mode × coût, comparaison IS/OOS, JSON réutilisable.
- `docs/time-series-trend-2026-10.md`: protocole, résultats, limites et verdict.
- `tests/unit/test_time_series_trend.py`: TDD de la logique métier, sans réseau ni fichiers réels.

## Hypothèses de calcul

1. Signal calculé à la clôture t à partir des seules clôtures ≤ t.
2. Exposition cible constante pendant l'intervalle close[t]→close[t+1] ; les settlements dans cet intervalle s'appliquent à cette exposition et sont valorisés au close 1m terminé avant l'instant de settlement.
3. À chaque clôture, la quantité est ajustée à l'exposition cible (max 1× equity). Le turnover est `abs(qty_target - qty_previous) × close / equity` ; il inclut le flip et le rééquilibrage dû à la dérive de notionnel/equity.
4. PnL journalier = exposition cible × rendement close-close − exposition cible × funding cumulé − turnover × coût total par côté (frais + slippage).
5. `long_short = sign(lookback_return)`, `long_flat = 1 si lookback_return > 0 sinon 0`; buy-and-hold long sert de benchmark.
6. Frais comparés : maker 2 + 1 bps de slippage/côté et taker 5 + 1 bps/côté.
7. IS/OOS reportés sur le PnL complet calculé chronologiquement, après warmup commun par paramètre. OOS n'est pas utilisé pour choisir le paramètre.
8. Métriques quotidiennes : CAGR, rendement total, volatilité annualisée, Sharpe, drawdown max, t-stat Newey-West (lag 20), turnover, temps exposé, funding et frais cumulés.

## Ordre TDD

1. RED/GREEN: expositions long-short et long-flat sans lookahead.
2. RED/GREEN: application close-close, funding horodaté et coût au turnover.
3. RED/GREEN: métriques, warmup et séries de longueur courte.
4. Script de données: smoke sur BTC/ETH, puis grille complète IS/OOS.
5. Rapport français, quality gates, commit.

## Hors périmètre

- Ajouter une stratégie CLI/live ou modifier l'Engine.
- Volatility targeting, stop-loss, indicateurs multiples ou recherche d'un grand nombre de seuils.
- Déduire un GO à partir du backtest vectorisé seul.
