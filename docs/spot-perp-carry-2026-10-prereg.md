# Pré-enregistrement — carry neutre spot-perp BTC/ETH

**Figé avant le calcul des rendements.** Septembre 2026 est exclu : son chemin de
prix a déjà été consulté pour une autre hypothèse.

## Hypothèse

Un portefeuille long spot / short perpétuel de même quantité de base encaisse le
funding positif et la convergence de basis, sans pari directionnel. On n'entre
que lorsque le funding récent couvre une part substantielle du coût d'entrée et
que le perp n'est pas en décote.

## Règle primaire, non ajustable après résultats

- Décision à la clôture journalière UTC, appliquée seulement au rendement suivant.
- Fenêtre de funding : 7 jours strictement passés, settlements inclus jusqu'à la clôture.
- Entrée si somme des taux ≥ 15 bps et basis `perp/spot - 1` ≥ 0.
- Sortie si cette somme ≤ 0 ou basis ≤ −20 bps. Sinon, conserver la quantité.
- Pas d'entrée pendant les 7 premiers jours.
- Quantité identique sur les deux jambes, dimensionnée pour que spot + notionnel perp = equity à l'entrée. Pas de rééquilibrage tant que la position est ouverte.
- Capital non levieré : les deux notionnels sont financés.
- Coût primaire par jambe et par transaction : spot 10 bps + 1 bp de slippage, perp taker 5 bps + 1 bp. Payé à l'ouverture et à la fermeture, pas à l'échéance de l'échantillon.
- Funding de l'intervalle suivant valorisé au close perp de la décision. Un taux positif crédite le short.
- Actifs séparés puis portefeuille équipondéré du capital.
- IS : 2020-01-01 → 2023-06-30. OOS décisionnel : 2023-07-01 → 2026-08-31.

## Comparaisons pré-enregistrées, hors sélection

- Benchmark toujours couvert, mêmes coûts, entrée unique après les 7 jours.
- Sensibilités reportées mais non utilisées pour choisir : seuil 8 bps ; fenêtre 3 jours ; jambe perp en maker 2 bps + 1 bp.

## Règle de lecture

La cellule primaire taker est la seule cellule de verdict.

- Rendement OOS ≤ 0, t-stat Newey-West < 2 ou drawdown > 25 % : hypothèse rejetée pour paper/live.
- Un OOS positif mais sous ces seuils reste un candidat de recherche, pas un GO.
- Si le benchmark toujours couvert explique le résultat, le signal n'ajoute pas de timing.
- Aucun nouveau seuil ne sera choisi après avoir vu la grille.
