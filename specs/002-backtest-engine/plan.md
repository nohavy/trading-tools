# Implementation Plan: Moteur de backtest événementiel

**Branch**: `002-backtest-engine` | **Date**: 2026-09-30 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-backtest-engine/spec.md`

## Summary

Moteur événementiel avec exchange simulé : ordres marché/limite/post-only/stop exécutés sur la tape de transactions réelle (aggTrades) ou en mode bougies seules, coûts paramétrables (frais maker/taker, slippage, latence seedée, funding), comptes spot et perpétuels avec registre réconciliable, API Strategy figée pour backtest/paper/live, artefacts de run traçables.

## Technical Context

**Language/Version**: Python 3.12 (uv) — déjà en place (feature 001)

**Primary Dependencies**: polars (chargement données), pydantic v2 (config), dataclasses (événements/ordres — léger, hot path), numpy (tapes en arrays) ; pas de numba sans benchmark (constitution V)

**Storage**: données via catalogue feature 001 (`data/parquet/`, `data/catalog.json`) ; artefacts dans `runs/<id>/` (git-ignoré)

**Testing**: pytest + hypothesis ; MockTransport/jeux synthétiques sans réseau ; marque `slow` pour le benchmark mensuel

**Target Platform**: Linux CLI, 12 cœurs / 11 Go RAM

**Performance Goals**: SC-003 — un mois de barres 1s + tape aggTrades < 10 min ; la boucle traite les barres une à une, les fills sont planifiés par searchsorted sur la tape

**Constraints**: déterminisme strict (graines), anti-lookahead structurel, RAM 11 Go (tapes mensuelles ~1 Go colonne en mémoire OK)

**Scale/Scope**: 1 instrument par run ; barres 1s/1m + tape aggTrades ; comptes spot et perpétuels

## Constitution Check

| Principe | Statut | Note |
|---|---|---|
| I. Test-First | PASS | Backlog TDD cycle par cycle ci-dessous |
| II. Réalisme économique | PASS | Coûts complets (frais/slippage/latence/funding) dès ce moteur ; ledger réconciliable |
| III. Anti-lookahead / déterminisme | PASS | FR-002/FR-003 + SC-002/SC-004 : tests dédiés |
| IV. Un code, trois exécutions | PASS | API Strategy figée ici ; exchange est une interface (implémentation simulée seule en 002) |
| V. Simplicité | PASS | dataclasses pour le hot path, pydantic seulement aux frontières (config/CLI) ; pas de partial fills v1 |

## Project Structure

```text
src/tradingv2/
├── core/types.py          # Side, OrderType, OrderStatus, FillRole, Order, Fill, PositionSnapshot
├── core/rounding.py       # round_price_to_tick, round_qty_to_step, respecte_min_notional
├── costs/fees.py          # FeeSchedule(maker_bps, taker_bps), fee_for(role, notional), round_trip_bps
├── costs/slippage.py      # SlippageModel.fixed_bps -> prix ajusté selon côté
├── costs/latency.py       # LatencyModel(mean_ms, jitter_ms, seed) -> sample(rng)
├── portfolio/ledger.py    # Ledger : flux catégorisés (gross/fee/slippage/funding) + invariants
├── portfolio/spot.py      # SpotAccount : cash + inventaire, frais en quote (v1)
├── portfolio/margin.py    # MarginAccount : position signée, levier, funding, liquidation MMR
├── execution/exchange.py  # SimulatedExchange : validation, arrival, fills prédictifs, annulations
├── strategy/base.py       # Strategy (on_start/on_bar/on_fill/on_timer/on_trade opt-in) + Context
├── backtest/config.py     # BacktestConfig (pydantic) : data, account, costs, strategy
├── backtest/engine.py     # boucle d'événements (heap), ordre strict à ts égal
├── backtest/runner.py     # orchestration : catalogue -> données -> engine -> artefacts
├── backtest/recorder.py   # trades.csv, equity.csv, summary.json, manifest.json
└── cli.py                 # tv2 backtest run --config
tests/unit/test_<module>.py (un fichier par module, cycles TDD)
tests/property/test_ledger.py, tests/integration/, tests/fixtures/
```

## Contrats techniques

### Types (`core/types.py`)

- `Side{BUY, SELL}`, `OrderType{MARKET, LIMIT, STOP_MARKET}`, `OrderStatus{PENDING, ACTIVE, FILLED, CANCELED, REJECTED}`, `FillRole{MAKER, TAKER}`.
- `Order{id, symbol, side, type, qty, limit_price?, stop_price?, post_only, submitted_ns, arrive_ns?, status, reject_reason?}`.
- `Fill{order_id, ts_ns, price, qty, fee, role, side}`.

### Arrondis et filtres (`core/rounding.py`)

- `round_qty_to_step(qty, step)` : **vers le bas** ; `round_price_to_tick(price, tick)` : **vers le bas** (conservateur) ; `validate_order(order, rules)` : tick/step/minNotional → `(ok, reason)`. Erreurs explicites si step/tick ≤ 0.

### Coûts (`costs/`)

- `FeeSchedule(maker_bps, taker_bps)` : `fee(role, notional) = notional * bps / 10_000` ; `round_trip_bps(entry_role, exit_role)` pour le risk gate.
- `SlippageModel` : `adjust_price(price, side, direction) = price * (1 ± slippage_bps/10_000)` — utilisé **uniquement en mode bougies seules** (sur tape, le slippage réel est dans les prix des transactions).
- `LatencyModel(mean_ms, jitter_ms, seed)` : `sample() -> ns` = mean ± |jitter| gaussien borné ≥ 0, rng numpy `default_rng(seed)` injectable.

### Registre (`portfolio/ledger.py`)

- `Ledger` : `record(gross, fee, slippage, funding)` par clôture de trade ; `totals() -> LedgerTotals` ; invariant `net == gross − fee − slippage − funding` vérifié par `assert_reconciled(tolerance=1e-9 relatif)`.

### Comptes (`portfolio/`)

- `SpotAccount(quote_balance, base_balance, rules)` : `apply_fill(fill)` (cash/inventaire + frais en quote v1) ; `equity(mark_price)` = quote + base × prix.
- `MarginAccount(balance, leverage, mmr=0.004)` : position signée (long > 0), `apply_fill`, `apply_funding(ts, rate, mark)`, `unrealized(mark)`, `equity(mark)`, `liquidation_price()` ; `is_liquidated(mark)` → equity ≤ MMR × notional ; levier ≤ 20.
- Les deux implémentent `Account` (protocole commun : apply_fill / apply_funding? / equity).

### Exchange simulé (`execution/exchange.py`)

- Construit avec : `InstrumentRules`, `Account`, `CostModel`, `LatencyModel`, tape optionnelle (`ts_ns, price, qty, buyer_is_maker` en arrays numpy triés) et curseur de lecture.
- `submit(order, now_ns)` : échantillonne la latence → `arrive_ns` ; à l'arrivée : validation (filtres, fonds) → ACTIVE → planification prédictive :
  - marché : première transaction **du bon côté** (acheteur preneur = `buyer_is_maker == False` pour un achat) à `ts ≥ arrive_ns` ; remplissage = VWAP des transactions suivantes jusqu'à couvrir la quantité (remplissement complet v1) ;
  - limite achat : pessimiste = première transaction avec `price < limit` ; optimiste = `price ≤ limit` ; rempli **au prix limite**, frais maker ; post-only : rejet si crossing au moment de l'arrivée ;
  - stop achat : première transaction `price ≥ stop` → remplissage taker au prix de déclenchement (+ frais taker) ; puis le stop devient marché s'il faut plus de quantité (v1 : une transaction suffit, tailles ≪ liquidité).
  - mode bougies seules (pas de tape) : marché → open de la barre suivante ± slippage ; limite → touch/trade-through sur high/low de la barre suivante au prix limite ; stop → déclenchement si high/low franchit, remplissage au max(min(open, stop)) pessimiste + slippage.
- `cancel(order_id, now_ns)` : si un remplissage est planifié à `ts_fill ≤ now_arrival` il survit (comme en réel) ; sinon l'ordre est annulé et le remplissage planifié est retiré.
- `on_bar_close(bar)` : en mode bougies seules, évalue les ordres actifs sur la barre qui vient de se clore.
- API évolution : la même interface servira au paper (tape live) et au live (BinanceBroker) — les méthodes `submit/cancel` et les callbacks de résultat sont le contrat de la constitution IV.

### Boucle d'événements (`backtest/engine.py`)

- Heap d'événements `(ts, priority, seq)` : priorité 0 = événements exchange (arrivées, remplissages planifiés), 1 = barres (livrées à `ts_close = open + interval`), 2 = minuteries. À priorité égale, ordre d'insertion (seq croissant).
- Barres : fournies par un itérateur sur le Parquet (chunk polars → numpy), jamais livrées avant leur clôture ; `ctx.lookback(n)` retourne les n dernières barres **clôturées** (la courante incluse).
- Latence appliquée à toute soumission ; aléa seedé ; timers via `ctx.set_timer(delay_ns)`.
- Fin de données : valorisation des positions à la dernière clôture, `on_end` de stratégie, artefacts écrits.

### Config (`backtest/config.py`, YAML)

```yaml
data:     {market: um, symbol: BTCUSDT, bars: 1s, tape: aggTrades, start: 2026-08-01, end: 2026-08-31}
account:  {type: margin, balance: 1000, leverage: 5, mmr: 0.004}
costs:    {maker_bps: 2, taker_bps: 5, slippage_bps: 0.5, latency: {mean_ms: 150, jitter_ms: 50, seed: 42}}
strategy: {name: trivial_buy_sell, params: {}}
```

- `bars` : intervalle des barres de décision (1s spot ou 1m UM natif ; UM 1s possible via barres dérivées des trades en catalogue) ; `tape: aggTrades|null` (null = mode bougies seules).
- Validation : latence ≥ 0, levier 1..20, balance > 0, stratégie connue (registre de stratégies).

### Artefacts (`backtest/recorder.py`, `runs/<UTCdatetime>-<strategy>/`)

- `config.yaml` (résolue), `trades.csv` (entrées/sorties, PnL brut/frais/slippage/funding/net), `equity.csv` (par clôture de barre), `orders.csv` (tous les ordres et leur sort), `summary.json` (compteurs, totaux, invariants), `manifest.json` (version, commit git, graines, fichiers de données + sha256 du catalogue).

## Backlog TDD (cycles, 1 cycle ≈ 1 commit)

**Phase A — fondations** (bloquantes)
1. `test_rounding` — tick/step vers le bas, minNotional → `feat: arrondis et filtres`
2. `test_core_types` — ordres/fills, transitions de statut → `feat: types core`
3. `test_fees` — maker/taker, round_trip_bps → `feat: grille de frais`
4. `test_costs_models` — slippage (côté), latence seedée déterministe → `feat: modeles de couts`

**Phase B — comptabilité (US3)**
5. `test_ledger` — catégories, invariant net, tolérance → `feat: registre`
6. `test_spot_account` — cycle achat/vente, frais quote, équité → `feat: compte spot`
7. `test_margin_account` — position signée, funding, liquidation → `feat: compte perpetuel`

**Phase C — exchange (US2)**
8. `test_order_validation` — rejets filtres → `feat: validation ordres`
9. `test_market_fills_tape` — côté, VWAP multi-transactions → `feat: fills marche tape`
10. `test_limit_fills_tape` — pessimiste/optimiste, post-only, maker → `feat: fills limite tape`
11. `test_stop_fills_tape` — déclenchement au franchissement → `feat: fills stop tape`
12. `test_bars_only_fills` — marché/limite/stop sur barres, pessimiste → `feat: fills bougies seules`
13. `test_predictive_cancel` — remplissage planifié vs annulation (course) → `feat: fills predictifs annulables`

**Phase D — moteur (US1/US4)**
14. `test_engine_ordering` — exchange → fills → barres → timers, à ts égal → `feat: boucle evenements`
15. `test_engine_latency` — ordre inactionnable avant arrive_ns → `feat: latence ordres`
16. `test_lookback_antileak` — lookback clôturé + troncature ⇒ mêmes décisions → `feat: lookback anti lookahead`
17. `test_engine_end` — valorisation finale propre → `feat: fin de donnees`

**Phase E — runner/CLI (US6/US5)**
18. `test_backtest_config` — YAML complet, erreurs → `feat: config backtest`
19. `test_runner_recorder` — artefacts runs/ complets + manifeste → `feat: artefacts run`
20. `test_backtest_cli` — `tv2 backtest run` → `feat: backtest cli`
21. `test_null_strategy` — aléatoire seedée perd ≈ coûts (SC-005) → `test: nullite moteur`
22. `test_trivial_golden` — PnL exact à la main (SC-001) + 2 runs identiques (SC-002) → `test: golden trivial`
23. `test_ledger_property` (hypothesis) — invariants sur séquences aléatoires → `test: proprietes registre`
24. `test_month_benchmark` (marque `slow`) — 1 mois < 10 min (SC-003) → `test: benchmark mois`

## Complexity Tracking

Aucune violation de constitution à justifier.