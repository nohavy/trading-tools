# Stress du carry toujours couvert — BTC/ETH, moteur 1m

Suite de `docs/carry-engine-result-2026-10.md` : le GO moteur est conditionné
au passage du stress prescrit par le workflow (frais ×1,5, slippage ×2,
latence +250 ms, combiné). Mêmes runs, mêmes entrées, seuls les coûts et la
latence sont dégradés ; le verdict reste figé (t ≥ 2,0, DD ≤ 25 %, OOS > 0).

## Résultats

Base de référence : BTC +25,48 % (t 7,20), ETH +17,97 % (t 6,04).

| Scénario | BTC total (t) | ETH total (t) | Verdict figé |
|---|---:|---:|---|
| Base | +25,48 % (7,20) | +17,97 % (6,04) | OK / OK |
| Frais ×1,5 | +25,45 % (7,18) | +17,94 % (6,03) | OK / OK |
| Slippage ×2 | +25,47 % (7,20) | +17,96 % (6,04) | OK / OK |
| Latence +250 ms | +25,48 % (7,20) | +17,97 % (6,04) | OK / OK |
| Combiné | +25,44 % (7,18) | +17,93 % (6,02) | OK / OK |

**Verdict global : SURVIT PARTOUT.** L'immunité s'explique mécaniquement :
l'attelage ne paie qu'un aller simple à l'entrée (zéro sortie, zéro
transaction OOS), donc dégrader les coûts de moitié ajoute au plus ~15 bps
d'entrée — contre une prime de funding de ~1 200 bps/an constatée en OOS
(4 012 bps sur 3,2 ans pour le benchmark toujours couvert de l'écran).
La latence +250 ms est invisible : le fill reste dans la même barre 1m
suivante.

## Lecture honnête

- Le stress mesure la sensibilité aux coûts d'un candidat à rotation quasi
  nulle : c'est le profil le moins coûts-sensible possible. Il NE précise
  RIEN sur le risque de marché (marge du short, bear 2022, ses klines ne
  sont pas encore rejouées au niveau moteur) ni sur la modélisation du
  funding en régime positif/négatif extrême.
- La prime étant chronologiquement inégale (2024 : +12,5 % ; 2026YTD :
  +1,6 %), l'edge peut se résorber ; la dégradation des coûts ne changera
  pas son signe — c'est le funding qui le fait, et une série historique
  réelle n'est pas stressable.

## Décision

- **Stress franchi** — la barre du workflow avant paper est franchie au
  niveau moteur pour ce candidat.
- Étape suivante : **holdout pré-enregistré** (mois non consulté, compteur
  d'essais à incrémenter dans `data/holdout_attempts.json`), puis paper sur
  petite taille si le holdout franchit aussi ses critères.
- Aucun réglage de sizing/coût autorisé même en cas de holdout négatif.
