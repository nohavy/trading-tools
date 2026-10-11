# Matrice de risques non-financiers — runbook paper → live

**Pré-enregistrement opérationnel**, inspiré du ch7.5 d'*Investing for
Programmers*. Le kill switch technique (fichier `paper-stop`, feature 011)
couvre le risque logiciel ; cette matrice couvre le reste.

**Règle de lecture** : une ligne passe au live seulement si (a) son trigger
est observable automatiquement dans les logs/dashboards paper, (b) sa
mitigation a été testée une fois en paper. Une ligne sans trigger chiffré
reste une intention, pas un mécanisme.

| # | Risque (NFR) | Probabilité | Impact | Triggers chiffrés | Mitigation |
|---|---|---|---|---|---|
| 1 | **Régulation exchange** — restriction UM/spot sur un actif ou un marché géo, durcissement KYC | moyen | critique | communication officielle Binance mentionnant un actif de la session ; statut du compte ≠ full trading | kill switch immédiat ; fermeture des jambes dans l'ordre encore négociable (perp d'abord puis spot) ; journal des fills pour l'audit |
| 2 | **Dépegage USDT/USDC** | moyen | critique | USDT/USDC spot < 0,997 pendant plus de 2 h ; prime perp < −1 % en continu | kill switch immédiat avant toute nouvelle exposition ; conversion du cash restant en USDC documentée dans le runbook |
| 3 | **Compromission du compte/API** | moyen | critique | session d'API inconnue ; ordres absents du journal ; IP hors whitelist | live only : clé API dédiée dont le retrait de fonds est désactivé, whitelist d'IP, rotation trimestrielle ; paper : sans objet (aucune clé) |
| 4 | **Contagion de liquidations** — crash type LUNA (> 30 %/24 h) | moyen | élevé | funding < −0,5 %/8 h ; basis spot/perp < −2 % ; volume 24 h ≈ ×3 norme | aucun achat de la baisse (gel) ; DD budget du carry 2,24 % constaté sur 2020-22, tolérance live 5 % = stop discrétionnaire manuel, jamais automatique intraday |
| 5 | **Régime de funding négatif persistant** | moyen | élevé | somme funding 7 j < 0 pendant plus de 14 jours consécutifs | le protocole est gelé — pas de recalibrage ; la jambe short paie le funding mais le carry 2020-22 a montré que la convergence de basis compense ; décision selon les critères fixés, pas selon l'humeur |
| 6 | **Basis extrême** (decouplage catastrophe spot/perp) | moyen | élevé | basis intraday < −50 bps | la règle de sortie du protocole s'applique à la clôture daily uniquement (basis ≤ −20 bps) — jamais intraday, pour éviter le whipsaw |
| 7 | **Défaillance du feed** (REST down, barres manquantes) | moyen | moyen | 3 polls échoués consécutifs ; trou au checkpoint daily | session 011 : retry exponentiel puis backfill au retour ; dépassé 15 min : pose du stop file manuel, rattrapage documenté à la reprise |
| 8 | **Erreur opérationnelle humaine** | moyen | élevé | intéressés: quantité exécutée ≠ quantité de couverture > 0,5 % ; tout ordre au-delà du contrat une-entrée | journal complet des fills (trades.csv paper) relu quotidiennement ; tout dépassement = kill switch + rapport HTML d'audit |
| 9 | **Durée d'observation insuffisante** | — | élevé | session paper < 30 jours ou < 90 settlements | constitution : minimum 30 jours de paper complet avant que l'option live s'ouvre |
| 10 | **Dérive protocole** (exécution ≠ config figée) | faible | moyen | empreinte sha256 de la session ≠ empreinte du holdout franchi | gate du runtime 011 : refus au démarrage si l'empreinte diffère |

Historique de mise à jour : matrice figée le 2026-10-11, avant l'ouverture
paper (T010). Toute modification après le premier jour de live exige un
nouveau pré-enregistrement.
