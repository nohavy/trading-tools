# tradingv2 — Constitution

## Core Principles

### I. Test-First (NON NÉGOCIABLE)

Toute la logique métier (`core`, `data`, `costs`, `execution`, `portfolio`, `strategy`, `risk`, `features`, `metrics`, `backtest`, `research`) est développée en TDD strict : cycle Red → Green → Refactor, un cycle = un commit. Un test doit être vu échouer pour la bonne raison avant d'écrire le code qui le fait passer. Exceptions pragmatiques validées : câblage CLI, rendu HTML, téléchargement réseau brut → smoke tests + revue. Une phase ne démarre que si sa spécification est écrite et relue.

### II. Réalisme économique avant tout

Aucune stratégie n'est validée sans modélisation complète des coûts : frais maker/taker, spread, slippage, latence, funding. La seule métrique qui compte est le net après frais. L'étude d'edge vs coûts précède tout backtest complet.

### III. Anti-lookahead et déterminisme (NON NÉGOCIABLE)

Aucune décision ne peut dépendre de données postérieures à l'instant t : barres clôturées uniquement, latence appliquée aux ordres, ordre de traitement interne strict (exchange → fills → stratégie) à timestamp égal. Deux exécutions avec les mêmes graines produisent des résultats identiques. Toute régression sur ces points est bloquante.

### IV. Un seul code, trois exécutions

Le même code de stratégie tourne en backtest, en paper et en live ; seule l'implémentation de l'exchange change. Les features existent en version vectorisée (recherche) et incrémentale (temps réel), avec parité testée entre les deux.

### V. Simplicité et conventions

Timestamps int64 nanosecondes UTC partout ; prix et quantités arrondis aux filtres de l'exchange ; documentation et commits en français, code en anglais ; YAGNI — aucune optimisation (numba, etc.) sans benchmark qui la justifie.

## Quality Gates

- `uv run pytest`, `uv run ruff check`, `uv run mypy` verts à chaque cycle, avant tout commit.
- Couverture ≥ 95 % sur `core/costs/data`, ≥ 90 % global.
- Aucun réseau ni donnée réelle dans les tests unitaires (marque `net` pour l'intégration).
- Go/no-go explicite (critères de la phase 4, voir `docs/plan.md`) avant tout passage au réel ; capital réel seulement après paper trading concluant.

## Governance

La constitution prime sur toute autre pratique. Tout amendement est documenté, motivé et validé explicitement avec l'utilisateur. `AGENTS.md` fait foi pour le quotidien (commandes, conventions) ; `docs/plan.md` est le plan de référence.

**Version**: 1.0.0 | **Ratified**: 2026-09-30 | **Last Amended**: 2026-09-30