# Implementation Plan: Stratégie funding-momentum

**Branch**: `005-funding-momentum` | **Date**: 2026-09-30 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/005-funding-momentum/spec.md`

## Summary

Hook `on_funding` dans le moteur (délivrance des échéances à la stratégie), stratégie `FundingMomentum` (percentile roulant des N dernières échéances, entrée à l'achat au franchissement, hold fixe, une position à la fois), puis validation complète : run 6 mois 1m UM, walk-forward, stress, verdict.

## Technical Context

**Language/Version**: Python 3.12 (uv) — existant

**Primary Dependencies**: numpy (percentile roulant), polars (données 1m + funding) — existants

**Storage**: runs/ standard (feature 003) ; données funding 6 mois déjà en catalogue

**Testing**: pytest — goldens synthétiques (taux connus), puis données réelles

**Target Platform**: Linux CLI

**Performance Goals**: run 6 mois 1m (~265k barres + 552 échéances) < 10 s

**Constraints**: déterminisme ; une position à la fois ; percentile calculé UNIQUEMENT sur les échéances passées (anti-lookahead)

**Scale/Scope**: 1 stratégie + 1 hook moteur + la chaîne de validation existante

## Constitution Check

| Principe | Statut | Note |
|---|---|---|
| I. Test-First | PASS | Cycles ci-dessous |
| II. Réalisme économique | PASS | Frais maker×maker de référence ; stress complet avant verdict |
| III. Anti-lookahead | PASS | Le percentile roulant ne voit que les échéances passées (testé) ; folds chronologiques |
| IV. Un code, trois exécutions | PASS | La stratégie passe par l'API Context standard |
| V. Simplicité | PASS | Aucun nouveau concept : un hook, une stratégie, la chaîne existante |

## Contrats techniques

### Hook moteur (`backtest/engine.py`)

- `Strategy.on_funding(ctx, rate: float)` : appelé à chaque échéance, APRÈS l'application comptable (le compte est à jour), AVANT la barre de clôture à l'instant égal (priority 1, seq avant les barres — déjà l'ordre).
- Le Context expose `now_ns` (déjà) ; la stratégie n'a pas besoin de plus.

### Stratégie (`strategies/funding.py`)

- `FundingMomentum(window_events: int = 250, threshold_pct: float = 90, hold_bars: int = 1440, qty: float = 0.002)` :
  - on_funding : ajoute le taux à l'historique (numpy array, taille window_events max) ; si len ≥ min_history (window_events // 2) et flat : seuil = percentile(threshold_pct) de l'historique ; si rate ≥ seuil ET rate > 0 : entrée BUY au marché (submitted à l'instant de l'échéance).
  - on_bar : compte les barres ; sortie au marché après hold_bars.
  - Une position à la fois (position_qty check).
  - Le percentile roulant : `np.percentile(historique, threshold_pct)` — anti-lookahead par construction (l'historique ne contient que les taux déjà vus, l'échéance courante incluse? DÉCISION : incluse — le taux courant fait partie du crowding observé; documenté).

### Validation (`tests/integration/test_funding_momentum_validation.py`, marque slow)

- Run 6 mois (config 1m UM BTC + funding) : métriques, round trips.
- Walk-forward : `train_bars`/`test_bars` en barres 1m (ex. 30 j train / 15 j test), grille sur `threshold_pct` et `hold_bars`.
- Stress : les 4 scénarios.
- Verdict : `go_no_go` avec les métriques OOS agrégées + folds + stress.

## Backlog TDD (cycles)

1. `test_engine_funding_hook` — RED : stratégie sonde reçoit les taux exacts en ordre ; compte débité → GREEN → `feat: hook on_funding`
2. `test_strategy_funding_momentum` — RED : entrée au franchissement du percentile roulant (taux synthétiques), hold, une position, pas d'entrée sans historique suffisant → GREEN → `feat: stratégie funding-momentum`
3. `test_funding_validation_real` — RED/slow : run 6 mois réel + walk-forward + stress + verdict structuré → GREEN → `test: validation funding-momentum`
4. Docs : mise à jour AGENTS.md (usage) + docs/edge-analysis (confirmation) → `docs: validation funding-momentum`

## Complexity Tracking

Aucune violation de constitution à justifier.