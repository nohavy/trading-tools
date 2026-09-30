# Feature Specification: Moteur de backtest événementiel

**Feature Branch**: `002-backtest-engine`

**Created**: 2026-09-30

**Status**: Draft

**Input**: User description: "Moteur de backtest événementiel : exchange simulé réaliste (marché, limite, post-only, stop), coûts complets (frais, slippage, latence, funding), comptes spot et perpétuels, API de stratégie unique pour backtest, paper et live"

## User Scenarios & Testing

### User Story 1 - Un backtest reproductible au résultat exact (Priority: P1)

En tant qu'utilisateur, je lance une stratégie triviale (acheter à un instant, revendre 60 secondes plus tard) sur des données historiques locales, et j'obtiens un PnL net **exactement** égal à celui que je calcule à la main (frais et slippage connus). Deux exécutions du même run donnent des résultats identiques.

**Why this priority**: sans résultat exact et reproductible, aucune validation d'algorithme n'a de valeur ; c'est le socle de confiance de tout le projet.

**Independent Test**: run sur un petit jeu de données avec coût paramétré → comparaison au calcul manuel ; relancer le run → identité des résultats.

**Acceptance Scenarios**:

1. **Given** un jeu de barres et une tape de transactions connus, **When** la stratégie triviale tourne avec des frais et un slippage paramétrés, **Then** le PnL net rapporté est égal au calcul manuel à la précision du centime de bps.
2. **Given** le même run relancé à l'identique, **When** je compare les artefacts, **Then** ils sont identiques (mêmes trades, même equity, mêmes métriques).
3. **Given** une stratégie aléatoire (entrées au hasard, même cadence et durée de détention), **When** elle tourne, **Then** elle perd en moyenne les coûts d'aller-retour × nombre de trades (test de nullité du moteur).

---

### User Story 2 - Des ordres qui se comportent comme sur Binance (Priority: P2)

En tant qu'utilisateur, les ordres que je passe en backtest se comportent comme ils le feraient chez Binance : remplis du bon côté de la carnet avec une latence réelle, rejetés s'ils violent les filtres, déclenchés au premier prix franchissant leur seuil.

**Why this priority**: un ordre simulé trop gentil fabrique des stratégies mentiront au paper puis au live.

**Independent Test**: scénarios unitaires sur des tapes synthétiques connues, un par comportement attendu.

**Acceptance Scenarios**:

1. **Given** un ordre au marché envoyé à t, **When** la latence s'écoule, **Then** il est rempli aux transactions qui suivent son arrivée, du bon côté du carnet ; s'il dépasse la taille d'une transaction, au prix moyen des suivantes.
2. **Given** un ordre limite, **When** le prix traverse ou touche son niveau (selon le mode choisi), **Then** il est rempli en tant que maker ; post-only est rejeté s'il serait rempli immédiatement.
3. **Given** un ordre stop, **When** une transaction franchit le seuil, **Then** il se déclenche et s'exécute au marché avec slippage.
4. **Given** un ordre violent les filtres (pas de prix, pas de quantité, notionnel minimum), **When** il est soumis, **Then** il est rejeté avec la raison exacte, comme l'API.

---

### User Story 3 - Comptes spot et perpétuels cohérents (Priority: P3)

En tant qu'utilisateur, je backteste sur un compte spot (cash + inventaire) ou sur un compte perpétuel (position signée, levier, funding, liquidation approximée), avec un registre comptable où chaque flux est catégorisé et réconciliable.

**Why this priority**: les perpétuels sont la voie réaliste du microtrading (frais réduits, vente à découvert) ; sans comptabilité réconciliable, impossible de faire confiance aux chiffres.

**Independent Test**: invariants vérifiés automatiquement sur des runs : équation du PnL net et équation de l'équité.

**Acceptance Scenarios**:

1. **Given** un run avec frais, slippage et funding, **When** je vérifie chaque trade, **Then** net = brut − frais − slippage ± funding, à chaque trade et cumulé.
2. **Given** un compte spot, **When** une position est ouverte et fermée, **Then** le cash et l'inventaire évoluent exactement selon les exécutions et les frais déduits.
3. **Given** un compte perpétuel avec levier, **When** une perte creuse la marge sous le seuil de maintenance, **Then** la position est liquidée comme le ferait l'exchange.

