# AGENTS.md — tradingv2

Outil de microtrading crypto (Binance spot + futures USDⓈ-M). Backtest réaliste d'abord ; temps réel, paper et live ensuite.

Références : `.specify/memory/constitution.md` (principes — prime sur tout) et `docs/plan.md` (plan validé).

## Commandes

- `uv run pytest` — tests (tout doit être vert avant commit)
- `uv run pytest -m "not net"` — sans les tests réseau
- `uv run pytest -m net` — intégration réseau uniquement
- `uv run ruff check` — lint
- `uv run mypy` — vérification des types
- `uv run tv2 --help` — CLI du projet

## Workflow

- Spec Kit : une feature = `specs/NNN-nom/` avec `spec.md` (QUOI) → `plan.md` (COMMENT) → `tasks.md` (checklist) → implémentation TDD.
- TDD strict sur la logique métier ; smoke tests pour CLI, rendu HTML et téléchargement réseau. Un cycle Red→Green→Refactor = un commit.
- Commits conventionnels en français : `test:`, `feat:`, `refactor:`, `fix:`, `docs:`, `chore:`.
- Une phase ne démarre pas sans spec relue ; les critères de réussite sont mesurables.

## Conventions

- Docs et commits en français ; code en anglais (identifiants, docstrings, messages d'erreur et logs).
- Timestamps int64 nanosecondes UTC en interne. Prix/quantités arrondis aux filtres d'exchange (tick, step, minNotional).
- Pas de secrets dans le repo ; clés API uniquement pour le live, jamais versionnées.
- `data/` (données brutes et Parquet) et `runs/` (résultats de backtests) sont ignorés par git.

## Layout (cible)

- `src/tradingv2/` : `core` (types), `data` (téléchargement, catalogue, qualité), `features`, `costs`, `execution`, `portfolio`, `strategy`, `strategies`, `risk`, `backtest`, `research`, `metrics`, `report`, `cli.py`
- `tests/` : `unit/`, `property/`, `integration/` (marque `net`), `fixtures/`
- `configs/` : YAML (fees, instruments, backtests) ; `docs/` ; `specs/` (Spec Kit)