# Tâches: validation moteur du trend temporel

- [x] T001 Implémenter les tests Engine RED du signal daily et du warmup OOS.
- [x] T002 Implémenter la stratégie `time_series_trend` long/flat et buy-and-hold.
- [x] T003 Tester ordre pending/rejet, sizing 1×, entrée/sortie sans lookahead.
- [x] T004 Ajouter configs 1m BTC/ETH et runner de synthèse OOS.
- [x] T005 Exécuter BTCUSDT et ETHUSDT avec funding, fees, slippage et latency.
- [x] T006 Documenter le rapprochement vectorisé vs moteur et le statut du candidat.
- [ ] T007 Passer les quality gates; suite hors net/slow, Ruff et mypy verts. La suite complète a 1 échec reproductible sur le timeout du benchmark `test_sweep_8_configs_on_real_month` (376 s > 300 s), sans échec fonctionnel.
