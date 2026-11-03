# Résultat du holdout carry toujours couvert — octobre 2026

Essai pré-enregistré (`docs/carry-holdout-2026-10-prereg.md`), lancement
effective le **2026-11-03** après l'ouverture de la fenêtre. Compteur
d'essais : 4 après le run (BTC + ETH).

## Audits de lancement (transparence)

- Lancement 1 (03/11) : avorté — fichier 1d de dimensionnement manquant
  (spot + UM septembre). AUCUNE donnée d'octobre lue, aucun verdict.
- Lancement 3 (03/11) : avorté à la combinaison des jambes — l'archive
  mensuelle UM d'octobre sur Vision est **incomplète** : un trou de
  1 441 minutes (le 2026-10-28 00:00→24:00) identique BTC et ETH. Les
  1 440 barres manquantes ont été récupérées via l'endpoint officiel
  `fapi/v1/klines` (public, sans clé) **avant tout calcul de verdict**,
  puis appliquées au parquet (sha256 du manifeste données re-calculé) ;
  la contiguïté 1 m a été vérifiée pour les deux jambes.
- Deux resets du compteur documentés dans `data/holdout_attempts.json`
  (aucun ajustement de protocole, aucun résultat lu avant l'essai final).
- Le fichier septembre (spot et UM) comporte 2 jours d'archive manquants
  identiques des deux côtés — les marques daily restent alignées, la
  fenêtre verrouillée d'octobre est intacte.

## Données

- Spot 1m + UM 1m + funding + daily closes, 2026-09-01 → 2026-10-31
  (post-telechargements, checksums Binance Vision ; les trous documentés
  au-dessus).
- Contrôles gelés : 1 fill par jambe et par actif, 0 rejet, couverture
  ≥ 0,99, net > 0 (BTC, ETH, équipondéré), DD mensuel ≤ 2 %.

## Résultat

| Actif | Actif net = position | DD | Couverture | Fills | Rejets |
|---|---:|---:|---:|---|---|
| BTCUSDT | **+0,08 %** | **0,07 %** | 0,9950 | 1/pièce | 0 |
| ETHUSDT | **+0,06 %** | **0,08 %** | 1,0000 | 1/pièce | 0 |

**VERDICT GELÉ: HOLDOUT PASSED.**

## Signification et limites

- La réplication sur un mois **jamais vu** franchit tous les critères
  figés : un mois seul ne remplace pas les seuils complets, mais il ferme
  le programme de falsification exécuté du carry (écran → moteur →
  stress → bear → holdout).
- Le rendement du mois (+0,07 % équipondéré) est du même ordre que la
  moyenne mensuelle OOS 3,2 ans (≈ +1,3 %) divisée par deux — l'edge peut
  se résorber ; le bootstrap de blocs (`data/carry_tail_scenarios.json`)
  reste le juge des plages mensuelles.
- Les empreintes figées des deux configs (BTC et ETH) ont été enregistrées
  dans le verdict JSON → la porte paper (`gate_check`) s'ouvre pour ces
  configurations exactes, conformément à la spécification 011.

## Prochaine étape autorisée

T010 du feature 011 : création des configs paper-carry portant ces
empreintes, smoke `tv2 paper run --once`, puis la session paper réelle
(≥ 30 jourss, ≥ 90 settlements) avant toute idée de live.
