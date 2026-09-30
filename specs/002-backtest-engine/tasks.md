# Tasks: Moteur de backtest événementiel

**Input**: Design documents from `/specs/002-backtest-engine/` (spec.md, plan.md)

**Prerequisites**: plan.md (required), spec.md (required for user stories)

**Tests**: inclus — TDD non négociable (constitution I). Chaque cycle Red→Green→Refactor = un commit.

**Format**: `[ID] [P?] [Story] Description` — **[P]** = parallélisable ; **[Story]** = user story.

## Phase 1: Setup

- [x] T001 Créer les paquets `src/tradingv2/{core,costs,portfolio,execution,strategy,backtest}` avec `__init__.py` (chore)

## Phase 2: Fondations (bloquantes)

- [x] T002 [F] RED `test_rounding` (tick/step vers le bas, minNotional, erreurs) → GREEN `core/rounding.py` → commit `feat: arrondis et filtres`
- [x] T003 [F] RED `test_core_types` (Order/Fill, transitions de statut valides) → GREEN `core/types.py` → commit `feat: types core`
- [x] T004 [F] RED `test_fees` (maker/taker, round_trip_bps entry×exit) → GREEN `costs/fees.py` → commit `feat: grille de frais`
- [x] T005 [F] RED `test_costs_models` (slippage selon côté, latence seedée déterministe) → GREEN `costs/slippage.py`, `costs/latency.py` → commit `feat: modeles de couts`

## Phase 3: US3 — Comptabilité cohérente (P3)

- [x] T006 [US3] RED `test_ledger` (catégories, net = gross − fee − slippage − funding, tolérance 1e-9) → GREEN `portfolio/ledger.py` → commit `feat: registre`
- [x] T007 [US3] RED `test_spot_account` (cycle achat/vente, frais en quote, équité valorisée) → GREEN `portfolio/spot.py` → commit `feat: compte spot`
- [x] T008 [US3] RED `test_margin_account` (position signée, levier, unrealized, funding, liquidation MMR) → GREEN `portfolio/margin.py` → commit `feat: compte perpetuel`

## Phase 4: US2 — Ordres comme Binance (P2)

- [x] T009 [US2] RED `test_order_validation` (tick, step, minNotional → rejets avec raison) → GREEN dans `execution/exchange.py` → commit `feat: validation ordres`
- [x] T010 [US2] RED `test_market_fills_tape` (bon côté, VWAP multi-transactions, frais taker) → GREEN → commit `feat: fills marche tape`
- [x] T011 [US2] RED `test_limit_fills_tape` (pessimiste trade-through / optimiste touch, prix limite, frais maker, post-only rejeté si crossing) → GREEN → commit `feat: fills limite tape`
- [x] T012 [US2] RED `test_stop_fills_tape` (première transaction franchissant, taker) → GREEN → commit `feat: fills stop tape`
- [x] T013 [US2] RED `test_bars_only_fills` (marché = open suivante ± slippage ; limite = touch/trade-through ; stop = gap pessimiste) → GREEN → commit `feat: fills bougies seules`
- [x] T014 [US2] RED `test_predictive_cancel` (annulation avant remplissage planifié → aucun fill ; remplissage déjà arrivé → on_fill) → GREEN → commit `feat: fills predictifs annulables`

**Checkpoint**: l'exchange simulé est complet et testé indépendamment

## Phase 5: US1/US4 — Moteur et API stratégie (P1/P4)

- [x] T015 [US4] RED `test_engine_ordering` (à ts égal : exchange → on_fill → barres → timers) → GREEN `backtest/engine.py` → commit `feat: boucle evenements`
- [x] T016 [US4] RED `test_engine_latency` (soumission à t → inactionnable avant t+latence) → GREEN → commit `feat: latence ordres`
- [x] T017 [US4] RED `test_lookback_antileak` (lookback n = barres clôturées ; troncature des données ⇒ décisions identiques) → GREEN `strategy/base.py` → commit `feat: lookback anti lookahead`
- [x] T018 [US1] RED `test_engine_end` (fin de données : valorisation, on_end, run propre) → GREEN → commit `feat: fin de donnees`

## Phase 6: US6/US5 — Runner, CLI, artefacts

- [ ] T019 [US6] RED `test_backtest_config` (YAML data/account/costs/strategy, erreurs précises) → GREEN `backtest/config.py` → commit `feat: config backtest`
- [ ] T020 [US6] RED `test_runner_recorder` (run sur données de catalogue, artefacts : config résolue, trades, equity, orders, summary, manifeste avec commit git + graines + sha) → GREEN `backtest/runner.py`, `backtest/recorder.py` → commit `feat: artefacts run`
- [ ] T021 [US6] RED `test_backtest_cli` (`tv2 backtest run --config`, exit 2 si config invalide) → GREEN cli → commit `feat: backtest cli`

## Phase 7: Validation du moteur (US1)

- [ ] T022 [US1] RED `test_null_strategy` (stratégie aléatoire seedée : PnL net ≈ −coûts × nb trades, SC-005) → GREEN `strategies/null.py` → commit `test: nullite moteur`
- [ ] T023 [US1] RED `test_trivial_golden` (PnL exact à la main à 1e-9, SC-001 ; 2 runs identiques, SC-002) → GREEN `strategies/trivial.py` → commit `test: golden trivial`
- [ ] T024 [US3] RED `test_ledger_property` (hypothesis : invariants sur séquences de trades aléatoires) → GREEN → commit `test: proprietes registre`
- [ ] T025 [US1] Benchmark (marque `slow`) : 1 mois barres 1s + tape < 10 min (SC-003) → commit `test: benchmark mois`

## Dependencies & Execution Order

- T001 → T002-T005 (fondations) → T006-T008 (comptabilité) → T009-T014 (exchange) → T015-T018 (moteur) → T019-T021 (runner/CLI) → T022-T025 (validation).
- T002-T005 indépendants entre eux (parallélisables) mais précèdent tout le reste.
- Un cycle = un commit ; quality gates verts avant chaque commit (constitution).

## Notes

- Le checkpoint après T014 valide l'exchange en isolation avant le moteur.
- SC-004 (anti-lookahead) est vérifié en T017 puis rejoué sur chaque stratégie de la feature 003.
- Pas de partial fills v1 (spec, hypothèses) ; taille d'ordre ≪ liquidité.