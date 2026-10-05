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
- [x] T006 Exécuter BTCUSDT et ETHUSDT avec funding, fees, slippage, latence.
- [x] T007 Rapprochement écran vs moteur documenté, verdict selon les critères
      figés (t ≥ 2,0, DD ≤ 25 %, OOS > 0) : tous passés (t 7,20/6,04,
      DD 0,38 %/0,29 %, 1 fill/jambe, 0 rejet) — `docs/carry-engine-result-2026-10.md`.
      L'écart avec l'écran 2020 (+49 %) est un effet de vintage expliqué et
      reproduit analytiquement, pas un défaut moteur.
- [x] T008 Quality gates: suite hors net/slow 504 verts, Ruff et mypy stricts
      verts. Correction associée: `_rules_for` lit les règles d'instruments
      via `data_root` du run (le couplage à `data/` du repo cassait les tests
      stress avec les règles réelles minNotional UM 50 USDT désormais
      présentes). Les tasks 008/009 documentent l'unique échec du benchmark
      `slow` `test_sweep_8_configs_on_real_month`, sans rapport.
- [x] T009 Stress du candidat dans le moteur (frais ×1,5, slippage ×2,
      latence +250 ms, combiné) sur BTC et ETH : survit partout, au pire
      4 bps au combiné — `docs/carry-stress-result-2026-10.md`.
      Prochaine étape : holdout pré-enregistré.
