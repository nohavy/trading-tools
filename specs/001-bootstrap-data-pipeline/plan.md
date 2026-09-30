# Implementation Plan: Socle et pipeline de données historiques Binance

**Branch**: `001-bootstrap-data-pipeline` | **Date**: 2026-09-30 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-bootstrap-data-pipeline/spec.md`

## Summary

Socle du projet (uv, CLI `tv2`, config YAML validée) et pipeline de données historiques Binance : téléchargement depuis data.binance.vision avec vérification SHA256 et reprise, normalisation des horodatages en nanosecondes UTC, stockage Parquet au schéma canonique, catalogue idempotent, contrôle qualité, règles d'instruments, funding des perpétuels et regroupement de résolution.

## Technical Context

**Language/Version**: Python 3.12 (géré par uv 0.12.18)

**Primary Dependencies**: typer+rich (CLI), pydantic v2 (configs), polars+numpy+pyarrow (données), httpx (HTTP), pyyaml, duckdb (plus tard) ; dev : pytest, pytest-cov, hypothesis, ruff, mypy

**Storage**: fichiers Parquet (zstd) sous `data/parquet/` + catalogue JSON `data/catalog.json` (tout git-ignoré)

**Testing**: pytest + hypothesis ; marque `net` pour l'intégration réseau ; httpx `MockTransport` pour tester la logique réseau sans réseau

**Target Platform**: Linux CLI (uv), 12 cœurs / 11 Go RAM

**Performance Goals**: SC-001 mois de klines 1s < 10 min ; SC-003 `data check` sur un mois < 1 min

**Constraints**: aucune clé API (données publiques) ; tests unitaires sans réseau ni données réelles ; RAM limitée → traitement jour par jour

**Scale/Scope**: 2 symboles (BTCUSDT, ETHUSDT) × {spot, um} × {klines 1s, aggTrades, fundingRate}

## Constitution Check

| Principe | Statut | Note |
|---|---|---|
| I. Test-First (NON NÉGOCIABLE) | PASS | Backlog TDD par cycle ci-dessous ; exceptions pragmatiques : câblage CLI, téléchargement HTTP brut (smoke tests + MockTransport pour la logique) |
| II. Réalisme économique | N/A | Coûts = feature 002+ |
| III. Anti-lookahead / déterminisme | N/A | Pertinent au moteur ; la normalisation ns UTC pose déjà les bases |
| IV. Un code, trois exécutions | N/A | |
| V. Simplicité / conventions | PASS | ns UTC int64, zstd, un fichier source = un fichier converti, YAGNI |

## Project Structure

### Source Code (repository root)

```text
pyproject.toml
src/tradingv2/
├── __init__.py            # version
├── cli.py                 # app Typer : data {download, check, instruments}, research, backtest, compare
├── config.py              # modèles pydantic + load_config
└── data/
    ├── __init__.py
    ├── sources.py         # URLs data.binance.vision + endpoints exchangeInfo
    ├── plan.py            # DownloadPlan (mensuel/journalier)
    ├── download.py        # fetch avec checksum, .part atomique, reprise, backoff, concurrence
    ├── convert.py         # parseurs CSV klines/aggTrades + normalize_ts + détection d'en-tête
    ├── store.py           # écriture Parquet zstd + catalogue data/catalog.json
    ├── quality.py         # anomalies : trous, doublons, non-monotone, high<low, aberrants
    ├── resample.py        # agrégation 1s → 5s/15s/1m
    ├── instruments.py     # exchangeInfo spot/fapi → InstrumentRules
    └── funding.py         # parsing fundingRate mensuel → Funding
tests/
├── unit/                  # sans réseau (fixtures synthétiques)
├── integration/           # marque @pytest.mark.net
├── fixtures/              # CSV d'exemples, golden exchangeInfo, golden funding
└── conftest.py
configs/                   # YAML de référence
data/                      # git-ignoré (raw/, parquet/, catalog.json)
```

**Structure Decision**: projet unique (lib + CLI), layout src/, tests miroir des modules.

## Contrats techniques

### Schémas canoniques (`data/convert.py`, requêtes `polars`)

- **Bar** : `ts_open_ns int64, open f64, high f64, low f64, close f64, volume f64, quote_volume f64, n_trades u32, taker_buy_volume f64, taker_buy_quote f64`
- **TradeTick** : `ts_ns i64, price f64, qty f64, agg_id u64, buyer_is_maker bool`
- **Funding** : `ts_ns i64, rate f64`
- **InstrumentRules** : `symbol str, market {spot, um}, tick_size f64, step_size f64, min_notional f64`
- **CatalogEntry** : `path, kind, market, symbol, interval?, source_url, sha256, n_rows, ts_min_ns, ts_max_ns, converted_at`
- **Anomaly** : `kind {gap, duplicate_ts, non_monotonic, high_lt_low, price_outlier}, ts_ns, detail`

### Sources et URLs (`data/sources.py`)

- `build_archive_url(market, kind, symbol, interval|None, period)` où period ∈ {YYYY-MM, YYYY-MM-DD} ; pattern `https://data.binance.vision/data/{spot|futures/um}/{daily|monthly}/{klines|aggTrades|fundingRate}/{SYMBOL}/{interval?}/{SYMBOL}-{...}.zip` ; checksum = même chemin + `.CHECKSUM`.
- `fundingRate` : mensuel uniquement. `exchangeInfo` : `https://api.binance.com/api/v3/exchangeInfo` et `https://fapi.binance.com/fapi/v1/exchangeInfo`.
- Golden strings figées en tests (fixture `tests/fixtures/golden_urls.txt`).

