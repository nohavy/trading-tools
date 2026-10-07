# Tâches: mode paper

- [ ] T001 Relire et valider spec+plan (porte d'empreinte, périmètre sans
      clés, pas de WebSocket).
- [x] T002 Tests RED du feed synthétique: clôtures 1m, déduplication
      ts_close, backfill après coupure, backfill funding.
- [x] T003 Implémenter `feed.py` (client HTTP injectable) (GREEN).
- [x] T004 Extraire la boucle d'événements d'`Engine` en flux itérable sans
      changer l'ordre constitutionnel (golden: mêmes fills qu'un backtest).
- [x] T005 Implémenter `session.py` deux jambes coordonnées + quantité de
      couverture partagée.
- [x] T006 Tests RED/GREEN de persistance: snapshot atomique, reprise après
      interruption simulée, aucun double ordre.
- [x] T007 Tests RED/GREEN du kill switch (fichier + Ctrl-C) et du gate
      d'empreinte (refus sans holdout franchi / `experimental: true`).
      Fix au passage: parité incrémental/vectoriel (np.sum pairwise) flaky
      préexistant; hooks d'état publics sur Strategy.
- [ ] T008 Sous-commandes CLI `paper run --once`/`--status`/`report` + smoke.
- [ ] T009 Hour complet réel en simulé (configs paper-carry), rapport HTML
      rendu, quality gates: suite hors net/slow, Ruff, mypy stricts verts.
- [ ] T010 (Après verdict holdout du 2026-11-01) : geler l'empreinte dans
      `configs/paper-carry-*`, ouvrir la session paper réelle.
