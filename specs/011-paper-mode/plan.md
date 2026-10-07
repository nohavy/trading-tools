# Plan d'implémentation: mode paper

## Architecture

- `src/tradingv2/paper/` (nouveau package) :
  - `feed.py` : polling REST des klines 1m publics (spot et UM) + endpoint
    fundingRate ; déduplication par `ts_close_ns`, backfill des barres
    manquées après coupure (≤ 1 500 klines/requête) ; client HTTP injectable
    pour les tests.
  - `session.py` : la boucle événementielle paper — deux `SimulatedExchange`
    coordonnés par la même horloge (une jambe par marché du candidat) ; la
    sémantique `Context` est réutilisée telle quelle ; la jambe spot et la
    jambe perp partagent la quantité de couverture calculée à l'entrée comme
    le runner.
  - `state.py` : snapshot JSON atomique (tmp + rename) — position par jambe,
    ordres avec statuts, marques d'equity daily, état de stratégie, seed de
    latence ; reprise = rechargement puis rattrapage des barres/settlements
    manqués.
  - `gate.py` : empreinte sha256 de la section figée d'une config + lecture
    du verdict du holdout (`data/carry-holdout-2026-10.json`) ; refus net si
    non franchi et non `experimental: true`.
- `src/tradingv2/cli.py` : sous-commandes `paper run` (avec `--once` pour
  n'absorber qu'une barre — smoke), `paper status`, `paper report`.
- `configs/paper-carry-{btc,eth}.yaml` : configs du candidat + `validation_sha256`
  attendu (gelé au verdict du holdout).
- Stratégies : interface optionnelle `save_state`/`load_state` sur `Strategy`
  (défaut : inférer de la position — pour les jambes une-entrée, position ≠ 0
  ⇒ déjà soumis) ; le contrat « même code » est le critère du golden test.

## Hypothèses d'exécution

1. La boucle paper réutilise la mécanique exacte de `Engine.run` — la
   refonte minimale visée : extraire la boucle d'événements pour accepter un
   flux itérable de barres (le backtest en consomme une liste finie, paper
   un flux infini) sans changer l'ordre constitutionnel.
2. Le pas de temps est 1m ; les décisions daily restent aux frontières
   00:00 UTC (même sémantique que le backtest) ; la latence fait arriver les
   fills dans la barre suivante comme en backtest.
3. Le polling REST : 1 requête/minute/jambe — très en dessous des limites
   publiques ; coupure réseau = retry exponentiel avec garde-fou, puis
   reprise par backfill (jamais une barre sautée).
4. Funding manqué pendant un arrêt : backfill par l'endpoint historique,
   appliqué aux settlements ≤ maintenant et > dernier settlement connu.
5. Aucune réécriture du sizing : la fraction 0,95, le levier interne 2 et
   les coûts figés sont ceux des configs validées.
6. L'empreinte de validation ne couvre QUE la section figée (data/account/
   costs/strategy) — pas les chemins locaux ni les seeds d'affichage.

## Ordre TDD

1. RED/GREEN: feed sur client HTTP synthétique — clôtures 1m, déduplication,
   backfill après coupure, funding backfillé.
2. RED/GREEN: session — golden test « mêmes fills que le backtest » sur les
   mêmes barres rejouées en flux.
3. RED/GREEN: persistance/reprise — interruption simulée entre deux barres,
   reprise sans double ordre, sans perte.
4. RED/GREEN: kill switch (fichier + Ctrl-C) et gate d'empreinte (refus/
   experimental).
5. Smoke CLI `--once`/`--status`/`report`, puis exécution réelle d'au moins
   un hour complet en simulé avant toute ouverture paper effective.

## Risques connus

- REST vs WebSocket : latence de données plus variable — acceptée en paper
  (documentée dans le rapport), le live exigera la réflexion WS.
- Bars-only en live (pas d'aggTrades) : le slippage reste le modèle figé.
- La reprise après un crash mid-minute : la barre en cours est re-traitée
  depuis son open (déduplication par ts_close) — un ordre déjà arrivé ne
  peut pas être rejoué (statuts persistés).
