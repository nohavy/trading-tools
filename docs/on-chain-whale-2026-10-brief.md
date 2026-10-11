# Brief de recherche — signal on-chain de distribution des whales

Rédigé le 2026-10-11 **avant tout calcul de rendement et sans lecture de
données on-chain** — transposition du ch11 (scorecards) d'*Investing for
Programmers*. Ce document fige l'hypothèse d'un éventuel feature 012 ; il
ne vaut autorisation d'aucune sorte.

## Verdict empirique de l'heuristique (2020-01, BigQuery réel)

La sonde topologique janvier 2020 (in-degree × out-degree sur les
transferts natifs ETH, 2 356 283 adresses actives) classe **#1 le
cluster Binance actif** `0x3f5ce5fbfe3e9af3971dd873d819547554bea7e3`
(in=35 414, out=13 313, 4,6 M ETH transacted) — référence publique du
hot wallet Binance documentée. Le wallet `0xF977…1aceC` était dormant ce
mois-là (in=0) : la topologie capture ce qui EST un exchange, pas une
étiquette héritée.

**Amendement figé pré-résultats** (remplace la formulation « whale ≥ 0,1 %
supply », impossible sur le modèle UTXO/account sans snapshots) :
1. Hub discovery = fenêtre **2020-01** uniquement (avant les fenêtres
   d'évaluation), heuristique topologie pure.
2. Seuils gelés : in-degree ≥ 5 000, out-degree ≥ 100, volume ≥ 1 000 ETH,
   top 30 par score (in×out).
3. Le set figé est écrit dans `data/onchain/eth_hubs_2020-01.json`
   (provenance: job BigQuery id, sha256, fenêtre, SQL) ; tout usage
   ultérieur consomme ce set et jamais une redécouverte.
   **Empreinte** : sha256 = f2c7f06b8c81849d (fichier local, ignoré par
   git, 20 hubs retenus — le hub Binance actif #1 et le portefeuille
   identitaire de CZ 0x5f54… y figurent).
4. Signal = flux net journalier de ce set (deposits − withdrawals,
   adresses figées), agrégé 7 jours au screen.

## Hypothèse (formulation figée)

Les transferts on-chain observables télégraphient les intentions des gros
holders. Le signal candidat : **flux exchange net sur 7 jours** — masse
des transferts depuis les portefeuilles whales (≥ 0,1 % de la
circulation) vers les adresses d'exchange connues, moins les retraits :
- un flux net d'entrées sur exchange (= préparation de vente) prédit des
  rendements subséquents négatifs ;
- un flux net de retraits prédit des rendements neutres ou positifs.

Combinable uniquement avec les deux signaux déjà validés du projet
(funding, basis) ; jamais en agrégation ML.

## Alignement avec la constitution

- Une seule hypothèse testable, seuils figés avant lecture.
- Écran vectoriel d'abord : corrélation flux(t) vs rendements t+1..t+5,
  t Newey-West, fenêtres IS 2021-2023 / OOS 2023-07→2026-08 identiques aux
  features porteuses 009/010.
- Aucun recalibrage après lecture du résultat.

## Contraintes de données — gate de faisabilité clôturée (2026-10-11)

Sondes réseau exécutées le 2026-10-11 :

1. **Blockchair** : stats sans clé OK ; dashboards par adresse → HTTP 430
   (blacklist temporaire immédiate sans clé) — flux whale = offre payante.
2. **Etherscan V2** : clé obligatoire sur toute requête ; le free tier
   (5 req/s) ne peut ni classer l'ensemble des holders ni balayer les
   adresses d'exchange depuis 2019 à coût deterministe raisonnable.
3. **DefiLlama** : gratuit, mais couvre TVL/protocoles — pas de flux whale
   par adresse.

**Verdict (2026-10-11) : PASSED.** Les requêtes réelles sur
`bigquery-public-data.crypto_bitcoin` sont **facturées 0 octet** — un scan
complet de `outputs` (3,96 milliards de lignes) a tourné avec
`total_bytes_billed = 0` sur un compte sandbox **sans billing**. Les bases
sondes confirment des données vivantes : blocks = 970 939 lignes (09/10),
outputs d'un bloc = 6 156 lignes, transactions ETH ≈ 200 k / 1 000 blocs.
Le sandbox sans carte suffit ; les sources payantes ne sont pas nécessaires.

La couverture est complète : `inputs`/`outputs` (BTC UTXO, adresses
dépaquetées par UNNEST), `transactions`/`token_transfers`/`traces` (ETH).
Les metadata (num_rows/bytes et dry-run) mentent (0 partout) — seuls les
comptes réels font foi ; les requêtes pleines restent sans coût.

## Ordre de falsification (identique aux features précédentes)

1. RED/GREEN ingestion → colonnes (ts, flux_net_7d_usd, marque)
2. écran vectoriel — signal vs rendements subséquents, coûts identiques à
   l'écran carry (11 bps spot, funding réel)
3. moteur événementiel seulement si l'écran franchit les seuils
4. stress + holdout pré-enregistré avant tout paper
