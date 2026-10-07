# Feature Specification: Mode paper — exécution temps réel simulée

**Created**: 2026-10-07

**Status**: Draft for review

## User Story

Exécuter une stratégie validée en **temps réel** sur les données de marché
publiques Binance, avec des fills simulés par les mêmes modèles de coûts que
le backtest, de la persistance d'état, un kill switch et un monitoring — sans
clés API, sans argent réel, sans ordre envoyé à un exchange. C'est la barrière
obligatoire entre le holdout franchi et le live (constitution).

## Acceptance Scenarios

1. **Même code** : une stratégie du registre tourne en paper sans modification
   — elle voit des `PriceBar` via le `Context` et `SimulatedExchange`, avec
   l'ordre d'événements constitutionnel (exchange → on_fill → clôture de
   barre → timers → on_bar).
2. **Fills simulés fidèles** : latence déterministe (150±50 ms, seed 42),
   slippage 1 bp, fees taker/maker figés, funding réel appliqué aux
   settlements via l'endpoint officiel — les mêmes paramètres gelés que le
   run validé.
3. **Persistance** : position, ordres, marques d'equity et état de stratégie
   écrits **atomiquement** à chaque barre ; après redémarrage, la session
   reprend sans double soumission (le candidat une-entrée ne ré-entre pas) et
   sans perte d'historique ; les funding et barres manqués pendant l'arrêt
   sont rejoués au retour.
4. **Kill switch** : un fichier de contrôle (`data/paper-stop`) ou Ctrl-C
   stoppe proprement : plus aucun ordre, snapshot cohérent, positions
   restantes valorisées comme en fin de backtest.
5. **Monitoring** : marques daily d'equity persistées, rapport HTML rendu à
   la demande, logs anglais explicites, alerte locale sur tout rejet d'ordre
   ou événement inattendu.
6. **Porte de constitution** : `tv2 paper run` refuse de démarrer si
   l'empreinte sha256 de la section (data+account+costs+strategy) de sa
   config ne correspond pas à celle d'un holdout pré-enregistré **franchi**
   pour ces paramètres exacts — sauf si la config déclare explicitement
   `experimental: true` (marqué dans les logs et le rapport).
7. **Zéro secret, zéro réel** : uniquement les endpoints publics (klines,
   fundingRate) ; aucune clé API ; aucun ordre sortant vers Binance.

## Out of scope

- Live, clés API, fills réels, réconciliation d'ordres exchange.
- WebSocket (le polling REST au pas 1m suffit au pas de décision du moteur).
- Multi-stratégies, rééquilibrage, volatility targeting, notifications
  externes (email/télégram).
- Toute stratégie dont le protocole pré-enregistré n'a pas franchi son
  holdout.
