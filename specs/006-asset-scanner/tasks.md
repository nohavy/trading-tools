# Tasks: Scanner d'actifs à fort potentiel

**Input**: Design documents from `/specs/006-asset-scanner/` (spec.md, plan.md)

**Tests**: inclus — TDD non négociable (constitution I) ; rapport en smoke. Un cycle Red→Green→Refactor = un commit.

**Format**: `[ID] [P?] [Story] Description`

## Phase 1: Univers (US1, P1)

- [ ] T001 [US1] RED `test_universe` (filtres exchangeInfo via MockTransport : PERPETUAL + TRADING + USDT uniquement ; persistence horodatée) → GREEN `data/universe.py` → commit `feat: univers perpétuels`

## Phase 2: Métriques + edge par actif (US2/US3, P2/P3)

- [ ] T002 [US2] RED `test_asset_metrics` (goldens synthétiques : vol 1m/1h, liquidité journalière, fréquence de cassures, funding None, marque dead) → GREEN `research/asset_metrics.py` → commit `feat: métriques d'actif`
- [ ] T003 [US3] RED `test_asset_edge` (edge par actif : signaux existants, score max à l'horizon cible, edge net vs maker, marque peu de trades) → GREEN `research/scan.py::asset_edge` → commit `feat: edge par actif`

## Phase 3: Orchestration + rapport (US4, P4)

- [ ] T004 [US4] RED `test_scan` (E2E synthétique : univers 4 actifs, 1 mort, 1 défaillant, 2 bons ; snapshot isolé par symbole ; classement déterministe ; rapport autonome ; candidats exportés) → GREEN `research/scan.py::run_scan` → commit `feat: orchestration scan`
- [ ] T005 [US4] RED `test_cli_scan` (smoke `tv2 scan universe/snapshot/run`, erreurs propres) → GREEN cli → commit `feat: cli scan`

## Phase 4: Réel

- [ ] T006 [US1] `slow` scan réel : univers réel, instantané ~100 actifs top volume, scan complet, candidats exportés → commit `test: scan réel`
- [ ] T007 [US3] Validation des 3-5 meilleurs candidats par la chaîne existante (backtest → WF → stress → verdict) + docs → commit `docs: candidats du scan`

## Dependencies & Execution Order

- T001 → T002/T003 (indépendants entre eux) → T004 → T005 → T006 → T007.

## Notes

- Le scan ne VALIDE rien : il désigne. Le verdict reste la chaîne des features 003/004.
- Isolation des erreurs par actif : jamais un crash global (FR-008).