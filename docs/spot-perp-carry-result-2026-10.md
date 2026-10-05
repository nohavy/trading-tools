# Résultat de l'écran carry neutre spot/perp — BTC/ETH

**Essai pré-enregistré avant tout calcul de rendement** : règles, seuils, coûts
et comparaisons figés dans `docs/spot-perp-carry-2026-10-prereg.md`.
Septembre 2026 exclu par construction. Relecture selon la règle gelée : la
cellule primaire taker est la seule cellule de verdict, les sensibilités sont
reportées mais non sélectionnantes, aucun nouveau seuil choisi après lecture.

## Données

- Spot 1d (BTCUSDT, ETHUSDT) 2020-01-01 → 2026-08-31, 80 mois/actif,
  archive Binance checksummée, convertie Parquet ns.
- Perpétuel UM 1d même période (80 mois/actif, `data/daily/um`).
- Funding historique 81 mois/actif (2020-01 → 2026-09) ; seuls les
  settlements ≤ clôture sont utilisés ; les settlements de septembre ne
  servent jamais à une décision de l'échantillon.
- Grilles spot/perp vérifiées alignées à la nanoseconde.

## Protocole exécuté (gelé)

- Décision à la clôture journalière UTC ; position appliquée seulement à
  l'intervalle suivant ; pas d'entrée pendant les 7 premiers jours.
- Entrée si somme des 7 derniers jours de funding ≥ 15 bps et basis ≥ 0.
- Sortie si somme ≤ 0 ou basis ≤ −20 bps.
- Long spot / short perp de même quantité, qty = equity/(spot+perp) :
  capital non levieré, les deux notionnels financés.
- Coûts par transaction : spot 11 bps (10 + 1 slippage), perp taker 6 bps
  (5 + 1). Funding de l'intervalle valorisé au close perp de la décision.
- IS 2020-01 → 2023-06, OOS décisionnel 2023-07 → 2026-08 (1 158 jours).

## Résultats OOS (portefeuille équipondéré)

| Cellule | Total OOS | CAGR | t NW-20 | DD max | Couvert | Trans. | Frais | Funding |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **Primaire 15 bps / 7 j / taker** | +13,1 % | 4,0 % | **4,13** | **0,19 %** | 54 % | 6 | 56 bps | 1 279 bps |
| Benchmark toujours couvert | +49,4 % | 13,5 % | 6,48 | 0,63 % | 100 % | 0 | 0 bps | 4 012 bps |
| Sens. seuil 8 bps | +13,2 % | 4,0 % | 4,16 | 0,17 % | 55 % | 6 | 61 bps | 1 293 bps |
| Sens. fenêtre 3 j | +9,9 % | 3,0 % | 3,57 | 0,17 % | 34 % | 4 | 36 bps | 967 bps |
| Sens. perp maker | +13,2 % | 4,0 % | 4,17 | 0,15 % | 54 % | 6 | 46 bps | 1 279 bps |

Par actif (primaire) : BTCUSDT +13,3 % OOS (t 4,33), ETHUSDT +12,9 % (t 3,90).
IS : CAGR portefeuille 29,2 % (2020-21 paie un funding massif) contre 4,0 % en
OOS — le niveau des taux funding s'est résorbé ; l'IS ne doit pas être lu
comme une prévision.

## Lecture selon la règle gelée

1. **Critères bruts de la cellule primaire : tous passés.** OOS +13,1 % > 0 ;
   t Newey-West 4,13 ≥ 2,0 ; drawdown 0,19 % ≤ 25 %. Première hypothèse du
   projet à franchir les trois seuils en OOS chronologique. Les sensibilités
   confirment la robustesse (toutes OOS positives, t ≥ 3,5, DD ≤ 0,17 %).
2. **Mais la comparaison benchmark gelée est sans appel** : le toujours couvert
   avec les mêmes coûts fait +49,4 % contre +13,1 % pour la version filtrée.
   Conserver la position en continu encaisse 4 012 bps de funding OOS contre
   1 279 bps pour la version filtrée : le seuil de 15 bps sort du marché
   pendant des périodes de funding positif et n'a jamais évité un vrai
   accident (DD benchmark 0,63 %, déjà faible). **Le signal n'ajoute pas de
   timing** — le rendement vient de l'attelage spot/perp lui-même, pas du
   filtre.

## Décision

- **La stratégie filtrée (règle primaire) n'est pas un GO** : son propre
  benchmark pré-enregistré la bat largement avec le même risque, la même
  exposition aux coûts et zéro transaction OOS. Exécuter le filtre serait
  payer de la complexité pour rendre moins.
- **L'hypothèse carry neutre (toujours couvert) devient le candidat de
  recherche prioritaire** : +49,4 % OOS, t 6,48, DD 0,63 %, zéro transaction
  après l'entrée unique de 2020. C'est le premier écran du projet qui survit
  à la falsification. La validation suivante est **événementielle dans
  l'Engine** (exigence de marge du short perp, fill réaliste, latence,
  liquidité spot), conformément au workflow du projet — l'écran vectorisé
  seul ne suffit jamais à un GO paper/live.

## Limites

- Écran vectorisé daily : pas de marge/liquidation modélisée, pas de spread
  variable, pas de contrainte de profondeur de carnet ; le short perp
  suppose un financement toujours disponible à l'exigence de marge.
- Coûts hypothétiques (spot 10 bps, perp taker 5 bps, slippage 1 bp) non
  mesurés sur carnet réel.
- Funding valorisé au close perp de la décision, approximation gelée du
  protocole ; le vrai encaissement se fait au prix de settlement.
- Basis négatif prolongé (bear premium) et régimes de funding négatifs sont
  inclus dans l'historique mais l'échantillon OOS 2023-07→2026-08 ne
  contient qu'une crise (2024-25) ; la résilience reste à confirmer.
- Aucun levier : le rendement est dilué par le capital immobilisé sur la
  jambe spot. Un levier prudent multiplierait rendement ET risque de marge —
  à étudier uniquement dans l'Engine, jamais sur l'écran.

Artefacts reproductibles : `scripts/spot_perp_carry_study.py` (cellules
gelées), `data/spot_perp_carry_results.json` (résultats locaux ignorés par
git), configs `configs/download-spot-1d-{btc,eth}.yaml`.
