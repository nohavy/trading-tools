# Feature Specification: Stratégie funding-momentum

**Feature Branch**: `005-funding-momentum`

**Created**: 2026-09-30

**Status**: Draft

**Input**: User description: "Stratégie funding-momentum : hook on_funding dans le moteur, stratégie à percentile roulant du funding (achat aux extrêmes positifs, hold 24-72h, maker), validation complète sur 6 mois (walk-forward, stress, verdict go/no-go)"

## User Scenarios & Testing

### User Story 1 - Le moteur délivre les échéances de funding à la stratégie (Priority: P1)

En tant qu'utilisateur, chaque échéance de funding est un événement dont la stratégie est informée (taux, instant), en plus de son application comptable au compte perpétuel déjà existante.

**Why this priority**: sans événement délivré, aucune stratégie ne peut réagir au funding.

**Independent Test**: une stratégie sonde qui enregistre les taux vus sur un run avec funding historique → la liste exacte.

**Acceptance Scenarios**:

1. **Given** un historique de funding et un run, **When** il tourne, **Then** la stratégie reçoit chaque échéance (taux exact, dans l'ordre, aux instants exacts) et le compte est débité/crédité comme déjà prévu.
2. **Given** un compte spot (pas de funding), **When** le run tourne, **Then** l'événement est quand même délivré (la stratégie décide, le compte ignore).

---

### User Story 2 - Une stratégie funding-momentum paramétrable (Priority: P2)

En tant qu'utilisateur, la stratégie entre à l'achat quand le taux de funding dépasse son percentile roulant (les N dernières échéances), maintient la position pendant une durée fixée, sort au marché, et gère une seule position à la fois.

**Why this priority**: c'est le premier signal du projet avec un edge brut confirmé hors des coûts.

**Independent Test**: sur des taux synthétiques connus, les entrées/sorties tombent aux échéances et barres attendues.

**Acceptance Scenarios**:

1. **Given** des taux synthétiques dont l'un dépasse le percentile roulant, **When** la stratégie tourne, **Then** elle achète à l'échéance suivante du franchissement et sort après la durée de détention fixée.
2. **Given** une position déjà ouverte, **When** une nouvelle échéance extrême arrive, **Then** aucun ordre supplémentaire n'est soumis (une seule position).
3. **Given** un percentile non atteignable (taux calmes), **When** le run tourne, **Then** aucun trade.

---

### User Story 3 - Validation complète : walk-forward, stress, verdict (Priority: P3)

En tant qu'utilisateur, la stratégie est jugée sur les critères du projet : optimisation par tronçons chronologiques avec évaluation hors-échantillon, survie aux coûts dégradés, et verdict go/no-go explicite avec compteur d'essais.

**Why this priority**: la constitution n'autorise pas le paper/live sans ce verdict.

**Independent Test**: le run complet sur 6 mois passe par walk-forward (folds chronologiques), stress (coûts dégradés), et produit un verdict argumenté critère par critère.

**Acceptance Scenarios**:

1. **Given** la stratégie et 6 mois de données, **When** le walk-forward tourne, **Then** les folds sont chronologiques, le meilleur paramètre par tronçon est choisi sur le train seul, et l'agrégat OOS est reporté avec le pourcentage de folds positifs.
2. **Given** le stress (frais ×1,5, slippage ×2, latence augmentée, combiné), **When** il tourne, **Then** seuls les coûts changent et la survie est reportée.
3. **Given** les résultats OOS + stress, **When** le verdict est calculé, **Then** chacun des sept critères est évalué avec son détail (aucune exception silencieuse).

### Edge Cases

- Historique de funding plus court que la fenêtre du percentile → aucune entrée tant que l'historique n'est pas assez long.
- Échéances manquantes (trous dans le fichier funding) → la stratégie réagit aux échéances présentes uniquement.
- Fin de données pendant une position → valorisation à la dernière clôture, run propre.
- Taux NaN dans le fichier → ignorés proprement.
- Période trop courte pour un fold → erreur claire (déjà prévu par le walk-forward).

## Requirements

### Functional Requirements

- **FR-001**: Le moteur DOIT délivrer à la stratégie un événement par échéance de funding (taux, instant) en plus de son application comptable.
- **FR-002**: La stratégie DOIT utiliser un percentile roulant calculé sur les N dernières échéances vues (fenêtre paramétrable).
- **FR-003**: La stratégie DOIT entrer au marché quand le taux dépasse son percentile roulant (seuil paramétrable), à la sortie d'une position unique après une durée de détention paramétrable.
- **FR-004**: La stratégie DOIT rester à une position à la fois et ne jamais superposer les entrées.
- **FR-005**: La validation DOIT réutiliser la chaîne existante : walk-forward chronologique, stress des coûts, verdict à sept critères.
- **FR-011 (n/a)**: (numérotation héritée — aucun autre requis.)

### Key Entities

- **FundingEvent (existant)** : taux + instant d'une échéance.
- **FundingMomentum** : la stratégie (fenêtre du percentile, seuil, quantité, durée de détention).
- **ValidationChain** : run → métriques → walk-forward → stress → verdict.

## Success Criteria

### Measurable Outcomes

- **SC-001**: La stratégie sondée reçoit exactement les taux du fichier, dans l'ordre.
- **SC-002**: Sur taux synthétiques, les entrées/sorties tombent aux instants exacts attendus.
- **SC-003**: Le run complet sur 6 mois produit des métriques avec round trips ≥ 20 et un verdict argumenté.

## Assumptions

- Le signal est confirmé sur BTC et ETH (edge brut net des coûts maker×maker positif aux horizons 24-72 h, ~30-40 événements dédupliqués en 6 mois).
- Les quantiles in-sample ne valent pas validation : le walk-forward chronologique et l'agrégat OOS font foi.
- Une seule position à la fois : le nombre de trades effectifs sera inférieur au nombre d'événements.
- Les frais de référence sont maker×maker UM (4 bps d'aller-retour).
- Le holdout (septembre 2026) reste verrouillé ; le verdict principal porte sur les folds OOS.