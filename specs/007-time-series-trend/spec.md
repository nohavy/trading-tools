# Feature Specification: Étude de trend temporel sur BTC/ETH

**Feature Branch**: `007-time-series-trend`

**Created**: 2026-10-01

**Status**: Approved for research

**Input**: User request: « regardons le trend temporel » après le NO-GO du momentum cross-sectionnel.

## User Scenarios & Testing

### User Story 1 - Mesurer le trend temporel sans fuite (Priority: P1)

En tant qu'utilisateur, je veux tester si le signe du rendement passé d'un actif prédit son rendement futur, indépendamment des autres actifs.

**Independent Test**: des séries synthétiques ascendantes/descendantes produisent les expositions attendues, et le PnL ne commence qu'après la clôture ayant rendu le signal observable.

**Acceptance Scenarios**:

1. **Given** un rendement passé positif à la clôture t, **When** le signal est calculé, **Then** l'exposition ne rémunère que le rendement de t à t+1 et les intervalles suivants.
2. **Given** un signal long/short et un signal long/flat, **When** le rendement passé est négatif, **Then** le premier est short et le second flat.
3. **Given** une inversion de position, **When** le coût est calculé, **Then** le turnover valorise les contrats fermés et rouverts, plus tout rééquilibrage dû à la dérive d'exposition.

### User Story 2 - Évaluer une règle perpétuelle nette de coûts (Priority: P1)

En tant qu'utilisateur, je veux que les rendements incluent les frais, le slippage modélisé et les settlements de funding réellement observés pour BTCUSDT et ETHUSDT.

**Independent Test**: des settlements synthétiques alignés aux intervalles quotidiens débitent un long à taux positif et créditent un short.

**Acceptance Scenarios**:

1. **Given** des settlements funding dans l'intervalle de détention, **When** le PnL est calculé, **Then** chacun est appliqué au close 1m complété avant le settlement et avec le signe de l'exposition en vigueur.
2. **Given** un coût de 2 bps par côté, **When** l'exposition passe de flat→long→flat, **Then** le coût total est 4 bps de notionnel.
3. **Given** aucune position n'est ouverte (mode long/flat en tendance négative), **When** funding est positif, **Then** aucun funding n'est débité.

### User Story 3 - Séparer sélection et validation chronologique (Priority: P1)

En tant qu'utilisateur, je veux comparer plusieurs lookbacks sur BTC/ETH, choisir les hypothèses uniquement en IS puis lire leurs résultats OOS.

**Independent Test**: les statistiques IS et OOS portent sur des intervalles disjoints, tandis que les signaux OOS gardent leur historique de chauffe pré-2023.

**Acceptance Scenarios**:

1. **Given** lookbacks 20/60/90/180/252 jours, **When** l'étude tourne, **Then** elle compare long/short, long/flat et buy-and-hold sur les mêmes dates de rendement pour chaque lookback.
2. **Given** IS 2020-01-01..2023-06-30 et OOS 2023-07-01..2026-08-31, **When** les métriques sont produites, **Then** l'OOS n'est jamais utilisé pour sélectionner un paramètre.
3. **Given** le rendement net quotidien, **When** le rapport est calculé, **Then** il contient rendement annualisé, volatilité, Sharpe, drawdown, t-stat Newey-West, turnover, exposition, coûts et funding.

## Edge Cases

- Historique inférieur au lookback ou à la fenêtre de volatilité → exposition flat, jamais de signal précoce.
- Timestamps de funding au bord des bougies → settlement compté une seule fois et affecté à l'exposition en vigueur après la clôture précédente.
- Valeurs non finies, prix non positifs, timestamps non croissants ou données manquantes → erreur explicite, pas de remplissage silencieux.
- Fin de données avec position ouverte → dernière position valorisée, sans liquidation artificielle.
- PnL indicatif daily ≠ simulation d'exécution intraday ; aucun verdict GO/paper/live ne peut en découler seul.

## Requirements

### Functional Requirements

- **FR-001**: Le signal DOIT être `sign(close[t] / close[t-lookback] - 1)` connu après la clôture t.
- **FR-002**: L'exposition calculée à t DOIT s'appliquer uniquement au rendement close[t]→close[t+1].
- **FR-003**: L'étude DOIT supporter les modes long/short et long/flat et le benchmark buy-and-hold.
- **FR-004**: Le PnL DOIT appliquer les taux exacts dont le timestamp tombe dans l'intervalle, valorisés au close 1m complété avant le settlement, selon `PnL funding = -position × rate × notionnel`.
- **FR-005**: Les coûts DOIVENT être calculés au turnover réel des contrats pour revenir à l'exposition cible 1×, y compris la dérive des shorts/equity, avec coût par côté paramétrable et slippage explicite.
- **FR-006**: Les lookbacks étudiés DOIVENT être 20/60/90/180/252 jours, BTCUSDT et ETHUSDT séparément puis portefeuille équipondéré.
- **FR-007**: L'étude DOIT reporter une séparation chronologique IS/OOS fixe ; l'historique IS peut chauffer les indicateurs OOS sans que son PnL entre dans l'OOS.
- **FR-008**: Le rapport DOIT produire métriques de rendement net et verdict explicite, mais ne DOIT PAS qualifier le résultat de stratégie exécutable/validée sans simulation événementielle ultérieure.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Les tests unitaires couvrent le décalage d'exécution, l'inversion long/short, le coût de turnover, le signe du funding, la chauffe et les métriques.
- **SC-002**: La recherche couvre les données disponibles 2020-01..2026-08 pour BTC et ETH, avec funding historique inclus.
- **SC-003**: Le rapport indique si un paramètre choisi en IS survit à l'OOS après coûts, sans optimiser sur l'OOS.

## Assumptions

- Les barres Binance UM 1d sont ouvertes à 00:00 UTC ; la décision utilise la clôture de la barre.
- Coûts indicatifs par côté : frais maker 2 bps ou taker 5 bps, plus 1 bp de slippage modélisé. Le spread/impact réel devra être confirmé par un futur backtest moteur.
- Les expositions sont en multiples du notionnel/equity journalier, plafonnées à 1x dans cette étude (pas de levier implicite).
- Il s'agit d'un écran de recherche vectorisé ; une hypothèse survivante devra être reproduite dans l'Engine et stressée avant tout GO.
