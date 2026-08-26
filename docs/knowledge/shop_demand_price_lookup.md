# Observed Shop Combination Demand & Price Forecast Lookup

**Artifact ID**: `LOOKUP-SHOP-001`  
**Date**: 2026-08-26  
**Purpose**: Compact reference mapping observed town shop combinations to daily demand drain rates and projected scarcity price paths.  
**Note**: These values represent environmental price and demand forecasts. They serve as informational inputs for the decision-making layer and should **not** be treated as pre-determined optimal planting or selling rules.

---

## 1. Shop-to-Product Marginal Demand Addition Matrix

Daily consumption added per active instance of each shop type (units/day):

| Shop Type | WHEAT | CARROT | TOMATO | STRAWBERRY | MELON | EGG | MILK | WOOL | FERTILIZER |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **BAKERY** | +6 | — | — | — | — | +6 | — | — | — |
| **PIZZA_SHOP** | +6 | — | +6 | — | — | — | +6 | — | — |
| **BRUNCH_SPOT** | +6 | — | — | +6 | — | +6 | — | — | — |
| **YARN_STORE** | — | — | — | — | — | — | — | +12 | — |
| **ICE_CREAM_SHOP** | +6 | — | — | +6 | — | — | +6 | — | — |
| **PET_CAFE** | — | +12 | — | — | — | — | — | — | — |
| **SMOOTHIE_SHOP** | — | — | — | +6 | — | — | +6 | — | — |
| **FARMERS_MARKET** | +6 | +6 | +6 | +6 | — | — | — | — | — |
| **TOWN_CENTER** *(Always Active)* | **+1** | **+1** | **+1** | **+1** | **+1** | **+1** | **+1** | **+1** | **0** |

---

## 2. Product-by-Product Scarcity Price Forecasts

Projected market sell prices under town consumption assuming zero player supply (scarcity trajectory):

### 🌾 WHEAT ($I_0 = 10,000, \text{Base} = \$25, T = 400, \text{Curve} = \text{sqrt}$)
| Active Consuming Shops | Daily Drain | Day 10 Price | Day 20 Price | Day 29 Price | Hinge Spike Risk |
| :--- | :---: | :---: | :---: | :---: | :---: |
| None (Town Center only) | 1/day | $28 | $29 | $30 | No |
| Any 1 Shop (e.g. Bakery) | 7/day | $33 | $37 | $39 | No |
| Any 2 Shops (e.g. Bakery + Pizza) | 13/day | $36 | $41 | $44 | No |
| Any 3 Shops | 19/day | $39 | $44 | $48 | No |
| Any 4 Shops | 25/day | $41 | $47 | $52 | No |
| All 5 Shops Active | 31/day | $43 | $50 | $55 | No |

---

### 🥕 CARROT ($I_0 = 10,000, \text{Base} = \$35, T = 450, \text{Curve} = \text{hinge}$)
*Note: Hinge triggers when total inventory drain exceeds $T = 450$.*
| Active Consuming Shops | Daily Drain | Day 10 Price | Day 20 Price | Day 29 Price | Hinge Spike Risk |
| :--- | :---: | :---: | :---: | :---: | :---: |
| None (Town Center only) | 1/day | $36 | $37 | $37 | No |
| Farmers Market (+6) | 7/day | $40 | $46 | $51 | No |
| Pet Cafe (+12) | 13/day | $45 | $55 | $64 | No |
| Pet Cafe + Farmers Market | **19/day** | **$50** | **$65** | **$92** | **YES (Day 24+)** |
| 2× Pet Cafe + Farmers Market | **31/day** | **$59** | **$88** | **$394** | **YES (Day 15+)** |

---

### 🍅 TOMATO ($I_0 = 10,000, \text{Base} = \$60, T = 200, \text{Curve} = \text{hinge}$)
*Note: Hinge triggers when total inventory drain exceeds $T = 200$. Low threshold makes Tomato highly reactive.*
| Active Consuming Shops | Daily Drain | Day 10 Price | Day 20 Price | Day 29 Price | Hinge Spike Risk |
| :--- | :---: | :---: | :---: | :---: | :---: |
| None (Town Center only) | 1/day | $61 | $62 | $63 | No |
| Any 1 Shop (Pizza or Farmers) | 7/day | $68 | $77 | $84 | **YES (Day 29)** |
| Any 2 Shops (Pizza + Farmers) | **13/day** | **$76** | **$108** | **$256** | **YES (Day 16+)** |
| Any 3 Instances (e.g. 2× Pizza + Farmers) | **19/day** | **$85** | **$191** | **$730** | **YES (Day 11+)** |

---

