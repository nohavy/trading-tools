# Feature Specification: Stratégies, métriques et rapport

**Feature Branch**: `003-strategies-metrics-report`

**Created**: 2026-09-30

**Status**: Draft

**Input**: User description: "Stratégies réelles paramétrables (meanrev z-score, breakout volume, orderflow imbalance, buy hold), indicateurs vectorisés et incrémentaux avec parité testée, métriques complètes net de frais, rapport HTML autonome et comparaison de runs"

## User Scenarios & Testing

### User Story 1 - Des indicateurs fiables, identiques en recherche et en temps réel (Priority: P1)

En tant qu'utilisateur, je calcule des indicateurs (moyennes, volatilité, déséquilibre de flux) de deux façons : en lot rapide sur toute l'historique (recherche) et pas à pas comme en direct. Les deux méthodes produisent les mêmes valeurs, garantissant que ce que je valide en backtest est ce que le live calculera.

**Why this priority**: une divergence entre les deux implémentations invaliderait tout : le backtest validerait un calcul que le live ne reproduirait pas.

**Independent Test**: sur un mois de données réelles, chaque indicateur calculé des deux façons donne des valeurs identiques à l'arrondi machine près.

**Acceptance Scenarios**:

1. **Given** un mois de barres 1s réelles, **When** chaque indicateur est calculé en lot puis pas à pas, **Then** les valeurs coïncident à 1e-9 relatif près.
2. **Given** une série plus courte que la fenêtre d'un indicateur, **When** il est calculé, **Then** il vaut absence-de-valeur tant que la fenêtre n'est pas pleine (et jamais une valeur partielle trompeuse).

---

### User Story 2 - Des stratégies réelles paramétrables par YAML (Priority: P2)

En tant qu'utilisateur, je lance des stratégies de trading concrètes en ne changeant que le YAML : retour à la moyenne (entrée quand le prix s'écarte trop, sortie au retour), cassure de plage avec confirmation de volume, déséquilibre acheteurs/vendeurs, et une référence achat-étude pour comparer.

**Why this priority**: ce sont les candidats à valider en phase 4 ; sans eux, pas de stratégie à évaluer.

**Independent Test**: chaque stratégie exécutée sur un mois de données avec des paramètres explicites produit des trades cohérents avec ses règles (vérifiables trade par trade).

**Acceptance Scenarios**:

