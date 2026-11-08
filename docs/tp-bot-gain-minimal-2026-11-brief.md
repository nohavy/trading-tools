# Brief figé — bot « gain minimal » (015) : mesurer le fardeau avant l'agent

Rédigé le 2026-11-08, avant tout calcul sur cette règle. But : définir la
règle mécanique la plus favorable (candidats les plus liquides, coûts les
plus bas du projet), mesurer son espérance nette, et en déduire le
**fardeau bps/trade** qu'un agent de sélection devrait créer pour rendre
le bot viable. Ce brief n'inclut aucun agent : c'est le plancher que tout
agent devrait battre.

## Hypothèses figées

1. **H15-a (mécanique)** : une entrée à timing fixe (sans compétence),
   suivie d'une sortie take-profit à +g %, avec stop à −s % et timeout,
   a une espérance nette positive OOS après coûts.
2. **H15-b (l'agent, mesurée indirectement)** : si H15-a échoue, la
   livraison = le bps/trade manquant. Un agent IA n'entre dans le
   protocole que si une famille de règles non-agent a déjà franchi la
   barre derrière son fardeau.

Sélection de paire par critères : déjà falsifiée quatre fois (005-006 sur
524 perpétuels, momentum, tendance, whale on-chain). Ce brief la
contourne et teste la mécanique seule — version la plus favorable.

## Candidats

SOLUSDT, XRPUSDT, DOGEUSDT, ADAUSDT, BNBUSDT + BTCUSDT, ETHUSDT en
référence. C'est la version la plus charitable du concept « acheter une
crypto » : liquidité maximale, coûts et données les plus propres.

## Règle primaire figée (pré-spécifiée, une seule)

- Entrée : close daily 1d UTC du premier jour de bourse de chaque semaine
  (timing volontairement sans compétence).
- Montant : X = 10 % du capital par ligne, pas de pyramide, pas de
  couverture.
- Sortie, appréciée aux closes daily (conservateur, pas d'intrabar) :
  TP +0,5 % ; stop −1,0 % ; timeout à 10 jours, sortie au close du
  10e jour. Si un close satisfaît les deux bornes, le stop est retenu
  (conservateur).
- Coûts : spot taker 10 bps + slippage 1 bps par côté, aller-retour
  22 bps.

## Grille secondaire (transparence, non décisive)

g ∈ {0,25 %, 1,0 %} × s ∈ {0,5 %, 2,0 %} × T ∈ {5 j, 20 j} autour de la
règle primaire. La grille ENTIÈRE est publiée dans le résultat ; aucune
cellule secondaire ne peut renverser le verdict.

## Fenêtres et barre

IS 2020-01 → 2023-06, OOS décisionnel 2023-07 → 2026-08 (identiques au
carry et à 013). Verdict sur le **portefeuille équi-pondéré des 7** :
t Newey-West ≥ 2,58 (Bonferroni héritée de 013), OOS net > 0,
drawdown ≤ 25 %. Les 7 résultats par symbole sont publiés tels quels.

## Métriques livrées

Net OOS, t NW, drawdown, taux de gagnants, bps/trade moyen, et la
métrique centrale : **le fardeau** = espérance d'entrée bps/trade
nécessaire pour équilibrer la règle (compte tenu des 22 bps et de la
queue des perdants).

## Prior écrit (avant la donnée, pour l'honnêteté)

Négatif : 22 bps d'aller-retour + timing sans compétence ⇒ espérance
attendue sous zéro. La valeur du document est le fardeau quantifié, pas
un GO. Références actuelles d'agents démontrés : ≈ 0 bps (appels
directionnels Jev ≈ drift naïf, p = 0,66 ; bot 7 indicateurs LinkedIn :
verdict nul).

## Données et gradin

1. Closes daily spot 2020-2026 pour les 7 paires — hérite l'ingestion du
   brief 013 (même gate de liquidité, mêmes checksums).
2. Si pass : fills intrabar 1m (TP/stop au toucher), moteur complet,
   stress, puis un holdout d'un mois jamais consulté.
3. Si fail : le thread « bot à agent » est refermé avec le chiffre du
   fardeau, pas avec une opinion.

## Out of scope

Tout agent IA en boucle, tout critère de sélection d'actif, les
futures, le levier.
