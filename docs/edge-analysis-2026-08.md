# Analyse d'edge poussée — août 2026, BTCUSDT & ETHUSDT

**Date** : 2026-09-30 · **Données** : klines 1 s spot, mois complet (2 678 400 barres/actif) · **Méthode** : étude d'edge (rendements forward vs coûts) — aucun backtest moteur nécessaire, chaque question répondue en secondes.

## Verdict : NO-GO pour le sub-minute retail sur ces signaux

Après balayage exhaustif (signaux × paramètres × conditionnements × actifs × horizons × TP/SL), **l'edge brut maximal trouvé est +0,8 bps, jamais suffisant** contre le coût aller-retour le plus bas accessible au retail (4 bps en maker×maker sur UM).

## 1. Sweep meanrev (16 combinaisons, horizon 60 s)

Toutes les fenêtres (60-600) × seuils (z 1,5-3,0) : **brut -0,5 à -0,8 bps**. Le z-score extrême sur BTC/ETH en août 2026 ne revient pas à la moyenne : les dips continuent en moyenne (régime de momentum).

## 2. Les 3 signaux en compétition (horizon 60 s)

| Signal | n | Brut (bps) | Hit rate | Net maker×maker |
|---|---|---|---|---|
| breakout lb30 vf5 | 69 722 | **+0,74** | 59,7 % | -3,26 |
| meanrev w120 z2.5 | 23 051 | -0,73 | 38,0 % | -4,73 |
| flow w120 th0.5 | 18 502 | +0,30 | 51,0 % | -3,70 |

Le breakout a un **vrai edge brut, robuste** : stable sur toutes les grilles (lookback 15-120, volume_factor 2-20 : 0,67-0,80), toutes les sessions UTC (0,67-0,78), les deux régimes de vol (0,70-0,79), les deux directions (buy 0,83 / sell 0,64).

## 3. Pourquoi ça ne suffit pas : borné par la microstructure

- MFE à 60 s = 3,3 bps : **même en prenant le meilleur prix de la minute**, on ne couvre pas 4 bps.
- Test décisif de la thèse « l'edge scale avec la volatilité » : ETH a une vol 1 s de +49 % (0,76 vs 0,51 bps) mais un edge breakout **inférieur** (0,62 vs 0,74) → l'edge brut est borné par le **bid-ask bounce** (~0,5-1 bps), pas par la volatilité de l'actif.
- Aucun schéma take-profit ne rattrape (calcul corrigé du biais de signe) : E_net max = **-4,98 bps** (TP 0,5, hit 92,7 %) ; les schémas « TP serré » paient le SL dans les queues.
- Pas de persistance : brut ~1 bps encore à 4 h d'horizon — l'edge du breakout 1 s est purement local.

## 4. Leçons méthodologiques

- L'étude d'edge (secondes) a remplacé des heures de backtests : ~20 questions analysées en 5 minutes.
- Un biais de signe dans l'analyse TP/SL (SL compté comme gain) a été attrapé avant d'induire en erreur — le recalcul confirme le verdict.
- Le test de nullité + l'edge négatif cohérent avec la théorie des coûts = confiance dans la chaîne de mesure.

## 5. Pivot horizons longs (feature 005) : le funding-momentum, testé et tué OOS

Le pivot vers des horizons 24-72 h a identifié un candidat : après un funding extrême (p95 roulant), le prix BTC/ETH CONTINUE (momentum du crowding) — brut +14 à +70 bps sur 8-72 h, net des frais maker×maker positif in-sample (BTC p90 : +24 à +58 bps ; ETH p95 : +55 à +66 bps). Le mécanisme est plausible (longs payants, liquidations en chaîne).

**Le test final honnête** : backtest moteur sur 7 ans de données 1m UM (2020-2026, 3,5 M barres, frais taker réels, une position, funding compté), puis walk-forward chronologique (54 folds de 30 j train / 15 j test) :

| Métrique OOS | Valeur |
|---|---|
| Folds positifs | **39 %** (requis 70 %) |
| OOS net agrégé | **-47,4 USDT** sur 190 trades |
| OOS brut | -33,6 USDT (même le prix ne suit pas OOS) |
| Espérance/trade | -0,25 USDT (~-26 bps) |

Le meilleur combo in-sample (+1,84 bps net, 282 trades, th=95 hold=48 h) **ne survit pas out-of-sample**. Le carry short funding est un edge connu et arbitré : visible in-sample, épuisé net de frais sur un actif liquide.

Notons aussi le coût caché découvert : la version LONG (buy funding élevé, première hypothèse) perdait -8,6 % sur 7 ans car la détention PAIT le funding pendant les pics (~50 bps/trade) — le momentum prix (+28 bps) ne le couvre pas. Les deux côtés sont morts par le mécanisme même qui crée le signal.

## 6. Voies restantes (documentées, non closes)

1. **Microstructure du tape** : séquences d'agresseurs (aggTrades disponibles localement), autocorrélation des ticks — l'ordre de grandeur attendu reste 1-3 bps bruts au mieux.
2. **Frais** : BNB/VIP réduit le maker×maker de 4 à ~3 bps — insuffisant seul (+0,8 brut).
3. **Style différent** : horizons minutes→heures avec signaux plus riches (l'edge local ne persiste pas, il faut une NOUVELLE nature de signal pour les horizons longs, ex. funding, basis, agrégats).
4. **Accepter la mesure** : l'outil a produit sa réponse — pas d'edge retail accessible sur BTC/ETH sub-minute avec des signaux prix/volume de base.

## 6. Impact sur la suite du projet

La constitution exige un verdict go/no-go avant le réel : le verdict est **NO-GO** sur les données d'août pour les signaux testés. Le pipeline (temps réel → paper → live) reste construit pour en valider d'autres — mais passer au paper sans signal à edge positif n'a pas de sens : la prochaine étape utile est la recherche de signaux d'une autre nature, ou l'acceptation du résultat.

## Artefacts

- Script d'analyse 1 : sweep meanrev + 3 signaux (237 s)
- Script d'analyse 2 : conditionnements breakout (sessions, régimes, direction)
- Script d'analyse 3 : TP/SL corrigé + long horizon + ETH (réfutation de la thèse vol)
- Commandes reproductibles : `uv run tv2 research edge --config configs/edge-meanrev.yaml`