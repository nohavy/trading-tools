# Tasks: Étude d'edge et validation des stratégies

**Input**: Design documents from `/specs/004-edge-validation/` (spec.md, plan.md)

**Tests**: inclus — TDD non négociable (constitution I) ; rapports HTML en smoke. Un cycle Red→Green→Refactor = un commit.

**Format**: `[ID] [P?] [Story] Description`

## Phase 1: Edge (US1, P1)

- [ ] T001 [US1] RED `test_signals` (meanrev/breakout/flow sur barres synthétiques : instants et directions exacts) → GREEN `research/signals.py` → commit `feat: signaux recherche`
- [ ] T002 [US1] RED `test_edge` (forward returns vectorisés, edge_table golden SC-001, MFE/MAE, verdict edge−coût, zéro événement propre) → GREEN `research/edge.py` → commit `feat: étude edge`

## Phase 2: Sweep (US2, P2)

- [ ] T003 [US2] RED `test_sweep` (grille générée, runs parallèles déterministes, classement par espérance, marque few_trades, heatmap HTML) → GREEN `backtest/sweep.py` → commit `feat: sweep grille`

## Phase 3: Walk-forward (US3, P3)

- [ ] T004 [US3] RED `test_walkforward` (bornes des folds golden sans recouvrement, meilleur param par train, OOS agrégé, pct folds positifs, erreur si période trop courte) → GREEN `backtest/walkforward.py` → commit `feat: walkforward`

## Phase 4: Monte Carlo + stress (US4/US5, P4/P5)

- [ ] T005 [US4] RED `test_montecarlo` (bootstrap golden exact, graine déterministe, proba DD, erreur sans trade) → GREEN `backtest/montecarlo.py` → commit `feat: monte carlo`
- [ ] T006 [US5] RED `test_stress` (4 scénarios : coûts seuls modifiés, espérance par scénario, verdict survie) → GREEN `backtest/stress.py` → commit `feat: stress`

## Phase 5: Verdict + régimes (US6/US7, P6/P7)

- [ ] T007 [US6] RED `test_validate` (golden GO/NO-GO critère par critère, holdout_attempts persistant/réparable) → GREEN `backtest/validate.py` → commit `feat: verdict go/no-go`
- [ ] T008 [US7] RED `test_regimes` (terciles sur série connue, régime unique si peu de barres) → GREEN `metrics/compute.py` → commit `feat: régimes volatilité`

## Phase 6: CLI + validation réelle

- [ ] T009 [US6] RED `test_cli_validation` (research edge, sweep, walkforward, monte-carlo, stress, validate : options, erreurs propres) → GREEN cli → commit `feat: cli validation`
- [ ] T010 Intégration données réelles (`slow`) : edge mois réel < 30 s ; sweep 8 configs < 5 min ; verdict sur un run réel → commit `test: validation données réelles`
- [ ] T011 Docs : quickstart validation dans docs/plan.md + AGENTS.md → commit `docs: usage validation`

## Dependencies & Execution Order

- T001 → T002 (les signaux alimentent l'edge) → T003 → T004 → T005/T006 → T007/T008 → T009 → T010 → T011.
- T005/T006 indépendants (parallélisables). T007/T008 indépendants.
- Le sweep/walkforward réutilisent run_backtest (feature 003) : aucune modification du moteur.

## Notes

- Le verdict n'est calculé que sur des données hors-échantillon (folds de test ou holdout) — jamais sur le train.
- Le compteur d'essais rend le sur-ajustement visible : il ne bloque pas, il rapporte.