# Brief figé — carry toujours couvert levieré (014)

Rédigé le 2026-11-08, avant tout calcul. Socle : le carry toujours couvert
validé (t 7,20 / 6,04, holdout octobre PASSED, DD ≤ 0,4 %). Le seul
changement testé est un facteur de notional F ∈ {2 ; 3,5 ; 5} multiplié
au sizing figé (notional par jambe = 0,95 × equity du compte de jambe,
config holdout oct-2026). Aucune autre règle ne bouge : une seule entrée
tenue jusqu'au terme, mêmes coûts, mêmes fenêtres.

## Hypothèse figée

Le mécanisme reste positif et solvable à F ∈ {2 ; 3,5 ; 5}. Le F retenu
est le plus haut qui franchit tous les échelons. Si aucun F ne passe, le
levier est falsifié et le socle 1× reste le portefeuille.

## Amendement mécanique figé (pré-exécution, le 2026-11-08)

- **F > 1 exige un emprunt spot** : la jambe spot passe sur un compte
  marge spot (nouveau type `margin_spot` dans le moteur) — l'achat est
  payé du cash d'abord, le reste est emprunté ; les intérêts s'ajoutent
  à la dette, proportionnellement au temps ; une vente rembourse la
  dette d'abord.
- **APR figé : 6 %/an flat**, les deux fenêtres, les deux symboles.
  Une sensibilité {2 % ; 6 % ; 12 %} est publiée en secondaire ; le
  verdict utilise 6 %. Plate et prudence : l'APR réel de Binance varie
  (pointes hautes en 2021 et fin 2024) — un GO à 6 % flat reste un GO
  prudent, pas une promesse.
- **Solvabilité évaluée sur la vue jointe (portfolio margin)** : le
  spot long sert de collatéral au short perp — ratio = equity combinée
  / (exigence de maintenance sur le short) ≥ 2× à chaque marque daily,
  et aucune liquidation jointe. Les equity MINIMES PAR COMPTE sont
  rapportées comme besoin de transferts opérationnels (le modèle deux
  comptes du moteur sépare les marges ; il ne change pas le PnL
  combiné).
- **Mécanique d'intérêts** : accrual depuis le bar de l'engine
  (`accrue_to`), elle apparaît naturellement dans les marques d'equity ;
  le ratio de marge joint est recalculé à post-lecture (equity combinée
  aux closes daily + closes perp 1d).

## Ordre de lecture pré-déclaré (le verdict suit le plus strict échelon)

1. **Solvabilité d'abord** : un ratio de marge (equity / exigence de
   maintenance) ≥ 2× à tout instant, et aucune liquidation touchée sous
   aucune fenêtre. Échec à cet échelon = NO-GO du F, sans recours.
2. **Stress** : replay LUNA 2022-05-04 → 2022-05-20 sous marge aux trois
   F ; les épisodes funding négatif (2021-05, 2022-06, extrêmes de 2026)
   sont dans les données du replay.
3. **Drawdown** : bear 2020-2022 ≤ 12 % ; holdout ≤ 2,5 % ; queue année
   (bootstrap de blocs, p01) ≥ −8 %. Budgets modifiables tant qu'aucun
   calcul n'a tourné, gelés à la première exécution.
4. **Statistique** : t Newey-West ≥ 2,0 net OOS, OOS > 0, et cohérence de
   mise à l'échelle : net(F) ≈ F × net(socle) ± 15 %.

## Fenêtres

Replay moteur entrée fraîche OOS 2023-07 → 2026-08 aux trois F, bear
2020-2022, bootstrap de blocs, LUNA. **Holdout pré-enregistré : décembre
2026** — le premier mois jamais lu après ce brief (novembre est consommé
par la paper 1×). Un seul F : le plus haut qui passe les échelons.
Verdict le 2027-01-01.

## Attente honnête (au run-rate de funding comprimé d'aujourd'hui)

F=2 ≈ 2-6 %/an, F=3,5 ≈ 3-10 %/an, F=5 ≈ 5-15 %/an, DD bear attendu
~11 % à F=5 si 2020-2022 se duplique. Le rendement à 1-3 %/an du socle
devient le double sujet : levier accepté, DD bear ≤ 12 % accepté.

## Matrice NFR

F > 1 crée un risque de marge absent du socle. Avant le holdout, la
ligne « ratio de marge » est ajoutée à `docs/live-risk-matrix.md` avec
ses déclencheurs d'alerte (génération des seuils avant exécution).

## Out of scope

Gestion dynamique (règle de delever active), extension multi-paires
(brief 013, séparée), tout changement de coûts, tout re-calcul de la
référence 1× existante.

## Implémentation minimale (TDD, avant toute lecture de résultat)

Un facteur de sizing dans le harnais existant
(`scripts/run_carry_engine_validation.py`) et la série du ratio de
marge dans les checks de fidélité. Changement mécanique ; aucun
changement de règles de trading.
