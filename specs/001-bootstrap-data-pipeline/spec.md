# Feature Specification: Socle et pipeline de données historiques Binance

**Feature Branch**: `001-bootstrap-data-pipeline`

**Created**: 2026-09-30

**Status**: Draft

**Input**: User description: "Socle projet et pipeline de données historiques Binance (CLI tv2, téléchargement vérifié, Parquet nanosecondes, contrôles qualité)"

## User Scenarios & Testing

### User Story 1 - Obtenir un mois de données historiques vérifiées (Priority: P1)

En tant qu'utilisateur, je lance une commande unique qui télécharge les données historiques Binance d'un symbole (bougies ou transactions agrégées, spot ou futures) sur une période, vérifie l'intégrité de chaque fichier et les convertit en un format local prêt pour le backtest.

**Why this priority**: sans données fiables, rien d'autre n'est possible ; c'est le MVP de tout le projet.

**Independent Test**: `tv2 data download --market spot --symbol BTCUSDT --type klines --interval 1s --start 2026-08-01 --end 2026-08-31` → fichiers locaux convertis + catalogue à jour.

**Acceptance Scenarios**:

1. **Given** un symbole et une période valides, **When** je lance le téléchargement, **Then** tous les fichiers sources sont obtenus, vérifiés par checksum, convertis et référencés dans le catalogue avec leurs bornes temporelles et leur nombre de lignes.
2. **Given** un téléchargement interrompu, **When** je relance la même commande, **Then** seuls les fichiers manquants ou invalides sont retéléchargés.
3. **Given** un fichier dont le checksum ne correspond pas, **When** il est téléchargé, **Then** il est rejeté et retenté, avec une erreur explicite si le problème persiste.

---

### User Story 2 - Des données normalisées quel que soit le format source (Priority: P2)

En tant qu'utilisateur, je manipule des données dont les horodatages et les colonnes sont toujours identiques (nanosecondes UTC, schéma canonique bougies/transactions), même si les sources varient (spot vs futures, millisecondes vs microsecondes, en-têtes présents ou non).

**Why this priority**: la normalisation conditionne tout le downstream (moteur, features, métriques).

**Independent Test**: convertir un petit échantillon réel de chaque source → valeurs attendues exactes, timestamps en nanosecondes.

**Acceptance Scenarios**:

1. **Given** un fichier de bougies spot horodaté en microsecondes (après 2025-01-01), **When** il est converti, **Then** les timestamps internes sont en nanosecondes UTC sans perte de précision.
2. **Given** un fichier contenant une ligne d'en-tête, **When** il est converti, **Then** l'en-tête est ignoré et les données sont correctement chargées.
3. **Given** un fichier contenant une ligne malformée, **When** il est converti, **Then** une erreur indique le fichier et le numéro de ligne, sans convertir un fichier ambigu en silence.

---

### User Story 3 - Contrôler la qualité des données téléchargées (Priority: P3)

En tant qu'utilisateur, je vérifie d'un coup qu'un jeu de données est exploitable : pas de bougies manquantes, pas de doublons, timestamps croissants, prix cohérents.

**Why this priority**: un backtest sur données trouées ou aberrantes produirait des résultats trompeurs.

**Independent Test**: `tv2 data check --market spot --symbol BTCUSDT --interval 1s --start 2026-08-01 --end 2026-08-31` → rapport d'anomalies ou statut propre.

**Acceptance Scenarios**:

1. **Given** un jeu de données sain, **When** je lance le contrôle, **Then** le statut est « propre » et le code retour est nul.
2. **Given** un jeu contenant des anomalies injectées (trou, doublon, high < low, prix aberrant, timestamp recul), **When** je lance le contrôle, **Then** chaque type d'anomalie est listé précisément et le code retour est non nul.

---

### User Story 4 - Règles des instruments et historique du funding (Priority: P4)

En tant qu'utilisateur, je récupère les règles de trading par symbole (pas de prix, pas de quantité, notionnel minimum) pour le spot et les futures, ainsi que l'historique du funding des perpétuels.

**Why this priority**: nécessaire à la feature 002 (moteur), mais pas au MVP données.

**Independent Test**: `tv2 data instruments --market um --symbol BTCUSDT` → règles affichées et stockées.

**Acceptance Scenarios**:

1. **Given** un symbole existant, **When** je demande ses règles, **Then** tick_size, step_size et min_notional sont extraits et stockés localement.
2. **Given** un perpétuel, **When** je demande son funding, **Then** l'historique des taux est téléchargé et stocké avec ses échéances.

---

### User Story 5 - Regrouper les données à la résolution voulue (Priority: P5)

En tant qu'utilisateur, je regroupe les bougies d'une seconde en 5s/15s/1m avec des OHLCV corrects, pour itérer vite sur des résolutions plus grosses.

**Why this priority**: confort de recherche ; les données 1s restent la référence.

**Independent Test**: regrouper un jour de bougies 1s connues → bougies 1m attendues exactes.

**Acceptance Scenarios**:

1. **Given** des bougies 1s couvrant une plage complète, **When** je les regroupe en 1m, **Then** open/high/low/close/volumes (dont taker) sont exacts et la dernière barre partielle est rejetée.

---

### User Story 6 - Un socle configurable et vérifiable (Priority: P6)

