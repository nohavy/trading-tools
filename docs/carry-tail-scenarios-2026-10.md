# Scénarios de queue du carry — bootstrap de blocs sur les rendements moteurs

Extension transposée du ch7 (VaR/Monte-Carlo) d'*Investing for Programmers*
au carry toujours couvert : le Monte-Carlo standard de la feature 004
bootstrap des **trips** (round-trips), que le carry n'a pas (une-entrée).
L'outil est donc un **bootstrap de blocs circulaires** des rendements
journaliers du portefeuille moteur (bloc 20 jours = discipline Newey-West),
sims = 2 000, seed = 42 — implémenté dans
`simulate...carry_tail_scenarios` (`research/cash_carry.py`).

## Source des rendements

OOS moteur fresh-2023 (2023-07-01 → 2026-08-31, 1 157 jours) : courbes
d'equity daily des 4 runs de `runs/carry-engine-2026-10`, jambes combinées
par symbole puis portefeuille équipondéré BTC/ETH (moyenne des rendements).

## Résultats (portefeuille équipondéré)

| Horizon horizont | p05 | médiane | p95 | prob. PnL final < 0 | prob. DD > 2 % | prob. DD > 5 % |
|---|---:|---:|---:|---:|---:|---:|
| 30 jours | +0,1 % | +0,4 % | +1,4 % | **1,7 %** | 0 % | 0 % |
| 90 jours | +0,6 % | +1,4 % | +3,2 % | 0 % | 0 % | 0 % |
| 365 jours | +4,0 % | +6,3 % | +9,6 % | 0 % | 0 % | 0 % |

## Lecture honnête

- Sur toute fenêtre rejouée du régime 2023-2026, le risque de perte du
  carry est minuscule — cohérent avec le DD moteur de 0,38 %.
- **Ces chiffres sont conditionnels au régime observé** : l'échantillon
  OOS fresh-2023 ne contient pas de bear. La résilience bear a été
  vérifiée séparément (`docs/carry-bear-2020-2022.md`, DD 2,24 %) ; un
  bootstrap qui mêlerait les deux échantillons serait plus honnête mais
  mélangerait aussi des conventions d'entrée différentes pour l'instant.
- Le funding réel, la base de marche et les coûts sont dans l'échantillon
  via les rendements ; seule la variation de régime reste hors-modèle.

Artefact : `data/carry_tail_scenarios.json` (locaux, ignorés par git).
