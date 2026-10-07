# Contrôle de résilience bear — carry toujours couvert, 2020-2022

Suite de `docs/carry-engine-result-2026-10.md` : la limite documentée
« la résilience 2020-2022 n'est pas couverte par ce run » est fermée. Le
carry toujours couvert est maintenant rejoué **dans le moteur événementiel
1m** sur toute la fenêtre IS de l'écran — incluant le bear 2022, les
épisodes de funding négatif et la crise de mai 2021.

**Nature du contrôle** : diagnostic de fidélité, pas un holdout — la fenêtre
2020-01→2023-06 fut consultée par l'écran vectoriel (IS). Les paramètres sont
ceux, **verbatim**, de la feature 010 (jambes 10 k + 10 k, levier interne 2,
fraction 0,95, coûts 11/6 bps, latence 150±50 ms seed 42). Seule différence
voulu : l'entrée moteur à la clôture du 2020-01-07, exactement la frontière
d'entrée du benchmark toujours couvert de l'écran (vintage identique pour
une comparaison directe).

## Exécution

4 runs (BTC/ETH × spot/perp), 1 fill par jambe, 0 rejet. Quantités de
couverture : BTC 1,2246, ETH 65,9287 (clôtures du 2020-01-07).

## Résultats moteur sur la fenêtre IS complète

| | BTCUSDT | ETHUSDT |
|---|---:|---:|
| Total (2020-01-08 → 2023-06-30) | **+121,01 %** | **+341,37 %** |
| CAGR | 25,6 % | 53,3 % |
| t Newey-West | 4,38 | 4,60 |
| Drawdown max | **0,69 %** | **2,24 %** |
| Equity 20 000 → | 44 203 USDT | 88 275 USDT |

Le pire mois vectoriel reste 2021-07 pour BTC (−0,17 %) et **2022-09 pour
ETH (−2,01 %)** : le carry a traversé le bear 2022 avec deux mois
légèrement négatifs sur 42 — le funding parfois négatif (le short paie)
a toujours été compensé par la convergence de basis.

## Fidélité moteur ↔ vectoriel, chemin journalier (1 269 intervalles communs)

| | BTC | ETH |
|---|---:|---:|
| Corrélation des rendements journaliers | 0,99933 | 0,99921 |
| Écart moyen | +0,008 bp/jour | −0,316 bp/jour |
| Somme des écarts | +0,10 % | −4,01 % |
| Jours à > 10 bps d'écart | **0** | 6 |

La dérive ETH de −0,32 bp/jour (−4,0 % sur 3,5 ans) vient de la convention
de valorisation **gelée au pré-enregistrement** : l'écran valorise le
funding au close perp de la décision, le moteur l'applique aux vrais
settlements aux prix de marque. L'écran surestime donc légèrement le carry
ETH ; le moteur mesure le plus réaliste. Aucun jour d'écart > 10 bps pour
BTC, six pour ETH (crashs de basis : mai 2021, 2022-09).

## État du candidat après ce contrôle

- Écran pré-enregistré ✓ (009) — moteur fresh-2023 ✓ (010) — stress ✓
  (010) — **bear 2020-2022 rejoué moteur ✓ (ce contrôle)** — holdout
  pré-enregistré : automatisé, déclenchement le 2026-11-01.
- Le seul chemin encore jamais vu par un GO moteur reste octobre 2026, et
  aucun réglage de sizing/coût n'est autorisé même après son verdict.

Artefacts reproductibles : `configs/research-carry-bear-2020-2023-{btc,eth}.yaml`
(paramètres figés), `scripts/run_carry_engine_validation.py` (runner
générique), `data/carry_engine_bear.json` (locaux, ignorés par git).
