# Tasks: Stratégies, métriques et rapport

**Input**: Design documents from `/specs/003-strategies-metrics-report/` (spec.md, plan.md)

**Tests**: inclus — TDD non négociable (constitution I) ; rendu HTML en smoke assertions (exception validée). Un cycle Red→Green→Refactor = un commit.

**Format**: `[ID] [P?] [Story] Description`

## Phase 1: Fondations indicateurs (US1, P1)

- [x] T001 [US1] RED `test_features_vectorized` (goldens EMA, zscore, vwap session, realized_vol, flow_imbalance ; fenêtre non pleine → NaN) → GREEN `features/vectorized.py` → commit `feat: indicateurs vectorisés`
- [x] T002 [US1] RED `test_features_incremental` (classes pas à pas, mêmes goldens, None tant que non défini) → GREEN `features/incremental.py` → commit `feat: indicateurs incrémentaux`
- [x] T003 [US1] RED `test_features_parity` (hypothesis + mois réel : lot == pas à pas à 1e-9) → GREEN → commit `test: parité indicateurs`

## Phase 2: Moteur — funding + registre (rattrapage US3)

- [x] T004 [US3] RED `test_engine_funding` (funding events → apply_funding sur margin ; round trips détectés ; ledger.record_trade à la fermeture ; EngineResult.round_trips + ledger_totals) → GREEN `backtest/engine.py` → commit `feat: funding et registre moteur`

## Phase 3: Métriques (US3, P3)

- [x] T005 [US3] RED `test_metrics` (golden à la main : total_return, sharpe, sortino, max_dd, calmar, win_rate, payoff, PF, expectancy_bps, hold, coûts, drag, t_stat) → GREEN `metrics/compute.py` → commit `feat: métriques`
- [x] T006 [US3] RED `test_metrics_edge` (zéro trade, PF infini → None, variance nulle → None, dd nul) → GREEN → commit `test: métriques dégénérées`

## Phase 4: Stratégies (US2, P2)

- [x] T007 [US2] RED `test_strategies_meanrev` (entrée z extrême, sortie retour, stop, max_hold ; une position à la fois) → GREEN `strategies/meanrev.py` → commit `feat: stratégie meanrev`
- [x] T008 [US2] RED `test_strategies_breakout` (cassure + volume confirmé, symétrie short) → GREEN `strategies/breakout.py` → commit `feat: stratégie breakout`
- [x] T009 [US2] RED `test_strategies_flow` (déséquilibre ≥/≤ seuil) → GREEN `strategies/flow.py` → commit `feat: stratégie orderflow`
- [x] T010 [US2] RED `test_strategies_buyhold` + registre des 4 → GREEN `strategies/builtin.py` → commit `feat: stratégie buy_hold et registre`

## Phase 5: Rapport (US4, P4)

- [x] T011 [US4] RED `test_report_render` (sections présentes, autonomie sans ressource externe, < 2 Mo, déterministe, « aucun trade ») → GREEN `report/render.py` → commit `feat: rapport html`

## Phase 6: Comparaison (US5, P5)

- [x] T012 [US5] RED `test_report_compare` (tableau N runs, HTML) → GREEN `report/compare.py` → commit `feat: comparaison runs`
- [x] T013 [US5] RED `test_cli_compare` (`tv2 compare r1 r2`) → GREEN cli → commit `feat: cli comparaison`

## Phase 7: Branchement + validation

- [x] T014 [US4] RED `test_runner_report` (run_backtest génère metrics.json + report.html) → GREEN `backtest/runner.py` → commit `feat: run génère métriques et rapport`
- [x] T015 [US1] Benchmark SC-005 : run + rapport mois réel < 60 s (marque `slow`) → commit `test: benchmark run rapport`

## Dependencies & Execution Order

- T001-T003 (indicateurs) précèdent T007-T010 (stratégies qui les utilisent).
- T004 (moteur) précède T005-T006 (métriques consomment les round trips).
- T005-T006 précèdent T011-T013 (rapport/compare lisent metrics.json).
- T014-T015 finalisent le branchement.

## Notes

- La parité (T003) est le contrat de la constitution IV : à rejouer sur toute nouvelle feature d'indicateur.
- Le budget SVG < 2 Mo rend le rapport archivable avec chaque run.