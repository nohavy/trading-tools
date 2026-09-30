# Feature Specification: Étude d'edge et validation des stratégies

**Feature Branch**: `004-edge-validation`

**Created**: 2026-09-30

**Status**: Draft

**Input**: User description: "Validation finale des stratégies : étude d'edge vs coûts avant backtest, sweeps de paramètres avec cartes de stabilité, walk-forward, monte carlo sur les trades, stress des coûts, régimes de volatilité, holdout verrouillé avec compteur d'essais et verdict go/no-go"

## User Scenarios & Testing

### User Story 1 - Savoir si un signal bat les frais, avant tout backtest (Priority: P1)

En tant qu'utilisateur, pour un signal donné (retour à la moyenne, cassure, déséquilibre de flux), je vois les rendements qui suivent les signaux à plusieurs horizons (1 s à 15 min), confrontés aux coûts d'aller-retour de chaque combinaison produit × type d'ordre — et je sais en un coup d'œil si, où et quand l'edge existe.

**Why this priority**: le plan fondateur l'exige — c'est le filtre qui évite de backtester des idées non viables.

**Independent Test**: un signal connu sur des données synthétiques avec un rendement forward connu → le tableau montre exactement ces valeurs et le verdict par horizon.

**Acceptance Scenarios**:

1. **Given** un mois de barres et un signal, **When** l'étude tourne, **Then** un tableau donne par horizon : rendement moyen (bps), médiane, taux de réussite, excursions favorables/défavorables moyennes.
2. **Given** les coûts d'aller-retour par produit et type d'ordres, **When** le tableau est construit, **Then** chaque ligne porte le verdict « edge − coût » et le dépassement est lisible.
3. **Given** un signal sans événement sur la période, **When** l'étude tourne, **Then** le tableau l'indique proprement (zéro événement, pas de crash).

---

### User Story 2 - Balayer les paramètres et voir la stabilité (Priority: P2)

En tant qu'utilisateur, je balaye une grille de paramètres (fenêtres, seuils) en parallèle, et j'obtiens une carte de l'espérance nette par configuration : une bonne stratégie doit être bonne sur les voisins, pas seulement sur un point chanceux.

**Why this priority**: la carte de stabilité est le premier rempart contre le sur-ajustement.

**Independent Test**: une grille de quelques configurations sur des données synthétiques → tableau complet, déterministe, exécuté en parallèle.

**Acceptance Scenarios**:

1. **Given** une grille de N configurations, **When** le sweep tourne, **Then** N runs complets avec métriques sont produits et agrégés dans un tableau trié par espérance nette.
2. **Given** le même sweep relancé, **When** je compare, **Then** les résultats sont identiques (déterminisme).
3. **Given** un paramétrage qui déclenche trop peu de trades, **When** le sweep tourne, **Then** la configuration est marquée (trop peu de trades pour être jugée) et non promue.

---

### User Story 3 - Optimiser et tester sur des périodes séparées (walk-forward) (Priority: P3)

En tant qu'utilisateur, la période est découpée en tronçons chronologiques : les paramètres sont choisis sur un tronçon et évalués sur le suivant, puis la fenêtre glisse. Le résultat agrégé hors-échantillon est ce qui compte — plus le pourcentage de tronçons positifs.

**Why this priority**: c'est la validation standard contre l'optimisation opportuniste.

**Independent Test**: découpage déterministe d'une période en folds → métriques OOS agrégées + par fold.

**Acceptance Scenarios**:

1. **Given** une période et des durées d'entraînement/test, **When** le walk-forward tourne, **Then** les folds sont chronologiques sans recouvrement train/test et le rapport donne les métriques de chaque test et l'agrégat OOS.
2. **Given** des folds, **When** le verdict partiel est calculé, **Then** le pourcentage de folds nets positifs est exact.

---

### User Story 4 - Monte Carlo sur les trades (Priority: P4)

