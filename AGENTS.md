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

## Usage validation (feature 004)

- `uv run tv2 research edge --config configs/edge-meanrev.yaml` — rendements après signal vs coûts, par horizon (filtre pré-backtest).
- `uv run tv2 backtest sweep --config configs/backtest.yaml --grid "window=60..300:60"` — grille en parallèle, classement par espérance nette, heatmap.
- `uv run tv2 backtest walkforward --config ... --grid ... --train-bars N --test-bars M` — folds chronologiques, agrégat OOS, % folds positifs.
- `uv run tv2 backtest monte-carlo runs/<id> --sims 1000` — percentiles du PnL final, proba de drawdown.
- `uv run tv2 backtest stress --config ...` — frais ×1,5 / slippage ×2 / latence +250 ms / combiné.
- `uv run tv2 validate run runs/<id>` — verdict go/no-go (7 critères) ; compteur d'essais holdout dans `data/holdout_attempts.json`.

## Usage données (feature 001)

- `uv run tv2 data download --config configs/reference.yaml` — télécharge + convertit (Parquet ns) + catalogue (`data/catalog.json`) ; idempotent.
- `uv run tv2 data check --config configs/reference.yaml` — contrôle qualité (trous, doublons, OHLC, outliers) ; exit 1 si anomalies.
- `uv run tv2 data instruments --market spot --symbol BTCUSDT` — règles de trading (tick, step, minNotional) persistées dans `data/instruments/`.
- Configs de référence dans `configs/` : `reference.yaml` (spot 1s), `download-um-1m.yaml` (futures : 1m minimum, pas de klines 1s), `download-*-aggtrades.yaml`, `funding-um-btc.yaml`.

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