---

### User Story 4 - Une API de stratégie unique et à l'épreuve du futur (Priority: P4)

En tant qu'utilisateur, j'écris ma stratégie une fois contre une API claire (événements d'entrée, passage d'ordres, état du portefeuille), et le même code tournera en backtest, puis en paper et en live ; le moteur m'empêche structurellement de lire le futur.

**Why this priority**: cette API est le contrat du projet ; la figer tôt évite de réécrire les stratégies plus tard.

**Independent Test**: une stratégie de démonstration utilise toute l'API (ordres, annulations, timers, lookback) sur un run backtest.

**Acceptance Scenarios**:

1. **Given** une stratégie inscrite aux événements, **When** le run tourne, **Then** elle reçoit les barres à leur clôture seulement, et son historique borné ne contient que des barres clôturées.
2. **Given** les données tronquées après un instant t, **When** la stratégie tourne sur les données tronquées, **Then** toutes ses décisions antérieures à t sont identiques (garantie anti-lecture-du-futur).
3. **Given** un ordre annulé avant son remplissage programmé, **When** l'instant du remplissage arrive, **Then** rien ne se produit ; un remplissage déjà arrivé est signalé par on_fill.

---

### User Story 5 - Coûts paramétrables et auditables (Priority: P5)

En tant qu'utilisateur, je paramètre la grille de frais, le slippage et la latence par configuration, et je vois dans le registre combien chaque facteur a coûté, trade par trade.

**Why this priority**: le net après frais est la seule vérité ; l'auditabilité des coûts permet de comprendre pourquoi une stratégie perd.

**Independent Test**: un run avec deux grilles de frais différentes → la différence de PnL net correspond exactement à la différence de frais appliquée aux volumes échangés.

**Acceptance Scenarios**:

1. **Given** deux runs identiques ne différant que par la grille de frais, **When** je compare, **Then** l'écart de PnL net égale l'écart de frais totaux.
2. **Given** un run, **When** je consulte le registre, **Then** chaque flux (brut, frais, slippage, funding) est catégorisé et sommable.

---

### User Story 6 - Lancer un backtest par configuration et récupérer des artefacts (Priority: P6)

En tant qu'utilisateur, je lance un backtest depuis un fichier YAML, et j'obtiens un dossier de run réutilisable : configuration résolue, liste des trades, courbe d'équité, résumé, et manifeste de provenance (graines, données utilisées, version du code).

**Why this priority**: la reproductibilité d'un run exige la traçabilité de ses entrées ; les métriques avancées viendront dans la feature suivante.

**Independent Test**: `tv2 backtest run --config backtest.yaml` → dossier de run complet avec manifeste.

**Acceptance Scenarios**:

1. **Given** un YAML de backtest valide, **When** je lance le run, **Then** un dossier contient configuration résolue, trades, équité, résumé et manifeste.
2. **Given** un YAML invalide ou des données manquantes au catalogue, **When** je lance, **Then** une erreur claire indique le problème avant tout calcul.

### Edge Cases

- Stop et objectif touchés dans la même barre (mode bougies seules) → résolution au cas le plus défavorable.
- Annulation arrivant après le remplissage programmé → le remplissage arrive quand même (comme en réel).
- Trou de données pendant qu'un ordre limite repose → aucun remplissage pendant le trou.
- Funding pendant une position ouverte (perp) → débit/crédit catégorisé.
- Latence qui fait arriver un ordre pendant une seconde sans transactions → rempli à la première suivante.
- Barre de clôture en cours de run (fin de données) → positions ouvertes valorisées et run arrêté proprement.

## Requirements

### Functional Requirements

