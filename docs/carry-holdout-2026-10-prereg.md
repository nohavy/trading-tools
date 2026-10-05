# Pré-enregistrement — holdout carry toujours couvert, octobre 2026

**Enregistré le 2026-10-05, avant téléchargement ou lecture de toute donnée
d'octobre.** La fenêtre est verrouillée : aucun chemin de prix d'octobre 2026
n'a été consulté. Septembre 2026 fut un holdout d'une autre hypothèse (trend
60j) : seule information de septembre utilisée ici, la **clôture daily du
2026-09-30 pour le dimensionnement de la quantité**, à la date de décision.

## Hypothèse gelée

Rejouer dans l'Engine 1m, sur le mois non consulté, l'attelage validé aux
features 009/010 (écran pré-enregistré + validation moteur + stress franchi) :

- Actifs et jambes : BTCUSDT et ETHUSDT, long spot (compte cash 10 000 USDT)
  / short perp UM (compte marge 10 000 USDT, levier interne 2, tampon de
  marge ; exposition agrégée ≤ 1×, capital total 20 000 USDT non levieré).
- Quantité unique de couverture : `qty = 0,95 × 20 000 /
  (spot_close[2026-09-30] + perp_close[2026-09-30])`, passée identique aux
  deux jambes, arrondie aux filtres réels de chaque marché ; jamais
  rééquilibrée, jamais sortie.
- Entrée : décision à la première frontière de clôture daily ≥
  2026-10-01 00:00 UTC (clôture du 2026-09-30), fill à l'open 1m suivant,
  latence déterministe 150±50 ms, seed 42.
- Coûts figés : spot 10 bps (maker/taker) + slippage 1 bp ; perp taker
  5 bps + slippage 1 bp.
- Funding : settlements réels UTC appliqués au short pendant la couverture ;
  les archives mensuelles UM du holdout (2026-10) sont complétées si besoin
  par l'endpoint officiel `/fapi/v1/fundingRate` au jour du lancement,
  checksums lorsque disponibles (même discipline que le holdout de
  septembre).
- Données : spot 1m et UM 1m du 2026-09-30 00:00 au 2026-10-31 23:59 UTC ;
  **aucun téléchargement ni lecture avant le 2026-11-01 00:00 UTC**, jour du
  lancement.
- Fenêtre verrouillée : **2026-10-01 00:00 UTC → 2026-11-01 00:00 UTC**
  (32 marques daily, 31 intervalles).

## Règle de décision — pas d'ajustement après ouverture

Ce mois est une **réplication**, pas un critère stat suffisant de GO. Ne
seront ni modifiés ni retunés après lecture : fraction 0,95, levier interne
2, coûts, date, actifs ou protocole de latence.

Checklist gelée, appliquée par le script au lancement :

1. **Exécution** : exactement 1 fill par jambe et par actif, 0 ordre rejeté,
   couverture spot/perp ≥ 0,99. Toute violation = échec technique : résultat
   non interprétable, investigation obligatoire, aucune retouche du
   protocole.
2. **Hypothèse « le carry survit au mois »** : net équipondéré BTC+ETH > 0,
   net BTC > 0, net ETH > 0, drawdown mensuel ≤ 2 %.
3. Sinon : **NO-GO holdout** — pas de paper ; l'OOS moteur 3,2 ans reste la
   démonstration, le mois renégatif ne déclenche aucune recherche d'un
   réglage alternatif sur octobre.
4. Passage du holdout ⇢ conditionné au stress **déjà franchi** (2026-10-05)
   ; un mois seul ne remplace jamais les seuils complets du validate.

## Comptabilisation des essais

`data/holdout_attempts.json` est à 2 au moment du gel (holdout trend). Au
lancement il sera incrémenté **deux fois avant tout accès aux données** : un
essai par actif (BTC, ETH), chacun touchant la fenêtre verrouillée. Le
marqueur `data/carry-holdout-2026-10.started.json` horodate l'ouverture.