### Plan de téléchargement (`data/plan.py`)

- `build_download_plan(market, kind, symbol, interval, start_date, end_date, today)` → `[FileSpec(url, checksum_url, stem, target_path, period)]`
- Règle : mois complet écoulé → mensuel ; sinon journalier. Détermination du côté journalier/mensuel injectable (`today` paramètre) pour tests déterministes.

### Téléchargement (`data/download.py`)

- `download_file(client, url, checksum_url, dest_dir)` → `Path` : GET avec stream, écriture `.part`, vérification SHA256 du `.CHECKSUM` (hash hexadécimal, casse quelconque), renommage atomique ; si le fichier existe et passe son checksum → skip ; checksum invalide → rejet + retry ; retry avec backoff exponentiel sur 429/5xx/erreurs de connexion (max 5, jitter seedé) ; concurrence limitée au niveau appelant (ThreadPool, max 4).
- Tests : `httpx.MockTransport` (resume, skip, backoff, atomique, checksum).

### Normalisation (`data/convert.py`)

- `normalize_ts(raw: int) -> int` : ≥1e17 → µs→ns ; ≥1e14 → ms→ns ; sinon déjà ns. Erreur si hors plage plausible.
- Parseurs : détection d'en-tête (première ligne non numérique sur les colonnes attendues) ; lignes malformées → `DataParseError(file, line_no)`.

### Stockage (`data/store.py`)

- `write_parquet(df, path)` (zstd), layout `data/parquet/{market}/{kind}/{symbol}/{interval?}/{stem}.parquet` (stem = nom du zip sans extension).
- Catalogue `data/catalog.json` : `load_catalog(root)`, `upsert(entries)` idempotent (clé = path), `verify_catalog(root)` (re-hash optionnel).

### Qualité (`data/quality.py`)

- `check_bars(df, interval_ns, price_outlier_factor=100)` → liste d'anomalies : gap (ts manquants), duplicate_ts, non_monotonic, high_lt_low, price_outlier (prix hors [min/max jour × factor]).
- `data check` CLI : liste précise, exit 1 si anomalies.

### Resample (`data/resample.py`)

- `resample_bars(df, target_ns)` : group-by buckets d'ouverture cible ; open=premier, high=max, low=min, close=dernier, volumes sommés ; la dernière barre incomplète (bucket non rempli) est rejetée.

### Config (`config.py`)

- Modèles pydantic v2 : `AppConfig{data: DataConfig, costs?, strategy?, risk?}` ; `load_config(path)` ; erreurs localisant le champ (pydantic ValidationError + chemin du fichier).

## Backlog TDD (cycles, dans l'ordre — 1 cycle ≈ 1 commit)

1. `test_cli_help` — `tv2 --help` exit 0, commandes listées → `feat: cli tv2`
2. `test_config` — YAML valide/invalide, erreurs localisées → `feat: chargement config yaml`
3. `test_normalize_ts` — ms/µs/ns, plages, erreur → `feat: normalisation timestamps`
4. `test_parse_klines` — 12 colonnes, en-tête auto, malformed → `feat: parseur klines`
5. `test_parse_aggtrades` — spot 8 col / um 7 col, booléens → `feat: parseur aggtrades`
6. `test_build_archive_url` — golden strings tous marchés → `feat: urls data binance`
7. `test_download_plan` — mensuel/journalier, bornes, determinisme today → `feat: plan téléchargement`
8. `test_checksum` — ok/ko/absent/casse → `feat: verification checksum`
9. `test_downloader` — MockTransport : .part atomique, reprise, skip valide, backoff 429/5xx → `feat: downloader`
10. `test_store_catalog` — roundtrip parquet zstd + catalogue idempotent → `feat: stockage parquet catalogue`
11. `test_quality` — anomalies injectées toutes détectées → `feat: data check`
12. `test_resample` — golden 1s→5s/1m, barre partielle → `feat: resample`
13. `test_instruments` — golden exchangeInfo BTCUSDT (spot+um) → `feat: instruments`
14. `test_funding` — golden fundingRate mensuel → `feat: funding`
15. `integration/test_net_download` — 1 jour réel spot 1s BTCUSDT (~86 400 lignes) → `test: net telechargement`
16. smoke CLI `data download` E2E sur fixtures locales → `test: cli data smoke`

## Complexity Tracking

Aucune violation de constitution à justifier.