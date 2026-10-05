# Tâches: carry neutre spot-perp

> **Note de backfill (2026-10-05)**: tâches cochées rétroactivement — le cycle
> TDD et l'étude ont été réalisés dans la session perdue et repris le 05/10.

- [x] T001 Écrire le pré-enregistrement gelé (règle primaire, coûts,
      benchmark, sensibilités, règle de lecture) avant tout calcul.
- [x] T001b Spécifier la feature (spec.md, status research falsification).
- [x] T002 Tests RED du modèle: funding sans lookahead, convergence de basis,
      coûts aller-retour des deux jambes.
- [x] T003 Implémenter `simulate_cash_and_carry` (GREEN) puis corriger la
      garde de chauffe pour couvrir la fenêtre de funding observée.
- [x] T004 Ajouter les configs spot 1d BTC/ETH 2020-01→2026-08 et vérifier
      l'alignement spot/perp/funding à la nanoseconde.
- [x] T005 Script d'étude avec cellules figées (primaire, benchmark toujours
      couvert, 3 sensibilités) et synthèse IS/OOS Newey-West.
- [x] T006 Exécuter l'étude et documenter le verdict selon la règle gelée
      (`docs/spot-perp-carry-result-2026-10.md`).
- [ ] T007 Passer les quality gates: Ruff et mypy verts (147 fichiers), 5/5
      tests carry verts; la suite complète garde 1 échec reproductible sur le
      timeout du benchmark `test_sweep_8_configs_on_real_month`
      (349–366 s > 300 s), déjà documenté au T007 de la feature 008 et sans
      échec fonctionnel.
