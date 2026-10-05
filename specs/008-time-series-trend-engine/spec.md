# Feature Specification: Trend temporel dans le moteur événementiel

**Feature Branch**: `008-time-series-trend-engine`

**Created**: 2026-10-01

**Status**: Approved for execution validation

**Input**: Résultat exploratoire de la feature 007 : le filtre long/flat 60 jours est le candidat vectorisé le plus régulier, mais reste sous les seuils GO et son OOS est déjà exploré.

## User Scenarios & Testing

### User Story 1 - Exécuter un signal trend daily sur le moteur 1m (Priority: P1)

En tant qu'utilisateur, je veux décider à partir de clôtures daily, mais faire passer les ordres, les frais, la latence et le funding dans le moteur événementiel existant.

**Independent Test**: un jeu de bougies synthétiques vérifie l'instant de décision à la clôture daily et le fill au plus tôt sur la minute suivante.

**Acceptance Scenarios**:

1. **Given** moins de `lookback_days + 1` clôtures daily, **When** une journée se clôt, **Then** aucun signal n'est émis.
2. **Given** un rendement sur lookback strictement positif, **When** la clôture daily est connue, **Then** une entrée long est demandée et ne peut être remplie qu'après la décision.
3. **Given** une position long et un rendement lookback nul ou négatif, **When** la clôture daily est connue, **Then** la sortie est demandée une seule fois.
4. **Given** une date de début OOS, **When** le moteur tourne sur la période de warmup, **Then** aucun ordre stratégie n'est soumis avant cette date.

### User Story 2 - Comparer le candidat avec buy-and-hold dans les mêmes conditions (Priority: P1)

En tant qu'utilisateur, je veux comparer le 60j long/flat à un buy-and-hold déclenché à la même date sur les mêmes données 1m, avec même capital, levier, funding, frais, slippage et latence.

**Independent Test**: le mode benchmark entre une fois à la date OOS, reste long et traverse les mêmes événements de funding.

**Acceptance Scenarios**:

1. **Given** le mode buy-and-hold, **When** le début de trading arrive, **Then** une seule entrée long est soumise et aucune sortie trend n'est envoyée.
2. **Given** les bougies et les settlements funding historiques, **When** le runner exécute le test, **Then** les ordres sont remplis par l'exchange simulé, les frais/slippage sont comptabilisés et le funding utilise le dernier prix connu.
3. **Given** la période vectorisée OOS déjà explorée (2023-07..2026-08), **When** le résultat événementiel est lu, **Then** il est explicitement qualifié de validation d'exécution exploratoire, et non de holdout indépendant ou de GO.

## Edge Cases

- Un settlement funding coïncide avec une clôture daily : l'ordre nouveau ne peut pas recevoir le settlement antérieur à son fill.
- Ordre en vol, rejeté ou annulé : aucun ordre doublon n'est envoyé; une nouvelle décision sera tentée à la clôture daily suivante.
- Données 1m manquantes à la frontière UTC : la stratégie ne fabrique pas de clôture daily hors des barres reçues.
- Trend à rendement exactement nul : long/flat devient flat.
- Quantité arrondie sous minNotional ou insuffisance de marge : le rejet exchange reste visible et la stratégie peut retenter à la prochaine clôture.

## Requirements

### Functional Requirements

- **FR-001**: La stratégie DOIT conserver une série des clôtures des barres 1m qui ferment à 00:00 UTC et calculer `close[t] / close[t-lookback] - 1` uniquement quand une nouvelle clôture daily est disponible.
- **FR-002**: Le mode `long_flat` DOIT viser 1× equity long si le rendement est positif, sinon flat; l'entrée est dimensionnée à partir de l'equity et du close observé.
- **FR-003**: Le mode `buy_hold` DOIT entrer long une fois au début de trading et rester exposé jusqu'à la fin du run.
- **FR-004**: Les ordres DOIVENT passer par `Context` et `SimulatedExchange`; aucune exécution synthétique interne n'est permise.
- **FR-005**: La stratégie DOIT gérer les ordres en attente pour éviter doublons et réagir aux rejets par une nouvelle tentative seulement à une clôture daily ultérieure.
- **FR-006**: Une date/horodatage `trade_start_ns` DOIT permettre le warmup historique sans prise de position ni PnL avant l'OOS.
- **FR-007**: Le test OOS DOIT utiliser les barres 1m BTCUSDT et ETHUSDT, funding historique, capital 10 000 USDT, levier 1, taker 5 bps, slippage 1 bp/côté et latence déterministe 150±50 ms.
- **FR-008**: Le rapport DOIT comparer les métriques d'equity daily du candidat et du benchmark sur les mêmes dates OOS et rappeler qu'aucun GO n'est possible sans un holdout ultérieur non exploré.
- **FR-009**: Une validation d'ordre de réduction/fermeture sur un compte margin DOIT être autorisée sans marge additionnelle; seul le résiduel d'un retournement de position consomme de la marge nouvelle.

## Success Criteria

- **SC-001**: Des tests d'intégration Engine valident entrée/sortie, OOS start, ordre en vol et buy-and-hold.
- **SC-002**: Les backtests de BTC et ETH terminent sans exception et écrivent leurs artefacts habituels (trades, equity, funding, metrics).
- **SC-003**: Le rapport sépare clairement le résultat vectorisé sélectionné IS du challenger 60j et expose la différence due aux fills/funding/capitalisation du moteur.

## Assumptions

- La décision trend se fait uniquement à la clôture 00:00 UTC, après l'événement funding de même timestamp selon l'ordre du moteur.
- Les bougies 1m sont lues depuis `data/parquet/um/klines/{symbol}/1m`; elles fournissent aussi un mark frais aux settlements funding.
- Le 60j long/flat est un candidat exploratoire observé après lecture de l'OOS; sa simulation ne transforme pas cette période en holdout indépendant.