1. **Given** une stratégie de retour à la moyenne configurée (fenêtre, seuil d'entrée, seuil de sortie, stop, durée maximale), **When** elle tourne, **Then** elle n'entre que lorsque l'écart dépasse le seuil, sort au retour ou au stop, et ferme au-delà de la durée maximale.
2. **Given** une stratégie de cassure configurée (fenêtre de plage, facteur de volume), **When** le prix casse la plage sur un volume confirmé, **Then** elle prend position dans le sens de la cassure.
3. **Given** une stratégie de flux configurée (fenêtre, seuil de déséquilibre), **When** le flux acheteur domine au-delà du seuil, **Then** elle prend position dans le sens du flux.

---

### User Story 3 - Des métriques complètes, nettes de frais (Priority: P3)

En tant qu'utilisateur, chaque run est résumé par des métriques standard : rendement, ratios risque-rendement, drawdown, statistiques de trades, et surtout la décomposition des coûts — combien les frais, le slippage et le funding ont mangé des gains bruts.

**Why this priority**: le net après frais est la seule vérité (constitution) ; ces chiffres décident du go/no-go.

**Independent Test**: métriques recalculées à la main sur un petit jeu de trades connu → identiques à 1e-9.

**Acceptance Scenarios**:

1. **Given** un run, **When** les métriques sont calculées, **Then** rendement, Sharpe, Sortino, drawdown maximal, profit factor, taux de réussite, gain moyen par trade et t-statistique de l'espérance sont présents et exacts.
2. **Given** un run avec frais et slippage, **When** je lis la décomposition des coûts, **Then** net = brut − frais − slippage − funding, et la part des frais dans le brut (drag) est affichée.
3. **Given** un run sans aucun trade, **When** les métriques sont calculées, **Then** les métriques de trades valent absence-de-valeur sans erreur, et le rapport l'indique explicitement.

---

### User Story 4 - Un rapport HTML lisible et autonome (Priority: P4)

En tant qu'utilisateur, chaque run produit un fichier HTML unique s'ouvrant dans un navigateur sans connexion : courbe d'équité et drawdown, distribution des gains par trade, tableau de métriques, décomposition des coûts.

**Why this priority**: la lecture visuelle accélère le diagnostic ; le fichier autonome garantit l'archivage avec le run.

**Independent Test**: après un run, le rapport existe, pèse moins de 2 Mo, et contient les sections attendues.

**Acceptance Scenarios**:

1. **Given** un run terminé, **When** le rapport est généré, **Then** `report.html` existe dans le dossier du run, autonome (aucune ressource externe), avec équité, drawdown, trades, métriques et coûts.
2. **Given** un run sans trade, **When** le rapport est généré, **Then** il s'affiche proprement avec la mention « aucun trade ».

---

### User Story 5 - Comparer plusieurs runs (Priority: P5)

En tant qu'utilisateur, je compare des runs (paramètres différents, périodes différentes) dans un tableau côte à côte des métriques, pour choisir une configuration sur des chiffres.

**Why this priority**: nécessaire aux sweeps de la phase 4 ; fourni tôt car simple une fois les métriques prêtes.

**Independent Test**: `tv2 compare run_A run_B` → tableau aligné des métriques des deux runs.

**Acceptance Scenarios**:

1. **Given** deux dossiers de runs, **When** je lance la comparaison, **Then** un tableau met les métriques côte à côte (par colonne de run) et un résumé HTML est produit.

### Edge Cases

- Série plus courte que la fenêtre → indicateurs vides, stratégie sans trade, rapport « aucun trade ».
- Barres manquantes (secondes silencieuses) → fenêtres comptées en nombre de barres présentes (documenté).
- Profit factor sans perte (tout gagnant) ou sans gain (tout perdant) → valeur infinie affichée « ∞ » / 0.
- Sharpe avec variance nulle → absence de valeur.
- Run interrompu à mi-chemin (données tronquées) → métriques calculées sur ce qui existe.
- Rapport généré deux fois → même contenu (déterminisme).

## Requirements

### Functional Requirements

- **FR-001**: Chaque indicateur DOIT exister en version lot (toute la série) et pas à pas (barre après barre) produisant des valeurs identiques.
- **FR-002**: Indicateurs requis : moyenne mobile exponentielle, z-score roulant, prix moyen pondéré par les volumes, volatilité réalisée (écart-type roulant des rendements), déséquilibre acheteurs/vendeurs (déduit du volume taker des barres).
- **FR-003**: Les stratégies DOIVENT être enregistrées dans un registre nommé et instanciables depuis la configuration.
- **FR-004**: Stratégies requises : retour à la moyenne (z-score), cassure avec volume, déséquilibre de flux, référence achat-conservé ; chacune paramétrable (fenêtres, seuils, stop, durée maximale).
- **FR-005**: Les métriques DOIVENT couvrir : rendement total, Sharpe et Sortino annualisés (365 jours), drawdown maximal, Calmar, nombre de trades, taux de réussite, ratio gain/perte, profit factor, espérance nette en bps, durée moyenne de détention, totaux et drag des coûts, t-statistique de l'espérance.
- **FR-006**: Les métriques DOIVENT être calculées depuis les artefacts de run (trades, équité) sans relire les données de marché.
- **FR-007**: Le rapport HTML DOIT être autonome (styles et graphiques embarqués), avec sections : métriques, équité + drawdown, gains par trade, coûts.
- **FR-008**: La commande de backtest DOIT générer le rapport à la fin de chaque run.
- **FR-009**: La commande de comparaison DOIT aligner les métriques de plusieurs runs en tableau et produire un résumé HTML.
- **FR-010**: Toutes les métriques DOIVENT tolérer l'absence de trades et de variance (valeurs absence-de-valeur, jamais de crash).

### Key Entities

- **FeatureSeries** : série d'indicateur alignée sur les barres, avec marque de fenêtre pleine.
- **Signal** : valeur d'indicateur au moment de la décision (pour l'audit des entrées).
- **MetricsReport** : ensemble figé de métriques d'un run (perf, trades, coûts, stats).
- **ReportRenderer** : générateur du HTML autonome d'un run.
- **ComparisonReport** : tableau de métriques alignées sur plusieurs runs.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Parité lot/pas-à-pas : écart maximal < 1e-9 relatif sur un mois de barres réelles, pour chaque indicateur.
- **SC-002**: Métriques recalculées à la main sur un jeu de trades connu : identiques à 1e-9.
- **SC-003**: Rapport HTML autonome < 2 Mo, aucune ressource externe.
- **SC-004**: La comparaison aligne N runs dans un tableau sans erreur.
- **SC-005**: Run + rapport sur le mois d'août réel < 60 s.

## Assumptions

- Les fenêtres d'indicateurs sont comptées en nombre de barres présentes (les secondes silencieuses ne « comptent » pas).
- Sharpe/Sortino annualisés sur 365 jours (crypto 24/7), rendements de l'équité échantillonnés par clôture de barre.
- Pas de garde-fou pré-trade edge vs coûts dans cette feature (phase 4).
- Le rapport est un fichier statique ; aucun serveur.
- La version pas à pas des indicateurs servira au live (feature 005+) ; sa parité est le contrat testé ici.
- Performance : lot vectorisé ; pas d'optimisation sans benchmark qui la justifie.