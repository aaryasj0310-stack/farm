# P1.3: 2x2 Factorial SW Regression Analysis — 5-Arm Balanced Results

- Control SHA: `237cf5ee54498ed1ad2fa04d00ad9a0ebd27352e`
- P1.3-A source HEAD: `18740e0e6b2c02bd547b411eb08214edb03acbd4`
- Worktree fingerprint: `a662d6aea288d9bc0884c8da61d64d0ea3c99e1c2755cf87061432e35e1d6e19`
- Engine: 1.32.7
- Matched cases: 40/40
- Engine errors: 0

| Metric | Control | Arm A (P1.3-A) | Arm B (Tight Soil) | Arm C (Livestock Cap) | Arm D (Combined) |
|---|---:|---:|---:|---:|---:|
| Mean final score | 97,618.23 | 93,713.18 | 94,252.93 | 99,969.45 | 99,508.90 |
| Confirmed SW acquisition cases | 0 | 31 | 31 | 13 | 13 |
| Starvation observations | 13103 | 31149 | 30666 | 14325 | 14490 |
| NW+NE HARVEST attempts | 10226 | 9550 | 9594 | 10394 | 10407 |
| NW+NE unwatered EOD | 6463 | 7499 | 7449 | 4985 | 4984 |
| SW soil plants confirmed | 0 | 808 | 735 | 323 | 299 |
| SW soil active plant-days | 0 | 3453 | 3213 | 1368 | 1297 |
| SW pasture plants confirmed | 0 | 0 | 0 | 0 | 0 |
| SW pasture active plant-days | 0 | 0 | 0 | 0 | 0 |
| Wheat purchase units ordered | 32182 | 42640 | 42753 | 33563 | 33475 |
| Wheat purchase spend ($) | 804,550.00 | 1,066,000.00 | 1,068,825.00 | 839,075.00 | 836,875.00 |
| Livestock spend ($) | 190,000.00 | 215,500.00 | 215,500.00 | 196,400.00 | 196,400.00 |
| Scheduler travel | 179439 | 179631 | 179267 | 170118 | 170093 |
| Arm B tight soil blocked turns | 0 | 0 | 3131 | 0 | 978 |
| Arm C livestock cap rejected animals | 0 | 0 | 0 | 3807 | 3807 |

## Matched Factorial Deltas

- **B vs A (Isolated Tight Soil)**: mean $539.75; median $10.00; SD $2,305.10; 95% CI [$-174.61, $1,254.11]; 20W/9T/11L (N=40).
- **C vs A (Isolated Livestock Cap)**: mean $6,256.27; median $6,409.00; SD $7,656.39; 95% CI [$3,883.54, $8,629.01]; 27W/0T/13L (N=40).
- **D vs A (Combined vs Baseline)**: mean $5,795.73; median $5,791.50; SD $7,760.68; 95% CI [$3,390.67, $8,200.78]; 26W/0T/14L (N=40).
- **D vs B (Incremental Livestock Cap on B)**: mean $5,255.98; median $5,971.00; SD $7,021.22; 95% CI [$3,080.08, $7,431.87]; 27W/0T/13L (N=40).
- **D vs C (Incremental Tight Soil on C)**: mean $-460.55; median $0.00; SD $1,432.20; 95% CI [$-904.39, $-16.71]; 3W/27T/10L (N=40).
- **A vs Control (P1.3-A vs Production)**: mean $-3,905.05; median $-6,476.00; SD $9,836.39; 95% CI [$-6,953.38, $-856.72]; 13W/0T/27L (N=40).
- **B vs Control**: mean $-3,365.30; median $-5,330.50; SD $9,399.57; 95% CI [$-6,278.26, $-452.34]; 13W/0T/27L (N=40).
- **C vs Control**: mean $2,351.22; median $2,881.50; SD $7,632.73; 95% CI [$-14.18, $4,716.63]; 25W/0T/15L (N=40).
- **D vs Control**: mean $1,890.67; median $2,881.50; SD $7,790.21; 95% CI [$-523.54, $4,304.89]; 24W/0T/16L (N=40).
- **Factorial Interaction (D - B - C + A)**: mean $-1,000.30; median $-220.50; SD $2,723.43; 95% CI [$-1,844.30, $-156.30]; 10W/8T/22L (N=40).