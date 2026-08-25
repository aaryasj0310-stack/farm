# Kaggriculture Profitability Report

Season = 30 days, starting quadrant = 25 tiles. Crops replanted
back-to-back; the fertilized vs unfertilized variant is chosen per
asset by higher season net profit. Animals: daily feeding (1 wheat @ $25),
care policy 'never', fertilizer collected but not sold unless noted.

## Regime rankings (by PPTD = profit / tile / day)

### Spot Base

| rank | asset | strategy | price | net/season | PPTD | ROCI % | payback d |
|---|---|---|---|---|---|---|---|
| 1 | MELON | fertilized | $250 | $3,960 | $132.00 | 733.3% | 4.1 |
| 2 | STRAWBERRY | fertilized | $120 | $660 | $22.00 | 220.0% | 13.6 |
| 3 | COW | care_never | $160 | $610 | $20.33 | 152.5% | 19.7 |
| 4 | CARROT | unfertilized | $35 | $595 | $19.83 | 425.0% | 7.1 |
| 5 | WHEAT | unfertilized | $25 | $540 | $18.00 | 900.0% | 3.3 |
| 6 | TOMATO | fertilized | $60 | $460 | $15.33 | 92.0% | 32.6 |
| 7 | SHEEP | care_never | $200 | $350 | $11.67 | 70.0% | 42.9 |
| 8 | GOOSE | care_never | $50 | $250 | $8.33 | 83.3% | 36.0 |

### Town Scarcity

| rank | asset | strategy | price | net/season | PPTD | ROCI % | payback d |
|---|---|---|---|---|---|---|---|
| 1 | MELON | fertilized | $300 | $4,860 | $162.00 | 900.0% | 3.3 |
| 2 | COW | care_never | $256 | $1,666 | $55.53 | 416.5% | 7.2 |
| 3 | STRAWBERRY | fertilized | $204 | $1,332 | $44.40 | 444.0% | 6.8 |
| 4 | CARROT | unfertilized | $70 | $1,330 | $44.33 | 950.0% | 3.2 |
| 5 | WHEAT | unfertilized | $45 | $1,020 | $34.00 | 1700.0% | 1.8 |
| 6 | TOMATO | fertilized | $84 | $844 | $28.13 | 168.8% | 17.8 |
| 7 | GOOSE | care_never | $70 | $770 | $25.67 | 256.7% | 11.7 |
| 8 | SHEEP | care_never | $240 | $670 | $22.33 | 134.0% | 22.4 |

### Competitive Glut

| rank | asset | strategy | price | net/season | PPTD | ROCI % | payback d |
|---|---|---|---|---|---|---|---|
| 1 | WHEAT | unfertilized | $10 | $180 | $6.00 | 300.0% | 10.0 |
| 2 | TOMATO | unfertilized | $24 | $92 | $3.07 | 92.0% | 32.6 |
| 3 | CARROT | unfertilized | $10 | $70 | $2.33 | 50.0% | 60.0 |
| 4 | GOOSE | care_never | $40 | $-10 | $-0.33 | -3.3% | 300000000000.0 |
| 5 | STRAWBERRY | unfertilized | $1 | $-96 | $-3.20 | -96.0% | 100000000000.0 |
| 6 | MELON | unfertilized | $1 | $-148 | $-4.93 | -92.5% | 160000000000.0 |
| 7 | COW | care_never | $1 | $-1,139 | $-37.97 | -284.8% | 400000000000.0 |
| 8 | SHEEP | care_never | $1 | $-1,242 | $-41.40 | -248.4% | 500000000000.0 |

## Endgame cutoff days

| asset | hard cutoff | first-yield cutoff | economic cutoff |
|---|---|---|---|
| WHEAT | 25 | 25 | 25 |
| CARROT | 26 | 26 | 26 |
| MELON | 21 | 19 | 21 |
| TOMATO | 18 | 21 | 18 |
| STRAWBERRY | 13 | 19 | 13 |
| GOOSE | 25 | - | 10 |
| COW | 21 | - | 11 |
| SHEEP | 23 | - | 11 |

## Key strategic notes

- **Melon dominates spot economics** only while prices hold; its glut curve
  (sq, target 3.6) crashes to $1 within ~160 dumped units — sell in small
  slices across days.
- Fertilizer ($100) is +EV on melon (cycle 10d -> 8d enables a 4th harvest)
  and on ongoing crops with two applications, but -EV on wheat/carrot at
  base prices (extra yield < fertilizer cost). Animal fertilizer is free.
- Animals amortize slowly: a goose needs ~10 days to break even at base
  egg prices; buy animals early or not at all.
- In a competitive glut, staples (wheat/tomato/carrot) retain positive
  margin while premium goods sit at the $1 floor — diversify.

## Assumptions

- Feed = 1 wheat/day at $25 (base market price).
- Coop/pasture build cost treated as $0 cash (rules do not price them);
  each structure occupies one tile.
- Travel amortized 1 move per field action; hands cost fib(n)/day.