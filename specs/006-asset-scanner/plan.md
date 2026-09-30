# Implementation Plan: Scanner d'actifs à fort potentiel

**Branch**: `006-asset-scanner` | **Date**: 2026-09-30 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/006-asset-scanner/spec.md`

## Summary

Chaîne de découverte d'opportunités : univers des perpétuels USDⓈ-M (exchangeInfo), instantané de données (1 mois de bougies 1m + funding par actif), métriques de potentiel par actif, passage d'edge rapide des signaux connus (cassure, meanrev, flux) face aux coûts maker, classement final en rapport autonome avec liste exportée de candidats pour la chaîne de validation existante.

## Technical Context

**Language/Version**: Python 3.12 (uv) — existant

**Primary Dependencies**: polars + numpy (métriques/edge), httpx (exchangeInfo), jinja2 (rapport), concurrent.futures (parallélisme du snapshot) — existants

**Storage**: `data/scan/universe.json` (instantané de l'univers) ; les données par actif vont au layout standard du catalogue ; rapports dans `runs/scan-*.html` + `scan-candidates-*.json`

**Testing**: pytest — goldens synthétiques (univers, métriques, edge), MockTransport (exchangeInfo), scan E2E sur 3-5 symboles synthétiques dont un mort et un défaillant

**Target Platform**: Linux CLI, 12 cœurs

**Performance Goals**: SC-001 instantané 200+ actifs < 60 min ; SC-002 scan < 10 min

**Constraints**: isolation des erreurs par actif (FR-008) ; RAM — un actif à la fois (44k barres 1m)

**Scale/Scope**: ~300 perpétuels UM ; 1 fenêtre mensuelle ; 3 signaux × 3 horizons par actif

## Constitution Check

| Principe | Statut | Note |
|---|---|---|
| I. Test-First | PASS | Cycles ci-dessous ; rapport en smoke |
| II. Réalisme économique | PASS | L'edge est mesuré net des coûts maker ; les candidats alimentent la chaîne de validation (jamais directement le réel) |
| III. Anti-lookahead / déterminisme | PASS | Les signaux/forward returns existants réutilisés tels quels ; classement déterministe |
| IV. Un code, trois exécutions | N/A | Recherche uniquement |
| V. Simplicité | PASS | Réutilise universement le downloader, les signaux, l'edge et le rapport existants |

## Project Structure

```text
src/tradingv2/
├── data/universe.py        # exchangeInfo → perpétuels UM négociables USDT
├── research/asset_metrics.py  # métriques par actif (vol, liquidité, cassures, funding, régimes)
├── research/scan.py        # orchestration : univers → snapshot → métriques → edge → rapport
└── cli.py                  # tv2 scan universe / snapshot / run
tests/unit/test_{universe,asset_metrics,asset_edge,scan,cli_scan}.py
tests/integration/test_scan_real.py (slow)
configs/scan.yaml
```

## Contrats techniques

### Univers (`data/universe.py`)

- `fetch_universe(client) -> list[dict]` : GET fapi exchangeInfo (existante) ; filtres : `contractType == "PERPETUAL"`, `status == "TRADING"`, `quoteAsset == "USDT"` ; sortie : symbole + tick/step/minNotional.
- Persisté dans `data/scan/universe.json` (horodaté).

### Métriques d'actif (`research/asset_metrics.py`)

- `asset_metrics(bars: pl.DataFrame, funding: pl.DataFrame | None, config) -> dict` :
  - `vol_bps_1m` : std des rendements 1m × 1e4 ; `vol_bps_1h` : idem sur bougies agrégées 60×1m.
  - `quote_volume_daily`, `n_trades_daily` : moyennes journalières.
  - `breakout_freq` : événements de cassure (signal existant, fenêtre 30, volume_factor 2) par jour.
  - `funding_mean_bps`, `funding_p95_bps` : None si funding absent.
  - `dead: bool` : volume notionnel journalier sous le seuil paramétrable OU moins de 20 jours de données.
  - Testable golden sur séries synthétiques.

### Edge par actif (réutilisation)

- Par actif : les 3 signaux aux défauts de l'analyse (breakout lb30 vf5, meanrev w120 z2.5, flow w120 th0.5), horizons [60 s, 300 s, 900 s], paire d'ordres maker×maker (4 bps).
- `asset_edge(bars, config) -> dict` : par signal `{mean_bps, hit_rate}` à l'horizon cible (300 s) + `score_bps = max(signaux)` + `edge_net_bps = score - coût`.
- Aucun nouveau code d'edge : `edge_table` et les signaux existants sont appelés tels quels.

### Orchestration (`research/scan.py`)

- `run_scan(config_path, data_root, runs_root, *, workers) -> Path` (rapport) :
  1. univers (cache `data/scan/universe.json` si récent, sinon fetch) ;
  2. snapshot : pour chaque symbole, pipeline de téléchargement existant (bougies 1m du mois précédent + funding) — try/except par symbole, écarts résumés ;
  3. métriques + edge par actif (try/except, actifs morts marqués) ;
  4. classement par edge net décroissant, rapport autonome (template `scan.html.j2`), candidats exportés (`edge_net > seuil`, actifs vivants, trades suffisants) en `scan-candidates-*.json`.
- Config scan YAML : `{data: {interval, start, end}, scan: {cost_pair: {maker_bps, taker_bps}, target_horizon_s, threshold_edge_bps, min_quote_volume_daily, min_trades}}`.

### CLI

- `tv2 scan universe` (liste + persistence) ; `tv2 scan snapshot --config` (téléchargement de l'instantané) ; `tv2 scan run --config` (métriques + edge + rapport ; suppose l'instantané présent).

## Backlog TDD (cycles)

1. `test_universe` — filtres exchangeInfo via MockTransport (perpétuels USDT négociables uniquement), persistence → `feat: univers perpétuels`
2. `test_asset_metrics` — goldens synthétiques (vol 1m/1h, liquidité, cassures, funding None, marque dead) → `feat: métriques d'actif`
3. `test_asset_edge` — edge par actif sur forward connu, score/max, marque peu de trades → `feat: edge par actif`
4. `test_scan` — orchestration E2E synthétique (4 actifs : 1 mort, 1 défaillant, 2 bons) → rapport, candidats, survie aux erreurs, classement déterministe → `feat: orchestration scan`
5. `test_cli_scan` — smoke des 3 commandes + erreurs propres → `feat: cli scan`
6. `test_scan_real` (slow) — univers réel, instantané top volume (~100 actifs), scan complet, candidats réels → `test: scan réel`
7. Docs — AGENTS.md usage scan + docs/edge-analysis (suite) → `docs: scan`

## Complexity Tracking

Aucune violation de constitution à justifier.