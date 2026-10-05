# Plan d'implémentation: carry toujours couvert dans le moteur événementiel

## Architecture

- `src/tradingv2/strategies/cash_carry.py`: deux jambes du même attelage,
  une entrée unique après `trade_start_ns`, aucune sortie :
  - `CashCarrySpotLeg` (long spot, compte cash) ;
  - `CashCarryPerpLeg` (short perp, compte margin) ;
  - paramètres communs `qty` (quantité de couverture) et `trade_start_ns`.
- `src/tradingv2/strategies/builtin.py`: enregistrement `carry_spot_leg`,
  `carry_perp_leg`.
- `configs/research-carry-engine-{btc,eth}.yaml`: jambes perp 1m (UM) ;
  les jambes spot 1m partagent la même structure avec `market: spot`.
- `configs/download-spot-1m-{btc,eth}.yaml`: données spot 1m 2023-04 →
  2026-08 (chauffe avril-juin + OOS).
- `scripts/run_carry_engine_validation.py`: exécute les deux jambes par actif,
  combine les courbes daily d'equity (somme), synthèse Newey-West et
  vérifications de fidélité d'exécution.
- `docs/carry-engine-result-2026-10.md`: verdict selon les critères figés.
- `tests/unit/test_strategy_cash_carry.py`: TDD des jambes.

## Hypothèses d'exécution

1. Motif 008 : décision à la clôture daily (00:00 UTC), fill à l'open 1m
   suivant, latence 150±50 ms, taker 5 bps + slippage 1 bp.
2. Jambe spot : compte cash, tampon de 5 % — coût d'entrée ≈ 9,6 k pour un
   compte de 10 k, aucun rejet de fonds.
3. Jambe perp : compte margin levier interne 2 avec notionnel = capital de
   jambe ≈ 10 k (marge requise ≈ 5 k) — l'exposition reste 1× notionnel et
   l'agrégat 19 k notionnel / 20 k capital est non levieré, conforme à l'écran.
4. Quantité de couverture unique : `qty = 0,95 × capital_total /
   (spot_close + perp_close)` à la clôture de décision, passée identique aux
   deux jambes ; chaque marché applique ses propres filtres (tick, step,
   minNotional) ; l'écart résiduel de couverture est mesuré.
5. L'entrée moteur est **fraîche en 2023-07** : elle paie coûts + basis à des
   prix OOS. L'écran toujours couvert était entré en 2020 — son OOS n'inclut
   pas ces coûts. Rapprochement attendu ≈ écran − ~20 bps de coûts d'entrée,
   pas une égalité exacte ; tout écart plus grand est investigué, jamais
   absorbé par un réglage.
6. Aucune fermeture à l'échéance de l'échantillon (règle gelée du
   pré-enregistrement) : les positions restent ouvertes et valorisées à la fin.

## Ordre TDD

1. RED/GREEN: jambes — une seule entrée, jamais avant `trade_start_ns`,
   quantité exacte, aucune sortie, comportement sur rejet.
2. Configs + données spot 1m (téléchargement réseau vérifié).
3. Runner : deux jambes par actif, courbe daily combinée continue, synthèse.
4. Exécution BTC/ETH, quality gates, verdict prudent documenté.

## Hors périmètre

- Rétro-ajuster la quantité ou les tampons après lecture des résultats.
- Multi-actifs simultanés dans un même Engine (le portefeuille est construit
  par agrégation de runs, motif 008).
