# Feature Specification: Scanner d'actifs à fort potentiel

**Feature Branch**: `006-asset-scanner`

**Created**: 2026-09-30

**Status**: Draft

**Input**: User description: "je veux trouver une solution pour sélectionner les actifs à fort potentiel de rentabilité. Que peux tu proposer ?"

## User Scenarios & Testing

### User Story 1 - Constituer l'univers scannable (Priority: P1)

En tant qu'utilisateur, je récupère en une commande la liste des perpétuels USDⓈ-M actuellement négociables sur Binance et des données récentes légères (bougies minute du mois dernier, funding) pour chacun — un instantané complet de l'univers, prêt à analyser.

**Why this priority**: sans données pour chaque actif, aucun scan n'est possible ; c'est le prérequis de tout le reste.

**Independent Test**: la commande produit la liste des symboles actifs et un jeu de données par symbole avec contrôle qualité.

**Acceptance Scenarios**:

1. **Given** la connexion aux règles d'exchange, **When** je demande l'univers, **Then** la liste des perpétuels négociables est obtenue avec leurs filtres (pas de prix, pas de quantité, notionnel minimum).
2. **Given** l'univers, **When** je lance le téléchargement de l'instantané, **Then** un mois de bougies minute et l'historique du funding récent sont obtenus pour chaque symbole, avec reprise et vérification d'intégrité comme pour tout téléchargement du projet.
3. **Given** des symboles inexistants, délistés ou sans données sur la période, **When** le téléchargement tourne, **Then** ils sont écartés proprement avec un avertissement (pas d'échec du scan global).

---

### User Story 2 - Mesurer le potentiel de chaque actif (Priority: P2)

En tant qu'utilisateur, pour chaque actif de l'univers, je vois les mesures objectives qui caractérisent son potentiel de microtrading : volatilité relative, liquidité (volumes, notionnel), coûts estimés, fréquence et force des cassures, extrêmes de funding, régimes de volatilité.

**Why this priority**: la leçon des analyses précédentes est que l'edge est borné par la microstructure — il faut donc mesurer, actif par actif, les dimensions qui font varier ce bornage.

**Independent Test**: sur des données synthétiques connues, chaque métrique reproduit la valeur attendue.

**Acceptance Scenarios**:

1. **Given** l'instantané d'un actif, **When** les mesures sont calculées, **Then** volatilité relative, liquidité, tendance, fréquence de cassures, extrêmes de funding sont produites avec leurs définitions précises.
2. **Given** un actif très peu liquide (volume quasi nul), **When** les mesures tournent, **Then** l'actif est marqué non-scanable plutôt que de produire des chiffres trompeurs.

---

### User Story 3 - Un passage d'edge rapide par actif (Priority: P3)

En tant qu'utilisateur, chaque actif passe par un test d'edge rapide des signaux connus (cassure, retour à la moyenne, flux) : rendements forward à quelques horizons, comparés aux coûts aller-retour du maker — le même filtre pré-backtest qui a tué les idées précédentes en secondes, appliqué à tous les actifs.

**Why this priority**: c'est le cœur de la valeur : trouver où l'edge brut dépasse (ou approche) les coûts, là où BTC/ETH l'ont tué.

**Independent Test**: sur des données synthétiques à rendement forward connu, l'edge par actif reproduit les valeurs attendues.

**Acceptance Scenarios**:

1. **Given** l'instantané de chaque actif, **When** le passage d'edge tourne, **Then** par actif et signal : rendement moyen par horizon, hit rate, et edge net estimé par paire d'ordres maker.
2. **Given** tous les actifs scannés, **When** les résultats sont agrégés, **Then** un classement par edge net estimé désigne les candidats dont l'edge dépasse (ou approche) les coûts.

---

### User Story 4 - Un classement et un rapport de scan (Priority: P4)

En tant qu'utilisateur, je reçois un rapport autonome classant les actifs par potentiel (métriques + edge net estimé), avec la liste des candidats recommandés pour une validation complète par la chaîne existante (backtest, walk-forward, stress, verdict).

**Why this priority**: le scan n'a de valeur que si sa sortie est actionnable — une liste d'actifs à passer dans le pipeline de validation.

**Independent Test**: le scan produit un rapport autonome avec le classement et la liste des candidats.

**Acceptance Scenarios**:

1. **Given** le scan terminé, **When** le rapport est généré, **Then** un fichier autonome (graphiques et tableaux embarqués, aucune ressource externe) classe les actifs par potentiel net estimé.
2. **Given** le classement, **When** les candidats sont désignés, **Then** la liste des actifs au-dessus du seuil est exportée (réutilisable par les commandes de validation du projet).

### Edge Cases

- Symbole délisté en cours de scan → écarté avec avertissement.
- Actif listé récemment (moins d'un mois d'historique) → inclus si assez de données, sinon marqué.
- Données d'un actif avec de longues plages sans transactions (actif mort) → marqué non-scanable.
- Cas de prix extrêmes (nouvelles listings en boom/crash) → métriques calculées telles quelles, marquées.
- Funding inexistant pour un actif récent → mesures de funding à absence-de-valeur, le reste du scan continue.

## Requirements

### Functional Requirements

- **FR-001**: La commande d'univers DOIT obtenir la liste des perpétuels USDⓈ-M négociables avec leurs filtres d'exchange.
- **FR-002**: La commande d'instantané DOIT télécharger et convertir, pour chaque symbole de l'univers, un mois de bougies minute et l'historique récent du funding, avec reprise et vérification d'intégrité.
- **FR-003**: Les symboles sans données (délistés, nouvelles listings insuffisantes) DOIVENT être écartés avec avertissement, sans interrompre le scan.
- **FR-004**: Les mesures par actif DOIVENT inclure : volatilité relative (écart-type des rendements), liquidité (volume notionnel moyen, nombre de transactions), fréquence et force des cassures de plage, extrêmes de funding, part des régimes de volatilité.
- **FR-005**: Chaque actif DOIT passer le test d'edge rapide des signaux connus (cassure, retour à la moyenne, flux) avec rendements forward et edge net estimé par paire d'ordres maker.
- **FR-006**: Le classement DOIT trier les actifs par edge net estimé, avec marque « trop peu de trades » et « non-scanable ».
- **FR-007**: Le rapport DOIT être autonome (aucune ressource externe) avec les métriques, le classement, et la liste exportée des candidats au-dessus d'un seuil paramétrable.
- **FR-008**: Le scan global DOIT continuer malgré les erreurs individuelles (symbole manquant, données vides) et résumer les écarts.

### Key Entities

- **Univers** : liste des perpétuels négociables et de leurs filtres.
- **Instantané d'actif** : bougies minute récentes + funding récent d'un symbole.
- **Métriques d'actif** : volatilité, liquidité, cassures, funding, régimes.
- **Edge d'actif** : rendements forward des signaux connus et edge net estimé par paire d'ordres.
- **ScanReport** : classement global + candidats exportés.

## Success Criteria

### Measurable Outcomes

- **SC-001**: L'instantané de 200+ actifs (un mois de bougies minute chacun) s'obtient en une commande en moins de 60 minutes.
- **SC-002**: Le scan complet (mesures + edge par actif) s'exécute en moins de 10 minutes sur l'instantané.
- **SC-003**: Sur des données synthétiques à valeurs connues, chaque métrique et chaque edge reproduit la valeur attendue.
- **SC-004**: Le rapport autonome pèse moins de 5 Mo et désigne la liste des candidats.
- **SC-005**: Le scan survit aux symboles défaillants (écartés avec avertissement) sans jamais s'interrompre.

## Assumptions

- La fenêtre d'instantané est le mois calendaire précédent (fichiers mensuels du dépôt public, un seul fichier par actif).
- L'universe est la totalité des perpétuels USDⓈ-M négociables ; un filtre par volume minimal est appliqué au classement (paramétrable).
- Les coûts de référence sont maker×maker USDⓈ-M (4 bps aller-retour), grille paramétrable.
- Le scan identifie les CANDIDATS ; la validation complète (backtest, walk-forward, stress, verdict) reste la chaîne des features précédentes.
- Les actifs très illiquides sont exclus du classement (volume notionnel minimal paramétrable).