- **FR-001**: Le moteur DOIT traiter les événements dans l'ordre strict : exchange (remplissements/rejets programmés) → notifications de remplissage → données de marché → minuteries → stratégie, à timestamp égal.
- **FR-002**: Les barres DOIVENT être transmises à la stratégie uniquement à leur clôture ; l'historique borné ne doit exposer que des barres clôturées.
- **FR-003**: Un ordre soumis à l'instant t DOIT devenir exécutable seulement après la latence simulée (moyenne et aléa paramétrés, graine fixée).
- **FR-004**: Le simulateur DOIT déterminer par recherche vectorisée sur la tape de transactions les instants de remplissage possibles de chaque ordre actif, et annuler un remplissage planifié si l'ordre est annulé avant.
- **FR-005**: Le simulateur DOIT supporter les ordres : marché, limite (durée de vie indéfinie), post-only, stop-marché, annulation.
- **FR-006**: Un ordre au marché DOIT être rempli aux transactions qui suivent son arrivée, du bon côté (acheteur preneur pour un achat) ; au-delà de la taille d'une transaction, au prix moyen pondéré des suivantes.
- **FR-007**: Un ordre limite DOIT offrir deux modes de remplissage paramétrables : pessimiste (rempli seulement si le prix traverse le niveau) et optimiste (rempli au contact), avec frais maker dans les deux cas.
- **FR-008**: Un ordre stop DOIT se déclencher à la première transaction franchissant son seuil et s'exécuter ensuite comme un ordre au marché avec slippage.
- **FR-009**: Le simulateur DOIT rejeter tout ordre violent les filtres de l'exchange (pas de prix, pas de quantité, notionnel minimum) avec la raison exacte.
- **FR-010**: Le moteur DOIT proposer un compte spot (cash + inventaire, frais déduits) et un compte perpétuel (position signée, levier, liquidation approximée au seuil de maintenance, funding historique appliqué aux échéances).
- **FR-011**: Le registre DOIT catégoriser chaque flux (brut, frais, slippage, funding) et vérifier l'invariant net = brut − frais − slippage ± funding à chaque trade et cumulé.
- **FR-012**: La grille de frais, le slippage et la latence DOIVENT être paramétrables par configuration YAML avec graine d'aléa fixée.
- **FR-013**: L'API de stratégie (événements d'entrée, passage d'ordres, annulations, minuteries, historique borné, accès portefeuille et coûts) DOIT être identique pour backtest, paper et live.
- **FR-014**: Un run DOIT produire : configuration résolue, liste des trades, équité pas à pas, résumé, et manifeste de provenance (graines, checksums des données, version du code).
- **FR-015**: Le moteur DOIT valoriser les positions ouvertes à la clôture et terminer proprement à la fin des données.

### Key Entities

- **Order** : direction, type (marché/limite/stop), quantité, prix limite ou seuil, horodatages de soumission et d'arrivée, statut (en attente, active, remplie, annulée, rejetée).
- **Fill** : ordre, instant, prix, quantité, frais, côté maker/preneur.
- **Position** : quantité signée (spot : inventaire ≥ 0 ; perp : signée), prix d'entrée moyen.
- **Account** : spot (cash + inventaire) ou perpétuel (marge, position, équité, seuil de liquidation).
- **Bar / TradeTick / FundingEvent** : données de marché canoniques (feature 001).
- **CostModel** : frais par type, slippage, latence ; expose le coût d'aller-retour d'une combinaison d'ordres.
- **Ledger** : flux catégorisés, réconciliés.
- **RunManifest** : provenance complète d'un run.
- **Strategy / Context** : callbacks et services exposés à l'utilisateur.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Le PnL net de la stratégie triviale est égal au calcul manuel à 1e-9 relatif près.
- **SC-002**: Deux exécutions du même run produisent des artefacts identiques.
- **SC-003**: Un run d'un mois de barres 1s avec tape de transactions s'exécute en moins de 10 minutes.
- **SC-004**: Tronquer les données après t ne change aucune décision antérieure à t (vérification automatique dans la suite de tests).
- **SC-005**: Une stratégie d'entrées aléatoires perd en moyenne les coûts × nombre de trades (test de nullité).

## Assumptions

- v1 : remplissements complets (pas de partiel), taille des ordres très inférieure à la liquidité, nos ordres ne déplacent pas le marché.
- Pas de carnet L1/L2 historique : le spread est estimé et les remplissages de limites sont bornés (pessimiste/optimiste).
- Le funding historique est disponible par échéance (93 lignes/mois, feature 001).
- Les données (barres 1s + tape aggTrades) sont déjà dans le catalogue local (feature 001).
- Paper et live utilisent la même API mais sont hors scope de cette feature.
- Performance : remplissages prédictifs vectorisés ; aucune optimisation additionnelle sans benchmark qui la justifie.