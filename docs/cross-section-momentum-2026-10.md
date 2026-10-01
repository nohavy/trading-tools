# Momentum cross-sectionnel sur pérpétuels UM — résultat : NO-GO

Date : 2026-10-01 · Voie A (horizon jours)
Statut : hypothèse testée et **rejetée**. Ne pas passer en paper/live.

## Question

Le momentum cross-sectionnel est l'anomalie la plus robuste documentée en
finance d'actifs. Sur les pérpétuels Binance, est-il exploitable après frais ?

Formulation testée, à chaque date t : classer les actifs par leur rendement
passé (lookback 7/14/30/60/90 jours), acheter le quintile haut, mesurer le
rendement forward (1/3/7/14 jours).

## Données

| Élément | Valeur |
|---|---|
| Source | `data.binance.vision`, klines 1d mensuels UM |
| Symboles | 864 (USDT) — dont ~340 **délistés**, pas de biais de survie |
| Fichiers | 21 334, 0 échec, checksums vérifiés |
| Période | 2020-01 → 2026-08, 2 435 jours |
| Barres | 637 705 (505 500 après filtre de liquidité, 830 actifs) |

Le filtre de liquidité garde les actifs dont la médiane glissante (30 j) du
volume de citation est au-dessus du 20e centile du jour : sans lui, l'étude
mesure des actifs innegociables.

## Méthode

- `src/tradingv2/research/cross_section.py`, 18 tests unitaires.
- Deux métriques par jeu de paramètres :
  - **spread** : quintile haut moins quintile bas (long + short, 2 jambes) ;
  - **long-only** : quintile haut moins l'univers equal-weight — la question
    posée par un investisseur long : « choisir les gagnants bat-il juste tout
    détenir ? ». La dérive du marché s'annule dans la différence.
- t-statistique **Newey-West** : les fenêtres forward se chevauchent, ce qui
  gonfle le t-stat naïf (corrigé ici, vérifié par test).
- Coûts : 4 bps (maker×maker) et 10 bps (taker×taker) par rebalance.
- Découpage : IS 2020-01 → 2023-06, OOS 2023-07 → 2026-08.

## Résultats

### Spread haut-bas (net 4 bps)

| Période | Meilleur | t | Médiocre |
|---|---|---|---|
| IS | +3,5 bps (lb=30, h=7) | 0,16 | −44 bps (lb=60, h=7) |
| OOS | +24,3 bps (lb=14, h=14) | 0,69 | −37 bps (lb=30, h=14) |

Brut, le spread reste dans ±15 bps sur tout l'échantillon avec |t| ≤ 1. Ce
qui semblait être un signal à 4 bps de coûts n'était que la soustraction des
coûts à un spread nul.

### Long-only haut vs univers equal-weight (net 4 bps)

| Période | Cellules positives | Meilleure | t | Pire | t |
|---|---|---|---|---|---|
| IS | **0 / 20** | −0,02 bps (lb=30, h=7) | −0,00 | −43,7 bps (lb=90, h=14) | −2,03 |
| OOS | 9 / 20 | +24,8 bps (lb=14, h=14) | 1,14 | −5,1 bps (lb=90, h=14) | −0,22 |

Le signe s'inverse entre les deux périodes. En IS, acheter les plus forts
perd systématiquement face au simple fait de tout détenir l'univers
(lb=90 : −40 bps, t = −2 à −3,7). En OOS, le même classement devient légèrement gagnant (lb=7-14,
h=14 : +25 bps, t = 1,3 à 1,7).

## Verdict

**NO-GO.** Trois raisons, chacune suffisante :

1. **Aucun edge en in-sample.** 0 cellule sur 20 ne bat l'univers après
   coûts. Il n'existe pas de paramètre à choisir en IS — donc aucune
   discovered edge, seulement une observation de période.
2. **Le signe se retourne.** IS favorise la réversion, OOS le momentum. Un
   paramètre gagnant en OOS perd en IS. C'est un changement de régime, pas un
   signal.
3. **Sous la barre de significativité.** Le meilleur cas OOS (lb=7, h=14 :
   +21,8 bps net / 14 j, t = 1,42) reste sous t = 2 et vaut +1,5 bps/jour
   contre 4 bps de frais aller-retour.

Le hit rate de 20-23 % sur l'échantillon complet avec une moyenne ≈ 0
indique une distribution à queue gauche : quelques très gros gagnants, une
majorité de petites pertes. C'est le profil d'un effet de sélection de
survivants dans les données, pas d'un signal exploitable.

## Ce qui a été appris

- Le marché haussier 2020-2026 fait que l'univers equal-weight des alts
  dérive fortement (top ≈ 12 à 78 bps par jour selon l'horizon). La plupart
  des « gains » du top quintile sont du beta, pas de l'alpha — d'où l'importance de mesurer
  la différence et non le rendement brut.
- Sur 864 instruments et 6,5 ans, 40 jeux de paramètres testés : la
  multiplicité des tests explique les |t| ≈ 2 isolés.
- Le pipeline (manifeste, téléchargement résumable, filtre, moteur, IS/OOS)
  est réutilisable tel quel pour toute étude daily/weekly.

## Suite

- Tester la **voie B** (sonde signal social X) : coût quasi nul, falsifiable
  rapidement.
- La seule variante daily encore plausible est le **trend following
  temporel** (time-series momentum) sur BTC/ETH, qui est un autre mécanisme
  que le classement cross-sectionnel — à tester séparément si la voie B
  échoue.
