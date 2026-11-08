# Résultats — carry toujours couvert levieré (014) : l'échelle figée

Exécution du 2026-11-08 selon `docs/carry-leverage-2026-11-brief.md` (brief
figé + amendement pré-exécution : APR 6 % flat, solvabilité sur la vue
jointe). Huit invocations du harnais existant (OOS + bear × F ∈ {1, 2,
3,5, 5}), 32 jambes moteur à 1 fill / 0 rejet. Le socle F=1 reproduit les
chiffres validés de la feature 010 **à l'identique** (BTC +25,48 % / t 7,20 /
DD 0,38 % ; ETH +17,97 % / t 6,04 / DD 0,29 %) : la fidélité mécanique
précède la lecture du levier.

## L'échelle de verdict, échelon par échelon

### 1. Solvabilité sur la vue jointe — PASS partout

| F | ratio joint min (BTC) | (ETH) | seuil 2,0 |
|---|---|---|---|
| 1 | 156 | 234 | — |
| 2 | 87 | 126 | ✓ |
| 3,5 | 58 | 78 | ✓ |
| 5 | 45 | 57 | ✓ |

Aucune liquidation jointe n'approche le seuil ; en fenêtre bear le minimum
tombe à 34,5 (ETH F=5). Le mécanisme reste un livre hedgé en permanence.

### 2. Stress LUNA (2022-05-04 → 2022-05-20, sous marge) — PASS

DD intraday (marques daily) dans la fenêtre : BTC ≤ 0,21 %, ETH ≤ 0,30 %
à tous les F. Les six mois de funding négatif (pires : BTC 2020-03
−0,5 % de taux cumulé ; ETH 2022-09 −1,6 %) sont dans les runs, aucun
n'approche le budget.

### 3. Budgets de drawdown — PASS

DD bear 2020-2022 : 0,69 % → 4,24 % (BTC), 2,24 % → 2,87 % (ETH) —
tous ≤ 12 %. p01 (tail année, bootstrap de blocs) : +0,81 % (pire,
ETH F=5) ≥ −8 %. Le budget holdout ≤ 2,5 % est pour décembre.

### 4. Statistique — COHÉRENCE violée à lettre figée

t NW tous ≥ 3,27 et OOS > 0 partout. AGREGAT portefeuille (50/50, base
40 k, fenêtre 3,17 ans) :

| F | net OOS | intérêt d'emprunt | Δ linear | ratio / F×net(1) |
|---|---|---|---|---|
| 1 | +21,73 % | 0 | — | — |
| 2 | +33,55 % | 9,9 % | −18,6 % (BTC) à −28,7 % (ETH) | ✗ |
| 3,5 | +50,87 % | 25,2 % | −27,4 % à −41,2 % | ✗ |
| 5 | +68,18 % | 40,5 % | −30,9 % à −46,2 % | ✗ |

**L'identité du déficit est exacte** : mesuré = F×net(1) − intérêt/20 000
au point près (BTC F=2 : 50,96 % − 9,47 % = 41,49 % mesuré ; ETH F=3,5 :
62,91 % − 25,94 % = 36,97 % mesuré ; six couples, écart ≤ 2 bps). Le
mécanisme s'ajuste MECHANIQUEMENT au levier ; le total de la déviation
linéaire est le coût d'emprunt figé. La cohérence ± 15 % figée, comparée
au dol linéaire NU, est violée pour tout F > 1.

## Verdict à lettre figée

**NO-GO pour tout F > 1** : l'échelon 4 est le plus strict, la cohérence
± 15 % est violée, et la cause est le coût d'emprunt — pas un échec du
mécanisme, mais la lettre figée est la lettre figée.

Deux lectures pour la suite (décision utilisateur UNIQUEMENT, avant le
holdout de décembre) :

- **A. Lettre tenue** : le portefeuille reste 1× (validé et paperisé).
  Le 014 est clos NO-GO, un fork documenté reste ouvert.
- **B. Ré-enregistrement 014-b** (transparent, AVANT les données de
  décembre, dans ce dossier) : la cohérence est refigée contre
  l'espérance `F×net(1) − intérêt(F) − 15 %` (le revenu funding et les
  frais s'échelonnent exactement linéairement — identité vérifiée),
  échelons 1-3 inchangés. Le holdout de décembre teste alors le F
  survivant le plus élevé.

## La contrainte économique réelle (au run-rate d'aujourd'hui)

La sous-période 2026YTD (financement comprimé) au net d'intérêts :
BTC F=2 +1,3 % sur 8 mois (≈ +2 %/an), ETH F=2 −0,8 %, ETH F=5 −3,9 %.
**Au financement actuel, le levier ajoute ~2 %/an au mieux et devient
négatif côté ETH dès F=2** ; les années riches (2024 : +22 % à F=2) sont
celles où le levier paye. Le 014 amplifie un revenu en compression.

## Fragilité opérationnelle (métrique de transferts)

Les minima par compte (hors vue jointe) montrent le besoin de transferts
récurrents : perp equity min −491 k (ETH bear F=2), −866 k (ETH F=3,5),
−1,24 M (ETH F=5) — compensés par la jambe spot au même instant, mais le
volume d'opérations de marge croît en F². À F ≥ 3,5, l'exploitation
deux-comptes devient lourde ; la vue jointe (Portfolio Margin Binance)
est le seul déploiement réaliste au-delà de F=2.

---

Fenêtres : OOS 2023-07-01 → 2026-08-31 (entrée fraîche 2023-07-01) ;
bear 2020-01-08 → 2023-06-30. Sorties figées :
`data/carry_leverage_{oos,bear}_f*.json` +
`data/carry_leverage_{oos,bear}_analysis.json` ; runs
`runs/carry-leverage-2026-11/`. Verdict lu le 2026-11-08 dans l'ordre du
brief, avant tout amendement post-données.
