# Tasks: Stratégie funding-momentum

**Input**: Design documents from `/specs/005-funding-momentum/` (spec.md, plan.md)

**Tests**: inclus — TDD non négociable (constitution I). Un cycle Red→Green→Refactor = un commit.

## Phase 1: Hook moteur

- [ ] T001 [US1] RED `test_engine_funding_hook` (sonde : taux exacts en ordre ; compte perp débité/crédité ; spot ignore comptablement mais reçoit l'événement) → GREEN `backtest/engine.py` → commit `feat: hook on_funding`

## Phase 2: Stratégie

- [ ] T002 [US2] RED `test_strategy_funding_momentum` (percentile roulant, entrée au franchissement, hold fixe, une position, historique court = pas d'entrée) → GREEN `strategies/funding.py` + registre → commit `feat: stratégie funding-momentum`

## Phase 3: Validation réelle (slow)

- [ ] T003 [US3] RED/`slow` `test_funding_validation_real` (run 6 mois 1m UM BTC : round trips, métriques ; walk-forward 30j/15j grille threshold_pct×hold_bars ; stress 4 scénarios ; verdict critère par critère) → GREEN → commit `test: validation funding-momentum`

## Phase 4: Docs

- [ ] T004 [US3] AGENTS.md usage + mise à jour docs/edge-analysis-2026-08.md (confirmation) → commit `docs: funding-momentum validé`