En tant qu'utilisateur, je pilote l'outil par une CLI multi-commandes et des fichiers YAML validés avec des messages d'erreur clairs.

**Why this priority**: enabler de toutes les autres stories ; valeur directe moindre.

**Independent Test**: `tv2 --help` liste les commandes ; un YAML invalide → erreur localisant le champ fautif.

**Acceptance Scenarios**:

1. **Given** la CLI installée, **When** je lance `tv2 --help`, **Then** toutes les commandes sont listées avec un code retour nul.
2. **Given** un fichier de configuration invalide, **When** il est chargé, **Then** l'erreur indique précisément le champ et la raison.

### Edge Cases

- Mois en cours (fichier mensuel pas encore publié) → bascule automatique vers les fichiers journaliers.
- Jour manquant (symbole inactif ce jour-là) → avertissement explicite, pas d'échec silencieux.
- Bascule des unités d'horodatage du spot au 2025-01-01 (ms → µs) dans une même période.
- Fichier checksum manquant ou en casse différente.
- Interruption réseau au milieu d'un téléchargement (reprise via fichier temporaire).
- Symbole inexistant sur la période demandée → erreur claire, sans fichier zombie.

## Requirements

### Functional Requirements

- **FR-001**: La commande de téléchargement DOIT accepter le marché (spot|um), le type (klines|aggTrades|fundingRate), le symbole, l'intervalle et les bornes de période ; elle DOIT utiliser les fichiers mensuels pour les mois complets écoulés et journaliers sinon.
- **FR-002**: Chaque fichier téléchargé DOIT être vérifié par son checksum SHA256 ; en cas d'échec, le fichier est rejeté et retenté.
- **FR-003**: Le téléchargement DOIT être repirable (fichier temporaire renommé atomiquement à la fin) et idempotent (un fichier déjà valide n'est pas retéléchargé).
- **FR-004**: Les erreurs réseau transitoires (429, 5xx) DOIVENT être retentées avec backoff exponentiel ; la concurrence des téléchargements DOIT être limitée.
- **FR-005**: Les horodatages DOIVENT être normalisés en nanosecondes UTC, l'unité d'origine (ms/µs) étant détectée par magnitude.
- **FR-006**: Les données DOIVENT être stockées au schéma canonique (bougies : OHLCV + volumes taker ; transactions : prix, quantité, côté) dans un format colonne compacté, un fichier source = un fichier converti.
- **FR-007**: Un catalogue local DOIT référencer chaque fichier (checksum, bornes temporelles, nombre de lignes) et rester cohérent après relance.
- **FR-008**: `data check` DOIT signaler : bougies manquantes, doublons d'identifiants, horodatages non croissants, high < low, prix aberrants ; avec liste précise et code retour non nul si anomalies.
- **FR-009**: Le système DOIT obtenir les règles d'exchange par symbole (pas de prix, pas de quantité, notionnel minimum) pour le spot et les futures.
- **FR-010**: Le système DOIT obtenir l'historique du funding des perpétuels.
- **FR-011**: Le regroupement DOIT agréger les bougies 1s en 5s/15s/1m (OHLCV + volumes taker) et rejeter la dernière barre partielle.
- **FR-012**: Toute erreur de parsing DOIT indiquer le fichier et le numéro de ligne concernés.
- **FR-013**: Une ligne d'en-tête éventuelle DOIT être détectée et ignorée automatiquement.
- **FR-014**: Les configurations YAML DOIVENT être validées avec des erreurs localisant le champ fautif.

### Key Entities

- **Bar** : bougie (ouvert, haut, bas, clôture, volume, volume quote, nb trades, volumes taker) ancrée à son horodatage d'ouverture en nanosecondes.
- **TradeTick** : transaction agrégée (prix, quantité, identifiant, côté acheteur maker).
- **Funding** : taux de funding associé à une échéance.
- **InstrumentRules** : pas de prix, pas de quantité, notionnel minimum d'un symbole.
- **DownloadPlan** : liste des fichiers à obtenir pour une demande (choix mensuel/journalier).
- **Catalogue** : inventaire local des fichiers vérifiés avec leurs métadonnées.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Un mois de bougies 1s spot BTCUSDT s'obtient en une commande unique, sans intervention manuelle, en moins de 10 minutes sur une connexion standard.
- **SC-002**: 100 % des fichiers stockés sont vérifiés par checksum ; aucune corruption silencieuse possible.
- **SC-003**: Le contrôle qualité parcourt un mois de bougies 1s en moins d'une minute et détecte toutes les anomalies injectées dans un jeu de test.
- **SC-004**: Relancer un téléchargement terminé ne retélécharge aucun fichier.
- **SC-005**: Une interruption en cours de téléchargement est récupérable sans perte ni doublon.

## Assumptions

- Accès réseau à data.binance.vision et aux endpoints publics d'exchangeInfo ; aucune clé API nécessaire.
- Environ 15 Go d'espace disque disponibles pour les jeux de données initiaux.
- Symboles initiaux : BTCUSDT, ETHUSDT.
- Les tests automatisés n'exigent pas de réseau (jeux synthétiques) ; les tests réseau sont marqués et optionnels.
- Le scope se limite aux données historiques publiques ; l'enregistrement temps réel du carnet est hors scope de cette feature.