# Résultat de la validation moteur — carry toujours couvert BTC/ETH

**Critères figés** (`specs/010-spot-perp-carry-engine/spec.md`) : t Newey-West
≥ 2,0, drawdown ≤ 25 %, OOS > 0, un fill par jambe et par actif, aucune
restitution d'ordre, couverture de quantités ≥ 99 %. Fenêtre OOS
2023-07-01 → 2026-08-31, entrée fraîche à l'open 1m du 2023-07-01 après la
clôture daily du 2023-06-30, latence 150±50 ms.

## Exécution et critères — tous passés

| | BTCUSDT | ETHUSDT |
|---|---:|---:|
| Quantité de couverture | 0,312 052 | 5,13 072 548 |
| Couverture des jambes (spot/perp) | 0,9998 | 0,9999 |
| Fills (attendu 1/jambe) | 1 + 1 | 1 + 1 |
| Ordres rejetés | 0 | 0 |
| **OOS total / CAGR** | **+25,48 % / 7,42 %** | **+17,97 % / 5,35 %** |
| t Newey-West (HAC-20) | **7,20** | **6,04** |
| Drawdown max | **0,38 %** | **0,29 %** |
| Equity 20 000 → | 25 096 | 23 595 |

Sous-périodes, toutes positives : BTC +2,3 % /
+12,5 % / +7,3 % / +1,6 % (2023H2/2024/2025/2026YTD) ; ETH +2,3 % / +10,7 % /
+3,6 % / +0,6 %. Les critères figés sont franchis avec une large marge :
premier candidat du projet validé dans le moteur événementiel.

## Fidélité moteur ↔ modèle vectoriel (même vintage d'entrée)

Re-simulatisation du modèle vectoriel (`simulate_cash_and_carry`) avec la
même décision du 2023-06-30 à la clôture, mêmes coûts (11/6 bps), même
enchaînement funding :

| Sous-période | BTC vectoriel | BTC moteur | ETH vectoriel | ETH moteur |
|---|---:|---:|---:|---:|
| 2023H2 | +2,43 % | +2,30 % | +2,31 % | +2,30 % |
| 2024 | +13,13 % | +12,50 % | +10,71 % | +10,70 % |
| 2025 | +7,61 % | +7,30 % | +3,63 % | +3,60 % |
| 2026YTD | +1,66 % | +1,60 % | +0,55 % | +0,60 % |

Écarts résiduels ≤ 63 bps de sous-période : ils proviennent du timing
(vectoriel = intervalle complet depuis la clôture de décision ; moteur =
fill à l'open 1m du lendemain, moitié de journée moins), de l'inclusion du
settlement 00:00 de l'entrée (débitée en vectoriel, pas en moteur) et du
marquage. La mise en œuvre moteur est conforme au modèle.

## Pourquoi l'écran historique montrait +45,4 % / +53,4 %

L'écran toujours couvert était entré en **2020-01** et sa quantité gelée
n'a jamais été rééquilibrée. Quand BTC a triplé, le notionnel spot long,
figé en unités à l'entrée, a gonflé relativement à l'equity du modèle.
Au début de l'OOS, cette position portait ~1,8× sa base d'equity en
notionnel spot, contre ~0,95× pour une entrée fraîche en 2023 — un
rapport ≈ 1,76, égal au quotient 45,4 %/25,5 % mesuré sur BTC.
L'hypothèse 5 du plan (~20 bps d'écart) était fausse : le vintage ne
« coûte » pas, il **surdimensionne**. Le moteur mesure la réalité d'aujourd'hui : un
investisseur entrant en capital frais en 2023-07 encaisse ~+25 % (BTC) /
~+18 % (ETH) en 3,2 ans, pas +49 %. Aucun réglage n'a été effectué à
partir de ces chiffres.

## Décision

- **GO moteur** selon les critères gelés (t, DD, OOS, exécution) : l'attelage
  toujours couvert survit à l'exécution réaliste et les deux jambes sont
  fidèles.
- Suite prescrite par le workflow avant paper : **stress** (frais ×1,5,
  slippage ×2, latence +250 ms, combiné) sur les deux jambes, puis un
  holdout pré-enregistré analogue au protocole du trend. Ne pas toucher au
  sizing ni au rééquilibrage jusqu'à ce passage.

## Limites

- Entrée unique au 2023-07-01 : la période 2020-2023 est volontairement hors
  champ (l'entrée fraîche est le point de comparaison voulu) ; la résilience
  2020-2022 (bear 2022, funding négatif épisodique) **a depuis été rejouée
  au moteur** — voir `docs/carry-bear-2020-2022.md` : +121 % BTC / +341 % ETH
  sur l'IS, DD ≤ 2,24 %, fidélité vectorielle corr ≥ 0,999.
- Un seul actif par run moteur (agrégation en portefeuille par runs) ; la
  synchronisation des deux jambes repose sur la même frontière daily.
- Short perp en compte margin levier interne 2 : marge requise ≈ 4,8 k sur
  10 k ; une chute du spot de ~50 % sans rééquilibrage reste théoriquement
  gérable mais non stressée ici.
- Coûts non modélisés : spread variable, agressivité de marché ; les 10 bps
  spot et 5 bps perp taker (+1 bp slippage) sont des hypothèses figées.
