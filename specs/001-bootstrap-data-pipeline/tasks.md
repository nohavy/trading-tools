# Tasks: Socle et pipeline de données historiques Binance

**Input**: Design documents from `/specs/001-bootstrap-data-pipeline/` (spec.md, plan.md)

**Prerequisites**: plan.md (required), spec.md (required for user stories)

**Tests**: inclus — TDD non négociable (constitution I). Chaque cycle Red→Green→Refactor = un commit.

**Format**: `[ID] [P?] [Story] Description` — **[P]** = parallélisable (fichiers différents) ; **[Story]** = user story.

## Phase 1: Setup (Infrastructure partagée)

**Purpose**: socle projet sans logique métier (hors TDD, config uniquement)

- [ ] T001 Créer `pyproject.toml` (nom `tradingv2`, Python 3.12, script `tv2`, deps : typer, rich, pydantic, polars, pyarrow, numpy, httpx, pyyaml ; dev : pytest, pytest-cov, hypothesis, ruff, mypy) + config ruff/mypy/pytest (marque `net`)
- [ ] T002 Créer `src/tradingv2/__init__.py`, `tests/conftest.py`, dossiers `tests/{unit,integration,fixtures}`, `configs/`
- [ ] T003 `uv sync` et vérifier `uv run pytest`, `uv run ruff check`, `uv run mypy` verts sur squelette vide

**Checkpoint**: environnement installé, quality gates opérationnels

---

## Phase 2: Foundational (prérequis bloquants) — US6

**Purpose**: CLI + config, base de toutes les stories

- [ ] T004 [US6] RED `tests/unit/test_cli.py` : `tv2 --help` exit 0 ; commandes `data`, `research`, `backtest`, `compare` listées → GREEN `src/tradingv2/cli.py` minimal (stubs) → commit `feat: cli tv2`
- [ ] T005 [US6] RED `tests/unit/test_config.py` : YAML valide chargé, champ inconnu/type erroné → erreur localisant le champ → GREEN `src/tradingv2/config.py` (pydantic) → commit `feat: chargement config yaml`
- [ ] T006 [US6] Câbler `--config` dans la CLI + fixture `configs/reference.yaml` → commit `feat: config cli`

**Checkpoint**: `tv2 --help` et config OK — les stories données peuvent démarrer

---

## Phase 3: US1 — Téléchargement vérifié (P1) 🎯 MVP

**Goal**: obtenir des données Binance vérifiées, converties et cataloguées via une commande

**Independent Test**: `uv run tv2 data download --market spot --symbol BTCUSDT --type klines --interval 1s --start 2026-08-01 --end 2026-08-31` sur fixtures locales

- [ ] T007 [US2] RED `test_normalize_ts.py` (ms/µs/ns → ns, hors plage → erreur) → GREEN `data/convert.py` → commit `feat: normalisation timestamps`
- [ ] T008 [US2] RED `test_parse_klines.py` (12 col, en-tête auto, erreur fichier+ligne) → GREEN parseur klines → commit `feat: parseur klines`
- [ ] T009 [US2] RED `test_parse_aggtrades.py` (spot 8 col / um 7 col, booléens true/false/True/False) → GREEN parseur aggTrades → commit `feat: parseur aggtrades`
- [ ] T010 [US1] RED `test_build_archive_url.py` (golden strings spot/um × daily/monthly × klines/aggTrades/fundingRate) → GREEN `data/sources.py` → commit `feat: urls data binance`
- [ ] T011 [US1] RED `test_download_plan.py` (mensuel si mois complet écoulé, journalier sinon, bornes incluses, déterministe via `today`) → GREEN `data/plan.py` → commit `feat: plan téléchargement`
- [ ] T012 [US1] RED `test_checksum.py` (ok/ko/absent/casse) → GREEN verify_checksum → commit `feat: verification checksum`
- [ ] T013 [US1] RED `test_downloader.py` (MockTransport : `.part` + renommage atomique, reprise, skip si valide, backoff 429/5xx seedé) → GREEN `data/download.py` → commit `feat: downloader`
- [ ] T014 [US1] RED `test_store_catalog.py` (roundtrip parquet zstd, schéma exact, catalogue idempotent) → GREEN `data/store.py` → commit `feat: stockage parquet catalogue`
- [ ] T015 [US1] Câbler `tv2 data download` (plan → download → convert → store → catalog, concurrence max 4) + fixture `configs/download-spot-1s.yaml` → commit `feat: data download cli`
- [ ] T016 [US1] Smoke test CLI E2E (serveur local fixtures) → commit `test: cli data smoke`

**Checkpoint**: US1+US2 fonctionnelles — mois de données spot 1s téléchargeable et converti

---

## Phase 4: US3 — Contrôle qualité (P3)

- [ ] T017 [US3] RED `test_quality.py` (anomalies injectées : trou, doublon, non-monotone, high<low, prix aberrant ; dataset sain → 0 anomalie) → GREEN `data/quality.py` → commit `feat: data check`
- [ ] T018 [US3] Câbler `tv2 data check` (rapport, exit 1 si anomalies) → commit `feat: data check cli`

**Checkpoint**: qualité vérifiable en une commande

---

## Phase 5: US4 — Instruments et funding (P4)

- [ ] T019 [US4] RED `test_instruments.py` (golden exchangeInfo BTCUSDT spot+um ; MockTransport) → GREEN `data/instruments.py` → commit `feat: instruments`
- [ ] T020 [US4] RED `test_funding.py` (golden fundingRate mensuel BTCUSDT) → GREEN `data/funding.py` → commit `feat: funding`
- [ ] T021 [US4] Câbler `tv2 data instruments` (affichage + stockage) → commit `feat: instruments cli`

**Checkpoint**: règles d'exchange et funding prêts pour la feature 002

---

## Phase 6: US5 — Resample (P5)

- [ ] T022 [US5] RED `test_resample.py` (golden 1s→5s et 1s→1m, volumes taker agrégés, barre partielle rejetée) → GREEN `data/resample.py` → commit `feat: resample`

**Checkpoint**: résolutions arbitraires disponibles

---

## Phase 7: Intégration réseau + polish

- [ ] T023 [P] `tests/integration/test_net_download.py` (@net) : 1 jour réel spot 1s BTCUSDT ≈ 86 400 lignes, checksum OK → commit `test: net telechargement`
- [ ] T024 Validation SC (temps download, temps check, idempotence) sur le jeu réel d'août 2026 → commit `chore: validation sc`
- [ ] T025 Docs : quickstart dans `docs/plan.md` ou README + mise à jour AGENTS.md si besoin → commit `docs: quickstart`

## Dependencies & Execution Order

- Setup (T001-T003) → Foundational (T004-T006) → US1/US2 (T007-T016) → US3 (T017-T018) → US4 (T019-T021) → US5 (T022) → Network/polish (T023-T025).
- T007-T009 (normalisation + parseurs) précèdent T015 (conversion dans le pipeline). T010-T013 indépendants deux à deux, mais tous précèdent T015.
- Un seul développeur : ordre strict par numéros de tâches.

## Notes

- Vérifier que chaque test échoue pour la bonne raison avant d'implémenter (constitution I).
- Les golden fixtures (`tests/fixtures/`) sont figées une fois, jamais régénérées à la main.
- Stop & valider à chaque checkpoint.