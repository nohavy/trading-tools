# Pré-enregistrement — holdout trend 60j, septembre 2026

**Enregistré avant téléchargement/lecture des données du holdout.**

## Hypothèse gelée

- Actifs : perpétuels Binance UM BTCUSDT et ETHUSDT.
- Signal : rendement close-close des **60 derniers jours calendaires**; long si strictement positif, sinon flat. Aucun short, seuil, stop ou autre filtre.
- Décision : une fois par jour à 00:00 UTC après la clôture de la dernière bougie 1m; fills via l'Engine au prochain open 1m.
- Taille : viser 1× equity à l'entrée, quantité ensuite fixe jusqu'à la sortie; compte marge 10 000 USDT, levier 1.
- Coûts : taker 5 bps + slippage 1 bp par côté; latence déterministe 150±50 ms, seed 42; funding UM historique.
- Contrôle : buy-and-hold entrant au même timestamp, même capital, coûts, latence et funding.
- Holdout verrouillé : **2026-09-01 00:00 UTC à 2026-10-01 00:00 UTC** (marks daily, 30 intervalles).
- Warmup : bougies 1m du 2026-07-01 au 2026-08-31; aucune position ni PnL avant le holdout.

## Règle de décision — pas d'ajustement après ouverture

Cette fenêtre courte est un **test de réplication**, pas un critère suffisant de
GO statistique. Ne seront ni modifiés ni re-optimisés après consultation des
résultats : lookback, mode, coûts, date OOS, taille ou actifs.

- Hypothèse « survit au mois » : equity nette trend positive pour BTC et ETH,
  portefeuille trend équipondéré supérieur au buy-and-hold équipondéré, aucune
  liquidation/rejet de sortie.
- Sinon : fermer la piste de ce réglage (ne pas chercher un nouveau paramètre
  dans septembre).
- Quel que soit le résultat : **aucun paper/live** sur 30 jours; les seuils
  usuels t≥2, drawdown≤25 %, stress et walk-forward restent requis.

## Comptabilisation des essais

Le compteur `data/holdout_attempts.json` est à 0 avant l'expérience. Il sera
incrémenté **deux fois avant tout accès aux données** : un run trend et un run
benchmark, qui touchent tous deux la période verrouillée.
