# Brief de recherche — signal on-chain de distribution des whales

Rédigé le 2026-10-11 **avant tout calcul de rendement et sans lecture de
données on-chain** — transposition du ch11 (scorecards) d'*Investing for
Programmers*. Ce document fige l'hypothèse d'un éventuel feature 012 ; il
ne vaut autorisation d'aucune sorte.

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
