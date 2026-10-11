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

## Contraintes de données — gate de faisabilité non résolue

Avant toute expérimentation, établir :
1. une **source publique déterministe et rejouable** (candidats à évaluer :
   Blockchair, Etherscan v2, DefiLlama ; Glassnode et Dune sont payants) —
   l'ingestion doit supporter checksum et rejeu ;
2. la **couverture 2019+** pour BTC et ETH, idéalement les actifs UM du
   scan pour croiser avec le basis ;
3. la **stabilité de l'offre** : une API qui dégrade son offre casse le
   rejeu constitutionnel.

Si aucune source gratuite stable n'existe : close proprement (NO-GO
technique documenté).

## Ordre de falsification (identique aux features précédentes)

1. RED/GREEN ingestion → colonnes (ts, flux_net_7d_usd, marque)
2. écran vectoriel — signal vs rendements subséquents, coûts identiques à
   l'écran carry (11 bps spot, funding réel)
3. moteur événementiel seulement si l'écran franchit les seuils
4. stress + holdout pré-enregistré avant tout paper