### 🍓 STRAWBERRY ($I_0 = 10,000, \text{Base} = \$120, T = 100, \text{Curve} = \text{sqrt}$)
*Note: High baseline demand with 4 consuming shops; prices rise rapidly under scarcity.*
| Active Consuming Shops | Daily Drain | Day 10 Price | Day 20 Price | Day 29 Price | Hinge Spike Risk |
| :--- | :---: | :---: | :---: | :---: | :---: |
| None (Town Center only) | 1/day | $147 | $158 | $165 | No |
| Any 1 Shop (e.g. Brunch) | 7/day | $190 | $219 | $240 | No |
| Any 2 Shops | 13/day | $216 | $255 | $283 | No |
| Any 3 Shops | 19/day | $236 | $284 | $317 | No |
| All 4 Shops Active | 25/day | $253 | $308 | $346 | No |

---

### 🍈 MELON ($I_0 = 10,000, \text{Base} = \$250, T = 300, \text{Curve} = \text{log}$)
*Note: Unaffected by shop unlocks. Fully deterministic town-center trajectory.*
| Active Consuming Shops | Daily Drain | Day 10 Price | Day 20 Price | Day 29 Price | Hinge Spike Risk |
| :--- | :---: | :---: | :---: | :---: | :---: |
| None (Town Center only) | 1/day | $271 | $277 | $280 | No |

---

### 🥚 EGG ($I_0 = 10,000, \text{Base} = \$50, T = 332, \text{Curve} = \text{hinge}$)
| Active Consuming Shops | Daily Drain | Day 10 Price | Day 20 Price | Day 29 Price | Hinge Spike Risk |
| :--- | :---: | :---: | :---: | :---: | :---: |
| None (Town Center only) | 1/day | $51 | $51 | $52 | No |
| Any 1 Shop (Bakery or Brunch) | 7/day | $54 | $58 | $62 | No |
| Any 2 Shops (Bakery + Brunch) | **13/day** | **$58** | **$66** | **$76** | **YES (Day 26+)** |
| Any 3 Instances | **19/day** | **$62** | **$74** | **$118** | **YES (Day 18+)** |

---

### 🥛 MILK ($I_0 = 10,000, \text{Base} = \$160, T = 122, \text{Curve} = \text{sqrt}$)
| Active Consuming Shops | Daily Drain | Day 10 Price | Day 20 Price | Day 29 Price | Hinge Spike Risk |
| :--- | :---: | :---: | :---: | :---: | :---: |
| None (Town Center only) | 1/day | $187 | $199 | $207 | No |
| Any 1 Shop (e.g. Pizza) | 7/day | $233 | $263 | $284 | No |
| Any 2 Shops | 13/day | $259 | $300 | $329 | No |
| All 3 Shops Active | 19/day | $280 | $329 | $364 | No |

---

### 🧶 WOOL ($I_0 = 10,000, \text{Base} = \$200, T = 105, \text{Curve} = \text{log}$)
| Active Consuming Shops | Daily Drain | Day 10 Price | Day 20 Price | Day 29 Price | Hinge Spike Risk |
| :--- | :---: | :---: | :---: | :---: | :---: |
| None (Town Center only) | 1/day | $221 | $226 | $229 | No |
| Yarn Store (+12) | 13/day | $242 | $248 | $251 | No |
| 2× Yarn Store (+24) | 25/day | $248 | $255 | $258 | No |

---

### 🧪 FERTILIZER ($I_0 = 10,000, \text{Base} = \$100, T = 200, \text{Curve} = \text{linear}$)
| Active Consuming Shops | Daily Drain | Day 10 Price | Day 20 Price | Day 29 Price | Hinge Spike Risk |
| :--- | :---: | :---: | :---: | :---: | :---: |
| None (Town Center only) | 0/day | $100 | $100 | $100 | No |

---

## 3. Decision-Layer Forecast Guidance

1. **Deterministic Baselines**:
   * **Melon** ($250 \rightarrow \$280$) and **Fertilizer** ($\$100$) have zero shop variance. Their prices depend entirely on player sell volume.
2. **High-Yield Scarcity Targets**:
   * **Tomato** reaches superlinear hinge spikes ($\$256 \text{--} \$730$) whenever 2+ Tomato-consuming shops are active.
   * **Carrot** spikes strongly ($\$92 \text{--} \$394$) if Pet Cafe is paired with Farmers Market or multiple Pet Cafes.
3. **High-Volume Drains**:
   * **Strawberry** and **Milk** consistently climb to $\$280\text{--}\$360$ under typical shop unlocks, supporting steady multi-harvest ongoing crops and livestock production.
