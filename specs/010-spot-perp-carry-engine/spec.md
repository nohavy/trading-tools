# Feature Specification: Carry neutre spot-perp dans le moteur événementiel

**Created**: 2026-10-05

**Status**: Approved for execution validation

## User Story

Valider dans le moteur événementiel que le carry neutre toujours couvert
(long spot / short perp de même quantité, capital non levieré, entrée unique)
survit à une exécution réaliste (fills 1m, latence, slippage, marge du short)
sur l'OOS 2023-07-01 → 2026-08-31, pour BTC et ETH, et rapprocher le résultat
de l'écran vectorisé pré-enregistré (+49,4 % total OOS).

## Acceptance Scenarios

1. Chaque jambe entre **une seule fois** pendant l'OOS : décision à la première
   clôture daily autorisée (`trade_start_ns`), remplie à l'open 1m suivant avec
   latence déterministe et slippage ; aucune sortie avant la fin de l'échantillon.
2. Le funding réel historique est crédité au short perp uniquement pendant que
   la couverture est ouverte ; aucune attribution postérieure à la clôture de
   décision.
3. Aucun ordre rejeté et aucune liquidation : le capital de jambe finance le
   notionnel perp (levier interne avec marge tampon, exposition agrégée
   toujours ≤ 1× par notionnel), le spot est payé comptant avec le tampon de
   sa jambe.
4. L'equity portefeuille est la somme des deux jambes, chacune marquée à son
   propre marché ; la courbe daily OOS est continue, sans trou.
5. Le verdict exige : t Newey-West ≥ 2,0, drawdown ≤ 25 %, OOS > 0, un fill
   par jambe et par actif, un ratio de couverture des quantités ≥ 99 %, et un
   rapprochement chiffré avec l'écran (l'entrée moteur est fraîche : elle paie
   un aller simple de coûts et de basis que l'écran, entré en 2020, n'a pas
   payé pendant l'OOS).
6. Les quantités des deux jambes sont identiques à l'entrée (une quantité de
   couverture unique passée aux deux jambes, arrondie aux filtres de chaque
   marché) ; l'écart résiduel est mesuré et documenté.

## Out of scope

- La règle de timing filtrée (seuil 15 bps) : rejetée à l'écran, jamais testée
  ici.
- Levier agrégé > 1×, rééquilibrage, volatility targeting, stop-loss.
- Paper/live : un GO moteur ne suffit jamais (constitution).
- Toute optimisation de paramètre après lecture des résultats moteur.
