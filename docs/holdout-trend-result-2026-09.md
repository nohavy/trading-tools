# Résultat du holdout trend 60j — septembre 2026

**Essai pré-enregistré avant accès aux données.** Paramètres et critères dans
`docs/holdout-trend-2026-09-prereg.md`; compteur au lancement : 2 (candidat +
benchmark).

## Données et exécution

- BTCUSDT et ETHUSDT UM, 1m du 2026-09-01 au 2026-09-30; 30 fichiers daily
  d'archive convertis par actif, checksums vérifiés.
- Funding : 90 settlements/actif depuis l'endpoint historique officiel Binance
  (`/fapi/v1/fundingRate`); l'archive mensuelle funding n'était pas encore
  checksum-publiée le 1er octobre.
- Warmup 2026-07-01..2026-08-31, sans position avant le début OOS.
- Engine : capital 10 000 USDT/actif, levier 1, taker 5 bps, slippage 1 bp par
  côté, latence 150±50 ms, funding historique.

## Résultat

| Actif | Trend 60j long/flat | Buy-and-hold | Fills trend |
|---|---:|---:|---:|
| BTCUSDT | **+5,875 %** | **+5,875 %** | 1 achat, aucune sortie |
| ETHUSDT | **+10,577 %** | **+10,577 %** | 1 achat, aucune sortie |
| Équipondéré | **+8,232 %** | **+8,232 %** | 2 achats au total |

Chaque stratégie a gardé la position longue pendant tout le mois. Les frais et
fills sont donc identiques à buy-and-hold pour chaque actif; aucun exit n'a été
rejeté. Le t-stat Newey-West portefeuille sur 30 rendements journaliers est
0,875 : un mois ne permet de conclure à une espérance robuste.

## Décision selon le protocole gelé

Le critère « trend équipondéré supérieur à buy-and-hold » **échoue** : les deux
portefeuilles ont exactement le même rendement net. Les conditions de rendement
positif par actif et d'absence de rejet d'exit passent, mais le candidat **ne
survit pas au test comparatif pré-enregistré**.

**NO-GO maintenu.** Le trend 60j a simplement recommandé de rester long durant
ce mois; il n'a apporté aucune valeur ajoutée face à une détention passive. Ne
pas modifier le lookback à partir de septembre et ne pas passer en paper/live.

Artefacts reproductibles : `configs/research-trend-holdout-2026-09.yaml`,
`scripts/fetch_holdout_funding.py`, `scripts/run_trend_holdout.py` et
`data/trend-holdout-2026-09.json` (données/résultats locaux ignorés par git).
