# Plan d'implémentation: carry neutre spot-perp

> **Note de backfill (2026-10-05)**: ce plan est écrit rétroactivement après
> la session perdue; le travail décrit ci-dessous est déjà réalisé et commité
> (`3f4a9a4`, `af5cc4d`). Il est conservé pour restaurer la discipline Spec
> Kit et tracer les décisions prises.

## Architecture

- `docs/spot-perp-carry-2026-10-prereg.md`: pré-enregistrement figé avant tout
  calcul de rendement (règle primaire, coûts, comparaisons, règle de lecture).
- `src/tradingv2/research/cash_carry.py`: `simulate_cash_and_carry`, modèle
  vectorisé d'un long spot / short perp de même quantité, capital non levieré,
  décisions à la clôture daily, funding valorisé au close perp de la décision.
- `scripts/spot_perp_carry_study.py`: cellules figées (primaire, benchmark
  toujours couvert, sensibilités non sélectionnantes) et synthèse IS/OOS via
  `summarize_daily_series` (t Newey-West HAC-20).
- `configs/download-spot-1d-{btc,eth}.yaml`: données spot 1d 2020-01→2026-08.
- `docs/spot-perp-carry-result-2026-10.md`: verdict selon la règle gelée.
- `tests/unit/test_cash_carry.py`: TDD du modèle (lookahead, convergence de
  basis, coûts aller-retour, seuils, chauffe).

## Hypothèses d'exécution (gelées avant résultats)

1. Décision à la clôture journalière UTC, appliquée seulement au rendement
   suivant; fenêtre de funding 7 jours strictement passés, settlements inclus
   jusqu'à la clôture.
2. Entrée si somme ≥ 15 bps et basis ≥ 0; sortie si somme ≤ 0 ou basis ≤ −20 bps.
3. Quantité identique sur les deux jambes, qty = equity/(spot+perp) — pas de
   levier, pas de rééquilibrage tant que la position est ouverte.
4. Coûts primaires par transaction : spot 11 bps (10 + 1 slippage), perp
   taker 6 bps (5 + 1), payés à l'ouverture et à la fermeture.
5. Warmup: aucune entrée tant que la fenêtre de funding remonte avant la
   première barre observée — les 7 premiers jours restent plats.
6. Benchmark toujours couvert (entrée unique après les 7 jours, mêmes coûts);
   sensibilités (seuil 8 bps, fenêtre 3 j, perp maker) reportées, jamais
   sélectionnantes.
7. Septembre 2026 exclu : son chemin de prix a déjà été consulté (holdout trend).

## Ordre TDD

1. RED/GREEN: attribution du funding sans lookahead (settlements ≤ clôture,
   encaissement limité à l'intervalle suivant).
2. RED/GREEN: profit de convergence de basis, coûts des deux jambes payés à
   l'aller et au retour, seuils d'entrée/sortie et chauffe.
3. Script d'étude + données spot 1d; exécution sur BTC/ETH selon le protocole.
4. Verdict documenté selon la règle de lecture gelée, sans nouveau seuil.

## Résultats constatés

- Cellule primaire: OOS +13,1 %, t NW 4,13, DD 0,19 % — tous les seuils passés.
- Benchmark toujours couvert: +49,4 %, t 6,48, DD 0,63 % — le timing n'ajoute
  pas de valeur (ligne gelée appliquée); le toujours couvert devient le
  candidat prioritaire pour une validation événementielle.

## Hors périmètre

- Exécution Engine (marge du short, fills, latence): débloquée par ce résultat
  mais réservée à une spec dédiée.
- Levier, rééquilibrage, volatility targeting, paper/live.
- Tout ajustement de seuil après lecture de la grille.
