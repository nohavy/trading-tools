# Trend temporel BTC/ETH — candidat prometteur, NO-GO actuel

Date : 2026-10-01 · Specs : `007-time-series-trend`, `008-time-series-trend-engine`

## Verdict

Le **trend temporel long/flat 60 jours** est le premier candidat daily qui
survit à une simulation événementielle réaliste et bat le benchmark équipondéré
BTC/ETH sur la période observée. Il **ne passe pas encore les critères de
validation** : le t-stat Newey-West est 1,53 (< 2,0) et le drawdown max est
36,8 % (> 25 %). Le lookback a en outre été retenu après inspection de cet OOS
vectorisé. **NO-GO pour paper/live**; conserver comme hypothèse pour un futur
holdout réellement non consulté.

## 1. Écran vectorisé daily (feature 007)

### Protocole

- BTCUSDT et ETHUSDT UM, klines 1d + funding historique 2020-01..2026-08.
- Signal à la clôture t : `close[t] / close[t-lookback] - 1`.
- Position appliquée seulement après la clôture; lookbacks 20/60/90/180/252 j.
- Modes : long/short, long/flat (long si le rendement passé est positif),
  buy-and-hold. Exposition cible max 1× equity.
- Funding aux taux Binance exacts, valorisé au close 1m terminé avant chaque
  settlement. Frais par côté maker 2 bps ou taker 5 bps, slippage estimé 1 bp.
- IS 2020-09..2023-06, OOS 2023-07..2026-08; chauffe commune de 252 jours.
- Rendements OOS consultés pour plusieurs cellules : seuls les résultats choisis
  par IS sont une évaluation chronologique, les autres restent diagnostics.

### Résultats qui guident la suite

| Règle équipondérée BTC/ETH | IS CAGR / Sharpe | OOS CAGR / Sharpe | OOS t NW / DD max |
|---|---:|---:|---:|
| Paramètre au Sharpe IS max : 252j long/flat, maker | 81,6 % / 1,28 | 6,2 % / 0,35 | 0,66 / 42,5 % |
| Challenger 60j long/flat, maker — OOS exploratoire | 70,6 % / 1,25 | 31,8 % / 0,95 | 1,59 / 34,8 % |
| Buy-and-hold, maker | 44,2 % / 0,87 | 14,2 % / 0,51 | 0,91 / 60,7 % |

Le lookback sélectionné uniquement sur IS (252 j) ne bat pas le benchmark en
OOS. Le challenger 60 j fait mieux, y compris en taker (31,1 % CAGR OOS,
Sharpe 0,94), mais l'avoir retenu après consultation de plusieurs cellules OOS
le rend **exploratoire**. Ce signal ne prouve donc pas encore un edge.

## 2. Confirmation événementielle 1m (feature 008)

Le candidat 60j long/flat a été exécuté dans l'Engine sur les bougies UM 1m
2023-04..2026-08. Avril-juin sert uniquement au warmup; les ordres commencent
au 2023-07-01. La stratégie utilise la clôture daily à 00:00 UTC, soumet les
ordres par `Context`, remplit au prochain open 1m avec latence déterministe
150±50 ms, taker 5 bps et slippage 1 bp/côté. Funding historique est appliqué
aux positions ouvertes, marqué au dernier prix 1m connu. Capital 10 000 USDT,
levier configuré à 1×; buy-and-hold est entré au même instant.

| Portefeuille équipondéré BTC/ETH | Total OOS | CAGR | Sharpe | t NW-20 | DD max |
|---|---:|---:|---:|---:|---:|
| Trend 60j long/flat | +124,4 % | **29,1 %** | **0,895** | **1,53** | **36,8 %** |
| Buy-and-hold | +46,9 % | 12,9 % | 0,509 | 0,91 | 70,4 % |

| Actif | Trend CAGR / DD | Buy-and-hold CAGR / DD | Fills trend |
|---|---:|---:|---:|
| BTCUSDT | 22,2 % / 40,5 % | 24,7 % / 61,1 % | 57 |
| ETHUSDT | 32,5 % / 41,9 % | −3,8 % / 79,1 % | 39 |

Le portefeuille trend est positif chaque sous-période : +17,1 % en 2023H2,
+41,9 % en 2024, +28,7 % en 2025, +4,9 % en 2026 YTD. Les t-stats par
sous-période restent faibles; ces segments ne sont pas des validations
indépendantes. Les frais réellement débités sur les fills du challenger
s'élèvent à environ 695 USDT sur les deux comptes de 10 000 USDT; slippage
environ 139 USDT. Le PnL d'equity inclut aussi le funding.

## 3. Défaut moteur corrigé

Cette validation a révélé qu'une sortie sur compte margin pouvait être rejetée
quand l'equity avait baissé sous le notionnel, car `_check_funds` traitait la
quantité de clôture comme une nouvelle position. Le contrôle ne demande
maintenant de marge additionnelle que pour l'exposition réellement ouverte; une
régression teste le scénario d'une fermeture sous marge initiale.

## Limites et décision

- **Statistique** : t=1,53 reste sous la barre 2,0; DD=36,8 % dépasse 25 %.
- **Sélection** : 60 j est le challenger découvert en lisant l'OOS, et non une
  hypothèse pré-enregistrée. Le résultat événementiel n'efface pas ce biais.
- **Exécution** : bars-only au pas 1m, sans replay aggTrades, spread variable ni
  impact de marché; 1 bp de slippage reste une hypothèse.
- **Risque** : simple filtre de régime; pas de volatility targeting ni de
  contrôle drawdown. Le capital peut subir de longues baisses.

Décision : **NO-GO pour paper et live**. Prochaine étape scientifique : figer
60j long/flat et ses paramètres, puis l'évaluer sur un holdout futur non
consulté ou un protocole walk-forward pré-enregistré, avec stress slippage et
drawdown. Ne pas retoucher le lookback sur la période déjà étudiée.