En tant qu'utilisateur, je mélange aléatoirement (avec remise) la séquence des trades d'un run pour estimer la dispersion : percentiles du PnL final, et probabilité qu'un drawdown dépasse un seuil.

**Why this priority**: un run unique ne dit rien de la distribution ; le bootstrap quantifie la chance.

**Independent Test**: les trades d'un run + 1000 tirages → percentiles exacts recalculés et proba de drawdown cohérente.

**Acceptance Scenarios**:

1. **Given** un run et un nombre de tirages, **When** le bootstrap tourne, **Then** p5/p50/p95 du PnL final et probabilité de drawdown > seuil sont produits, déterministes avec la graine.
2. **Given** un run sans trade, **When** le bootstrap tourne, **Then** il signale proprement l'impossibilité.

---

### User Story 5 - Résister au stress des coûts (Priority: P5)

En tant qu'utilisateur, je rejoue un run avec les coûts dégradés (frais ×1,5, slippage ×2, latence augmentée, et combiné) : si la stratégie survit, elle a une vraie marge.

**Why this priority**: les coûts réels dégradent toujours l'estimation ; une stratégie qui meurt au stress ne passera jamais le réel.

**Independent Test**: rejouer le même run avec chaque scénario → uniquement les coûts changent, verdicts de survie.

**Acceptance Scenarios**:

1. **Given** un run et les scénarios de stress, **When** chacun tourne, **Then** seul le bloc des coûts diffère et l'espérance nette de chaque scénario est reportée avec le verdict survivant/non.

---

### User Story 6 - Un verdict go/no-go explicite sur données verrouillées (Priority: P6)

En tant qu'utilisateur, un verdict go/no-go est calculé sur les critères fixés (nombre de trades, espérance nette positive et significative, profit factor, folds positifs, stress, drawdown) sur des données non utilisées pour l'optimisation ; chaque consultation de la période verrouillée est comptée pour surveiller le sur-ajustement.

**Why this priority**: c'est la porte d'entrée du paper trading — elle doit être explicable ligne par ligne.

**Independent Test**: des métriques connues injectées → verdict GO ou NO-GO exact ; le compteur d'essais s'incrémente à chaque consultation.

**Acceptance Scenarios**:

1. **Given** des métriques satisfaisant tous les critères, **When** le verdict est calculé, **Then** GO avec le détail de chaque critère ; sinon NO-GO avec la liste des critères manqués.
2. **Given** un run touchant la période verrouillée, **When** il tourne, **Then** le compteur d'essais persistant s'incrémente et apparaît dans le verdict.
3. **Given** l'agrégat walk-forward + stress, **When** le verdict est calculé, **Then** tous les critères du plan sont évalués sans exception silencieuse.

---

### User Story 7 - Lire les métriques par régime de volatilité (Priority: P7)

En tant qu'utilisateur, la performance d'un run est ventilée par régime (volatilité faible/moyenne/élevée, terciles) : une stratégie qui ne gagne que dans un régime est fragile.

**Why this priority**: complément de robustesse ; simple une fois les métriques prêtes.

**Independent Test**: une série d'équité avec trois régimes connus → métriques par tercile cohérentes.

**Acceptance Scenarios**:

1. **Given** un run, **When** les régimes sont calculés (terciles de volatilité réalisée), **Then** les métriques clés par régime sont produites et jointes au rapport.

### Edge Cases

- Signal sans événement → tableau d'edge vide mais propre (zéro événement affiché).
- Période plus courte que train+test → walk-forward impossible, erreur claire.
- Run sans trade → monte carlo et verdict impossibles, signalés proprement.
- Grille de un seul point → sweep valide (1 run).
- Compteur d'essais absent/corrompu → recréé proprement (jamais de crash).
- Terciles impossibles (trop peu de barres) → régime unique.

## Requirements

### Functional Requirements

