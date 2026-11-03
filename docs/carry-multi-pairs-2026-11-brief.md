# Brief de recherche — extension du carry toujours couvert à cinq paires liquides (013)

Rédigé le 2026-11-03, **avant tout calcul de rendement sur ces paires**.
Le circuit éprouvé (écran → moteur → stress → holdout) se rejoue à
l'identique ; ce brief fige l'extension.

## Hypothèse figée

Le mécanisme validé sur BTC/ETH — long spot, short perpétuel de même
quantité, capital non levieré, une seule entrée tenue jusqu'au terme —
marche-t-il aussi sur les cinq paires les plus liquides après BTC/ETH ?

## Candidats figés (avant les données)

SOLUSDT, XRPUSDT, DOGEUSDT, ADAUSDT, BNBUSDT. Une paire qui ne passe pas
le seuil de liquidité vérifié aux données (volume daily spot > 100 M$ et
open interest perp > 300 M$) sort du set candidat avant l'écran, avec un
NO-GO technique documenté.

## Règles gelées (verbatim 009/010, une seule adaptation)

1. **Adaptation unique** : l'écran vectoriel tourne sur les closes 1d
   uniquement (l'écran carry n'a jamais besoin du 1m) ; le moteur 1m ne
   s'allume que si l'écran passe. Aucune autre modification du protocole.
2. Fenêtres identiques à l'original : IS du 2020-01-01 au 2023-06-30,
   OOS décisionnel du 2023-07-01 au 2026-08-31. Le funding doit couvrir
   tous les settlements 2020-2026.
3. Coûts : les mêmes chiffres que le carry (11 bps spot, 6 bps perp).
   Si un audit de profondeur décèle une illiquidité réelle,
   l'ajustement se documente AVANT l'écran, signé dans ce dossier.
4. Benchmark toujours couvert, mêmes coûts — chaque paire est comparée à
   sa propre couverture permanente ; aucune comparaison inter-paires
   avancée.
5. **Barre statistique durcie** : cinq tests simultanés = risque de faux
   positif multiplié. Seuil gelé avant les données : **t Newey-West
   ≥ 2,58 par paire** (Bonferroni, alpha = 0,01 / 5, bilatéral),
   drawdown ≤ 25 %, OOS netto > 0. Le carry BTC/ETH garde son seuil
   historique t ≥ 2,0.

## Ordre de falsification

1. Ingestion daily (closes spot + perp, funding 2020-01 → 2026-10),
   checksums, via les configs de téléchargement.
2. Écran vectoriel par paire (une seule entrée, jamais sortir) : IS/OOS,
   t ≥ 2,58, drawdown ≤ 25 %, OOS net > 0.
3. Si l'écran passe : moteur 1m, le même harnais (capital 20 000, levier
   interne 2, fraction 0,95), entrée à la première clôture daily
   d'octobredurable après le début OOS.
4. Si le moteur passe : stress, scénarios de queue, et un holdout
   pré-enregistré d'un mois jamais consulté pour cette paire.

## Out of scope

- BTC/ETH : déjà validés, portés par le paper. Pas de re-run.
- Toute paire hors la liste figée ci-dessus.
- Le paper d'un actif dont l'écran n'a pas franchi SA barre durcie.

## Gate de données (d'abord)

Pour chacune des cinq paires, vérifier avant l'écran : la profondeur des
archives daily spot/perp depuis 2020, l'open interest perp, et
l'historique funding complet. Une paire médiocre sort avant tout écran
avec un NO-GO technique documenté.
