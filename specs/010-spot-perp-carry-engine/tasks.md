# Tâches: carry toujours couvert dans le moteur événementiel

- [x] T001 Spécifier et planifier (fait à la création de la feature).
- [x] T002 Configs spot 1m BTC/ETH 2023-04→2026-08 et téléchargement vérifié
      (35+6 mois convertis par actif) ; règles d'instruments réelles
      téléchargées (spot/um × BTC/ETH).
- [x] T003 Tests RED des jambes: entrée unique post-`trade_start_ns`, quantité
      exacte, aucune sortie, pas de double soumission.
- [x] T004 Implémenter `CashCarrySpotLeg` / `CashCarryPerpLeg` (GREEN) et les
      enregistrer dans `builtin.py`.
- [x] T005 Runner de validation: deux jambes par actif, equity daily combinée,
      synthèse Newey-West et checks de fidélité (fills, rejets, couverture),
      helpers `hedge_qty` et `combine_leg_equities` testés.
- [ ] T006 Exécuter BTCUSDT et ETHUSDT avec funding, fees, slippage, latence.
- [ ] T007 Rapprochement écran vs moteur documenté, verdict selon les critères
      figés (t ≥ 2,0, DD ≤ 25 %, OOS > 0).
- [ ] T008 Quality gates: suite hors net/slow, Ruff et mypy verts (l'échec
      connu du benchmark `slow` `test_sweep_8_configs_on_real_month` est
      documenté aux tasks 008/009 et sans rapport).
