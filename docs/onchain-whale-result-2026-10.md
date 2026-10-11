# Résultat de l'écran whale-flux on-chain (012) — NO-GO

Protocole figé avant tout calcul de rendement
(`docs/on-chain-whale-2026-10-brief.md`) : hubs découverts sur la topologie
janvier 2020 (empreinte f2c7f06b, 20 adresses), seuil d'entrée = quantile
90 % des flux nets positifs de la fenêtre IS (29 351 ETH/jour), sortie =
q25 (1 543 ETH), fenêtre glissante 7 jours à couverture complète, coûts
10 bps/site, fenêtres IS 2021-01→2023-06 et OOS 2023-07→2026-08 — jamais
recalibrés.

## Résultat de l'écran vectoriel

Échantillon : 2 068 jours de flux des 20 hubs (56,7 M ETH déposées / 57,2 M
retirées), closes spot ETH 1d.

| Période | Total | t NW-20 | DD max | Exposé |
|---|---:|---:|---:|---:|
| IS (2021-01→2023-06) | −81,5 % | −0,94 | 88,6 % | 53 % |
| OOS (2023-07→2026-08) | −5,0 % | −0,11 | 21,9 % | 6 % |

## Lecture selon les critères gelés

- L'hypothèse « les entrées massives des whales sur exchange = préparation
  de vente → rendements subséquents négatifs » est **rejetée** : sur l'IS,
  courter les afflux des hubs pendant le bull run 2021 a détruit 81,5 %
  du capital (drawdown 88,6 %, très au-delà du budget 25 %), et le t
  Newey-West reste négatif (−0,94).
- L'OOS confirme la non-signalisation : −5,0 %, t −0,11, exposé 6 % du
  temps.
- **Aucune adaptation post-résultats n'est permise ni pratiquée** — pas de
  seuil inversé, pas de fenêtre déplacée, pas de réduction de hubs. La
  piste se ferme proprement.

## Ce que cette falsification enseigne

Le flux net de dépôts sur les hubs, détecté topologiquement, est une
accumulation de pouvoir d'achat plutôt qu'un signal de vente : les afflux
coïncident avec les phases haussières au lieu de les précéder. La
sémantique d'alerte du livre (entrées sur exchange = vente) ne transpose
pas à ce niveau topologique un sujet de twenty hubs dérivés par flux de
gang de clients dispersés.

## L'héritage durable de la feature 012

La pipeline d'ingestion BigQuery (gate de faisabilité gratuit, SQL
déterministe, parquet listés + manifest listés sha256) est réutilisable tel
quel pour toute future hypothèse on-chain. Le coûts de scan gratuits et la
couverture 2019+ font que le prochain écran peut être testé en quelques
heures plutôt qu'en quelques semaines.

Artefacts : `data/onchain/eth_hubs_2020-01.json` et
`data/onchain/eth_flows_2021-01-01_2026-08-31.parquet` + manifest sha256
814953fa (locaux, ignorés par git), `data/onchain_screen_results.json`, et
le code versionné : `research/onchain_screen.py`, `data/onchain/ingest.py`,
`data/onchain/sqls.py`.
