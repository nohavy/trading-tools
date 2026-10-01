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

## 5bis. Scan complet des 524 perpétuels UM (août 2026)

L'analyse a été étendue à **tous les perpétuels USDⓈ-M négociables** (524/527 téléchargés, 491 vivants après filtrage). Résultat :

**227 actifs (46 %) ont un edge net positif** avec le signal breakout (lb30, vf5, horizon 300 s), dont **41 avec >50 M$/jour de liquidité**.

**Top 10 liquides** (edge net = brut breakout − 4 bps maker×maker) :

| Actif | Edge net | Brut breakout | Vol/j | Vol 1m |
|---|---|---|---|---|
| SKRUSDT | +218 bps | 222 | 55 M$ | 31 bps |
| ONGUSDT | +192 | 196 | 121 M$ | 41 |
| BTRUSDT | +173 | 177 | 103 M$ | 48 |
| BMTUSDT | +173 | 177 | 55 M$ | 45 |
| ACEUSDT | +170 | 174 | 185 M$ | 52 |
| TUTUSDT | +123 | 127 | 271 M$ | 78 |
| TRUMPUSDT | +122 | 126 | 295 M$ | 23 |
| HEIUSDT | +113 | 117 | 99 M$ | 49 |
| APRUSDT | +95 | 99 | 88 M$ | 42 |
| PROMUSDT | +93 | 97 | 97 M$ | 42 |

**Interprétation** : sur BTC/ETH (vol 1m ~0.5-0.8 bps), l'edge breakout est +0.8 bps brut — borné par le bounce. Sur les alts volatils (vol 1m 23-78 bps), le même signal fait 90-220 bps brut — l'edge scale avec la volatilité de l'actif. La thèse réfutée sur BTC/ETH est **confirmée sur les alts** : la borne microstructure y est beaucoup plus haute.

**Réserves honnêtes** : in-sample (une seule période) ; les fills réels sur ces actifs sont à valider ; le breakout_freq est faible (<1/jour pour la plupart) → peu de trades indépendants. La validation par la chaîne complète (walk-forward, stress, verdict) reste indispensable.

## 5ter. Validation moteur des top candidats : divergence scan↔moteur

Les 4 top candidats du scan (ONGUSDT, ACEUSDT, TUTUSDT, TRUMPUSDT) ont été backtestés dans le moteur (6 mois, 1m, breakout_volume lb30 vf5, max_hold 5 barres = horizon du scan) :

| Actif | Trades | Net (USDT) | Espérance (bps) | Win rate | PF | t-stat |
|---|---|---|---|---|---|---|
| ONGUSDT | 2542 | -371 | **-12.8** | 23.6% | 0.40 | -14.4 |
| ACEUSDT | 1969 | -23 | **-17.9** | 25.2% | 0.35 | -9.7 |
| TRUMPUSDT | 58 | +1 | **+18.3** | 32.8% | 1.41 | +0.7 |

Le scan montrait +95 à +192 bps net pour ces actifs. Le moteur montre -18 à +18 bps.

**Causes de la divergence** :
1. **Événements chevauchants** : le scan compte chaque barre de cassure comme un événement indépendant (~2300/mois). Le moteur n'entre que si flat (une position) — ~212 trades/mois. Les événements non-first d'un cluster ont un edge différent du premier.
2. **Sortie range-re-entry vs horizon fixe** : le scan mesure un hold fixe de 300 s. Le moteur sort quand le prix retourne dans la plage d'entrée — durée variable, parfois très courte (le prix ne revient jamais → max_hold).
3. **Coûts** : le scan suppose maker×maker (4 bps). Le moteur entre au marché (taker×taker = 10 bps + slippage).
4. **Timing d'entrée** : le scan mesure depuis le close de la barre de cassure. Le moteur entre au open de la barre suivante + latence + slippage.

**Leçon** : le scan d'edge est un filtre NÉCESSAIRE (il tue les idées clairement non viables) mais PAS SUFFISANT. Le backtest moteur reste le ground truth. Un edge brut au scan ne devient rentable que si une stratégie réaliste le capture — et la sortie (range re-entry vs horizon fixe) est aussi importante que l'entrée.

## 6. Impact sur la suite du projet

La constitution exige un verdict go/no-go avant le réel : le verdict est **NO-GO** sur les données d'août pour les signaux testés. Le pipeline (temps réel → paper → live) reste construit pour en valider d'autres — mais passer au paper sans signal à edge positif n'a pas de sens : la prochaine étape utile est la recherche de signaux d'une autre nature, ou l'acceptation du résultat.

## Artefacts

- Script d'analyse 1 : sweep meanrev + 3 signaux (237 s)
- Script d'analyse 2 : conditionnements breakout (sessions, régimes, direction)
- Script d'analyse 3 : TP/SL corrigé + long horizon + ETH (réfutation de la thèse vol)
- Commandes reproductibles : `uv run tv2 research edge --config configs/edge-meanrev.yaml`