- **FR-001**: L'étude d'edge DOIT produire, par signal et horizon {1 s, 5 s, 15 s, 30 s, 1 min, 5 min, 15 min} : rendement moyen et médian (bps), taux de réussite, excursions favorables et défavorables moyennes.
- **FR-002**: Chaque ligne d'edge DOIT être confrontée au coût d'aller-retour de chaque combinaison produit × paire d'ordres, avec le verdict « edge − coût ».
- **FR-003**: Les signaux fournis DOIVENT être : extrême de z-score (inversion), cassure de plage confirmée, déséquilibre de flux — construits sur les indicateurs existants.
- **FR-004**: Le sweep DOIT exécuter une grille de configurations en parallèle et produire un tableau trié par espérance nette avec marque « trop peu de trades ».
- **FR-005**: Le walk-forward DOIT découper chronologiquement (train/test sans recouvrement), optimiser une grille sur le train et rapporter les métriques OOS agrégées et par fold, dont le pourcentage de folds positifs.
- **FR-006**: Le monte carlo DOIT rééchantillonner les trades avec remise (graine fixée) et produire percentiles du PnL final et probabilité de drawdown au-delà d'un seuil.
- **FR-007**: Le stress DOIT rejouer le même run avec frais ×1,5, slippage ×2, latence augmentée, et un scénario combiné, en ne changeant que les coûts.
- **FR-008**: Le verdict DOIT appliquer les critères fixés : au moins 300 trades hors-échantillon, espérance nette positive avec t-stat ≥ 2, profit factor net ≥ 1,2, au moins 70 % de folds positifs, survie au stress, drawdown sous seuil.
- **FR-009**: Tout run dont la période touche la période verrouillée DOIT incrémenter un compteur d'essais persistant, affiché dans le verdict.
- **FR-010**: Les régimes de volatilité (terciles) DOIVENT ventiler les métriques clés du run.
- **FR-011**: Toutes les sorties (tableaux, verdicts, distributions) DOIVENT être déterministes à graine fixée et tolérer les cas dégénérés sans crash.

### Key Entities

- **SignalEvent** : instant et direction d'un signal détecté (audit des entrées).
- **EdgeTable** : tableau signal × horizon × {rendements, hit rate, excursions, coûts, verdict}.
- **SweepResult** : métriques de chaque configuration de la grille + classement.
- **WalkForwardResult** : folds (train/test), métriques OOS agrégées, % folds positifs.
- **MonteCarloResult** : percentiles du PnL final, probabilité de drawdown > seuil.
- **StressResult** : espérance nette par scénario + verdict de survie.
- **Verdict** : critère par critère GO/NO-GO + compteur d'essais holdout.
- **RegimeSplit** : métriques par tercile de volatilité.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Sur des données synthétiques à rendement forward connu, l'étude d'edge reproduit exactement ces valeurs (1e-9).
- **SC-002**: Un sweep de 20 configurations sur un mois de données s'exécute en moins de 10 minutes, déterministe.
- **SC-003**: Le walk-forward produit des folds chronologiques exacts (aucun recouvrement), vérifiables par golden.
- **SC-004**: 1000 tirages de monte carlo s'exécutent en moins de 10 s et sont reproductibles.
- **SC-005**: Le stress ne change que les coûts : le reste du run est identique octet par octet.
- **SC-006**: Le verdict applique les critères exacts, testé par golden sur des métriques injectées.

## Assumptions

- L'optimisation (sweep, walk-forward) utilise des grilles explicites ; pas de recherche bayésienne dans cette feature.
- La période verrouillée est septembre 2026 (données journalières, à télécharger au premier besoin).
- Un seul instrument et une seule stratégie par étude.
- Le verdict final est porté par l'agrégat walk-forward et le stress ; l'étude d'edge oriente mais ne juge pas.
- Les signaux sont calculés sur les barres 1 s (features) ; le pas à pas n'est pas requis pour la recherche.
- Performance : parallélisme par processus pour les sweeps ; monte carlo vectorisé numpy.