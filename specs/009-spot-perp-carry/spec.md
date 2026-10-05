# Feature Specification: Carry neutre spot-perp

**Created**: 2026-10-04

**Status**: Approved for research falsification

## User Story

Mesurer si une couverture long spot / short perp, entrée seulement quand le funding passé paie les frais, a un rendement net positif après coûts sur BTC et ETH.

## Acceptance Scenarios

1. Une décision à la clôture t ne rémunère que t→t+1 et n'utilise aucun funding postérieur.
2. Un short de même quantité gagne le funding positif et la baisse du perp relative au spot.
3. L'ouverture et la fermeture paient les deux jambes; rester couvert ne paie pas un nouveau round-trip.
4. Sous le seuil de funding ou avec un basis négatif, aucune entrée.
5. Le verdict utilise uniquement la cellule primaire figée dans `docs/spot-perp-carry-2026-10-prereg.md`.

## Out of scope

- Exécution Engine tant que l'écran vectorisé échoue.
- Septembre 2026 et toute optimisation après lecture des résultats.
