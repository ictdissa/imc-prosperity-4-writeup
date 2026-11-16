# Technical strategy reference: Rounds 3, 4, and 5

**Dissa Trading · IMC Prosperity 4**

[Back to the portfolio](../README.md)

This README explains how the three supplied Python traders operate, including their signals, pricing formulas, execution rules, inventory controls, and intended sources of profit.

The explanation follows executable code. Comments inside the files are treated as descriptions of author intent, not instructions or independent evidence of profitability. No backtest was run for this document.

## 1. Files and strategy overview

| Round | Source file | Main approach |
|---|---|---|
| 3 | [round_3.py](../strategies/round_3.py) | Passive spread capture in Hydrogel, Velvet, and VEV_4000, plus zero-price bids on distant-strike vouchers |
| 4 | [round_4.py](../strategies/round_4.py) | Anchored fair-value trading, named-trader signals, option volatility-curve trading, and a conditional short-call overlay |
| 5 | [round_5.py](../strategies/round_5.py) | Selective market making with momentum and Circle signals, plus two statistical pair strategies |

### Which round uses option models?

| Technique | Round 3 | Round 4 | Round 5 |
|---|---|---|---|
| Implied volatility (IV) | No | Yes | No |
| Black–Scholes call pricing | No | Yes | No |
| Volatility smile/skew fitting | No | Yes: quadratic IV curve | No |
| Inventory-based quote skew | Yes | Yes | Yes |
| Explicit option delta hedging | No | No | Not applicable |

**Volatility skew** describes differences in implied volatility across strikes. **Inventory skew** means changing quotes because the bot already holds a position. They are different concepts.

## 2. Shared mechanics and vocabulary

- **Best bid:** highest available buying price.
- **Best ask:** lowest available selling price.
- **Spread:** best ask minus best bid.
- **Midpoint:** `(best bid + best ask) / 2`.
- **Fair value:** the bot's estimated reference value, which may differ from the midpoint.
- **Passive/maker order:** an order posted for others to trade against.
- **Aggressive/taker order:** an order priced to execute against existing liquidity.
- **Long position:** positive holdings; benefits from a price increase.
- **Short position:** negative holdings; benefits from a price decrease.
- **Clip:** maximum size of one trading action or quote.
- **Soft limit:** an internal threshold for slowing or stopping accumulation.
- **Hard limit:** the configured maximum permitted position.
- **Adverse selection:** being filled shortly before the market moves against the trade.

Each trader receives the current order books and positions in `run(state)`, builds orders, and returns `(orders, 0, traderData)`. The second value is zero in all three files: none requests conversions. `traderData` stores information needed across updates.

An order submission is not a confirmed fill. Several routines update temporary expected positions as if submitted orders execute; actual positions arrive in a later state. None of these files contains a portfolio-level P&L stop-loss or an end-of-session liquidation rule.

## 3. Round 3: passive external-flow market making

### 3.1 Strategy thesis

Round 3 aims to buy below estimated fair value and sell above it, mostly by waiting inside sufficiently wide spreads. Inventory controls try to prevent spread capture from becoming a large directional bet.

There are four active modules:

1. Hydrogel passive market making.
2. Velvet passive market making.
3. VEV_4000 passive market making, anchored to Velvet.
4. Zero-price buy orders for VEV_6000 and VEV_6500.

Other voucher names appear in the limit dictionary but have no active trading module. In particular, Round 3 does not fit IV, use Black–Scholes, or trade a volatility smile.

### 3.2 Step 1: restore memory and determine capacity

The trader restores its moving averages from JSON. Missing or invalid data resets memory.

Configured position limits are ±200 for Hydrogel and Velvet and ±300 for vouchers. Initial directional capacities are:

```text
Buy capacity  = max(0, limit − current position)
Sell capacity = max(0, limit + current position)
```

It requires both sides of the book for normal market making.

### 3.3 Step 2: estimate Hydrogel and Velvet fair values

The same estimator is applied independently to both products.

**A. Wall midpoint.** Find the price with the largest buy quantity and the price with the largest sell quantity across the book, then average those two prices. These need not be the best bid and ask.

**B. Microprice.** Weight the best prices by opposite-side quantities:

```text
Microprice = (best ask × bid quantity + best bid × ask quantity)
             / (bid quantity + ask quantity)
```

Large bid-side quantity pushes microprice toward the ask, representing buying pressure.

**C. Exponential moving average.** Smooth the ordinary midpoint:

```text
EMA_now = 0.06 × midpoint_now + 0.94 × EMA_previous
```

The first observation initializes the EMA.

**D. Blend and inventory adjustment.**

```text
Base fair = 0.45 × wall midpoint + 0.25 × microprice + 0.30 × EMA

Hydrogel fair = base fair − 7.0 × Hydrogel position / 200
Velvet fair   = base fair − 4.5 × Velvet position / 200
```

Holding a long position lowers the reference price; holding a short raises it. This encourages inventory reduction.

### 3.4 Step 3: trim unusually large inventory

Before checking whether the spread is wide enough for passive quoting, the bot can reduce a large position immediately at the best opposing price.

| Product | Soft threshold | Emergency trim starts at absolute position | Maximum trim per update |
|---|---:|---:|---:|
| Hydrogel | 95 | 165 | 18 |
| Velvet | 105 | 170 | 14 |
| VEV_4000 | 120 | 210 | 10 |

The trim is also constrained by displayed volume, capacity, and the amount above the soft threshold. It does not necessarily return the position to the soft threshold in one update.

### 3.5 Step 4: quote inside wide spreads

| Product | Minimum spread | Larger-size spread threshold | Base size | Larger size | Required fair-value margin |
|---|---:|---:|---:|---:|---:|
| Hydrogel | 10 | 16 | 56 | 78 | 1.00 |
| Velvet | 5 | 6 | 34 | 48 | 0.75 |
| VEV_4000 | 14 | 22 | 18 | 26 | 5.00 |

If the spread is too narrow, it posts no normal quotes. Otherwise:

```text
Proposed buy  = best bid + 1
Proposed sell = best ask − 1

Buy only if proposed buy ≤ fair − margin
Sell only if proposed sell ≥ fair + margin
```

The two proposed prices must remain distinct, with the buy below the sell.

Quote size decreases with inventory:

```text
Inventory fraction = min(1, abs(position) / soft threshold)
Size = max(4, integer(base-or-larger size × (1 − 0.55 × inventory fraction)))
```

Capacity can reduce the final quantity further.

### 3.6 Step 5: become one-sided when carrying inventory

The bot stops adding to a position before reaching its soft threshold:

- If position is greater than half the positive soft threshold, stop buying.
- If position is less than half the negative soft threshold, stop selling.

The half-thresholds are 47.5 Hydrogel, 52.5 Velvet, and 60 VEV_4000. Thus, for example, a Hydrogel position of +48 allows only inventory-reducing normal quotes.

### 3.7 Step 6: value VEV_4000 from Velvet

```text
VEV_4000 fair = inventory-adjusted Velvet fair − 4,000
               − 10 × VEV_4000 position / 300
```

The model treats this low-strike call as approximately the underlying minus its strike. This is a high-delta approximation, not a full option model: it does not explicitly price volatility or time value.

The anchor already includes Velvet's own inventory adjustment, so Velvet holdings also indirectly affect VEV_4000 quotes. The voucher has a separate inventory adjustment as well.

No offsetting Velvet hedge is submitted when the voucher trades. Calling it a synthetic Velvet instrument describes the pricing approximation, not a hedged arbitrage.

### 3.8 Step 7: place zero-price tail bids

For each of VEV_6000 and VEV_6500:

- Submit a buy order at price 0.
- Order at most 35 units per update.
- Stop accumulating at a position of 280.
- Never pay 1 and never submit a short through this module.

The intended source of upside is acquiring a potentially valuable option without paying a purchase price. The code contains no selling routine for these holdings. Zero-price orders may remain unfilled; any settlement or fee assumptions would need separate confirmation from the market rules.

### 3.9 Worked example

Suppose Hydrogel has bid/ask 9,990 / 10,010, estimated fair 10,000, and position zero.

1. The spread is 20, so it qualifies for the larger starting size of 78.
2. Proposed prices are 9,991 and 10,009.
3. Both satisfy the 1-unit fair-value margin.
4. The bot can submit 78-unit quotes on both sides, subject to capacity.
5. If equal quantities eventually fill on both sides, the gross price difference is 18 per unit.

The principal risk is receiving only the buy fill before prices fall, or only the sell fill before prices rise.

## 4. Round 4: anchored fair values, trader identities, and options

### 4.1 Strategy thesis and execution sequence

Round 4 combines three sources of trading decisions:

1. Trade Hydrogel and Velvet around slowly changing fair values.
2. Compare voucher prices with an implied-volatility curve fitted from other strikes.
3. Sell central calls when Velvet looks overpriced and the named-trader signal permits it.

Every update restores memory, updates trader scores, trades the two underlying products, then evaluates vouchers. Option positions are not explicitly delta-hedged.

### 4.2 Step 1: build named-trader flow scores

The bot reads buyer and seller identities from public market trades. Each identity has a preset score depending on whether it bought or sold.

Velvet score contributions before quantity scaling:

| Trader | When buying | When selling |
|---|---:|---:|
| Mark 67 | +3.0 | −0.5 |
| Mark 55 | +0.3 | −0.2 |
| Mark 01 | +0.2 | −0.2 |
| Mark 14 | −0.7 | +0.4 |
| Mark 49 | −2.2 | +3.0 |
| Mark 22 | −0.2 | +2.0 |

Unlisted identities contribute zero. A positive score is interpreted as bullish for future Velvet prices. This is identity-specific: Mark 49 selling is considered bullish, while Mark 49 buying is considered bearish.

```text
Quantity scale = min(3, max(1, trade quantity / 5))
New score = 0.72 × previous score
            + sum(quantity scale × buyer and seller contributions)
```

Velvet's final score is capped to [−25, +25]. Hydrogel uses a separate score, capped to [−15, +15], with these weights:

| Trader | When buying Hydrogel | When selling Hydrogel |
|---|---:|---:|
| Mark 14 | +0.35 | −0.15 |
| Mark 22 | −1.00 | +1.00 |
| Mark 38 | −0.10 | +0.20 |

These coefficients are supplied assumptions. The code does not learn or re-estimate their predictive value during trading.

### 4.3 Step 2: calculate anchored underlying fair values

Both products retain up to 64 midpoint observations. Before 20 observations, their base values are 10,000 for Hydrogel and 5,250 for Velvet.

After the warmup:

```text
Hydrogel base = 0.70 × 10,000 + 0.30 × median(recent midpoints)
Hydrogel adjustment = clip(0.04 × Hydrogel score, −1, +1)
Hydrogel fair = clip(base + adjustment, 9,985, 10,018)

Velvet base = 0.88 × 5,250 + 0.12 × median(recent midpoints)
Velvet adjustment = clip(0.35 × Velvet score, −8, +8)
Velvet fair = base + adjustment
```

Here `clip(value, low, high)` means constrain the value to that interval. The Hydrogel score cap makes its effective flow adjustment at most ±0.6, even though the adjustment formula itself permits ±1.

The heavy fixed-price weights make this a mean-reversion strategy. Velvet's current market price can be well above the estimated fair value without immediately pulling fair value up by the same amount.

### 4.4 Step 3: trade the underlying products

The underlying trading routine rejects missing-sided books, nonpositive spreads, or spreads exceeding the configured maximum.

| Parameter | Hydrogel | Velvet |
|---|---:|---:|
| Position limit | ±200 | ±200 |
| Maximum accepted spread | 25 | 16 |
| New aggressive entry edge | 30 | 18 |
| Maximum clip per aggressive stage | 20 | 10 |
| Normal passive clip | 18 | 12 |
| Passive margin | 2 | 2 |
| Neutral inventory band | 60 | 60 |
| Inventory relief threshold | 160 | 120 |

The sequence is:

**A. Exit existing inventory.** Sell longs when the bid reaches fair value; buy back shorts when the ask reaches fair value. Hydrogel at absolute inventory of at least 160 accepts exits up to 10 units worse than fair. Velvet's relief edge is zero, so its threshold does not relax the exit price.

**B. Take sufficiently mispriced liquidity.** Buy asks at or below `fair − entry edge`; sell bids at or above `fair + entry edge`. The routine can walk through multiple acceptable price levels. Clip limits apply to each stage rather than being one overall update-wide trade budget.

**C. Post passive orders.** Calculate an inventory-sensitive reservation value:

```text
Excess = max(0, abs(expected position) − 60)
Reservation = fair − linear skew × expected position
              − convex coefficient × excess × sign(expected position)
```

Hydrogel uses linear skew 0.045 and convex coefficient 0.18. Velvet uses 0.040 and 0.14. Large positions therefore move quotes more strongly toward inventory reduction.

```text
Bid = min(best bid + 1, floor(reservation − 2))
Ask = max(best ask − 1, ceil(reservation + 2))
```

Passive size is scaled using absolute expected position divided by 200:

| Utilization | Size multiplier |
|---|---:|
| Up to 65% | 1.00 |
| Above 65%, up to 85% | 0.50 |
| Above 85%, up to 90% | 0.25 |
| Above 90% | 0.00 |

The order helpers also account for previously submitted quantities when calculating directional capacity.

### 4.5 Step 4: infer implied volatility with Black–Scholes

The option module uses Velvet's **current market midpoint** as spot. It uses trader-adjusted Velvet fair separately for the directional richness signal.

The code assumes a fixed time to expiry:

```text
T = 4 / 365 years
```

It does not reduce this value as timestamps advance.

Its call formula is Black–Scholes with no interest or dividend adjustment:

```text
d1 = [ln(S/K) + 0.5 × sigma² × T] / (sigma × sqrt(T))
d2 = d1 − sigma × sqrt(T)
Call price = S × N(d1) − K × N(d2)
```

`S` is Velvet spot, `K` is strike, `sigma` is annualized volatility, and `N` is the standard normal cumulative distribution function.

For each voucher, it finds the volatility whose Black–Scholes price matches the voucher midpoint. It uses 45 binary-search iterations between 0.0001 and 5.0.

Candidate fitting strikes are 5,000, 5,100, 5,200, 5,300, 5,400, and 5,500. A point is excluded if:

- Either side of its book is missing.
- Its spread exceeds 20.
- Its midpoint has less than 1 unit of value above intrinsic value `max(S − K, 0)`.
- Its IV is invalid or not strictly between 0.01 and 5.0.

The module requires at least four usable points overall.

### 4.6 Step 5: fit the volatility smile/skew

For each point:

```text
x = ln(K / S) / sqrt(T)
IV(x) = a × x² + b × x + c
```

The trader fits this quadratic by least squares. The quadratic term can represent smile curvature, and the linear term can represent skew/asymmetry. The fit does not constrain curvature or guarantee an arbitrage-free option surface.

When pricing a target voucher, its own point is excluded from the fit. At least three other points must remain. This prevents the target's own market price from directly anchoring its fitted valuation.

The predicted IV is capped to [0.01, 5.0] and passed through Black–Scholes to obtain a fair call price.

Only VEV_5000, VEV_5100, VEV_5200, and VEV_5300 receive trading orders. VEV_5400 and VEV_5500 are fitting inputs only. A target book's spread must be no greater than 12.

### 4.7 Step 6: trade option relative value

```text
Option reservation = Black–Scholes fair − 0.025 × option position
```

- Buy at the best ask if reservation exceeds the ask by at least 4.
- Sell at the best bid if the bid exceeds reservation by at least 4.
- Take at most 4 units per action, constrained by displayed liquidity.
- Use a normal soft inventory band of ±70.
- Also post passive quotes with a 2-unit margin and normally 2-unit size.

Passive size drops to 1 above 65% utilization and stops at 90% utilization. Additional directional gates stop passive bids at positions of +52.5 or more and stop passive asks at positions of −52.5 or less.

Example: if option fair and reservation are 100, an ask of 95 creates a 5-unit buying edge and qualifies for a buy. A bid of 105 creates a 5-unit selling edge and qualifies for a sell.

### 4.8 Step 7: overlay directional short calls

The directional measure is:

```text
Velvet richness = Velvet market midpoint − trader-adjusted Velvet fair
```

The bot submits an additional sale in each central voucher when all conditions hold:

1. Richness is at least 8.
2. Velvet trader score is 6 or lower.
3. The option bid is at least `option fair − 4`.
4. There is capacity within the overlay's ±140 band and the configured ±300 hard limit.

The third condition allows selling slightly below curve fair; the overlay is not purely an expensive-option sale. Its main thesis is that the underlying is rich and may fall.

```text
Strength = max(0, richness − 8)
Bearish bonus = max(0, −trader score) × 0.25
Clip = integer(min(18, 8 + 0.7 × strength + bearish bonus))
```

Selling first reduces any long holdings, then can establish or enlarge a short. The overlay itself contains no symmetric directional long-call entry rule, though the relative-value module can buy calls.

Example: spot 5,270, adjusted underlying fair 5,255, and trader score −4 give richness 15. The calculated clip is `int(8 + 0.7 × 7 + 1) = 13`, before liquidity and capacity constraints.

### 4.9 Step 8: cover existing call shorts

The overlay buys back an existing short when any of these holds:

- Richness is 2 or lower.
- Velvet trader score is at least 8.
- Option ask is at least 5 below its curve fair value.

It covers at most 18 units per update, constrained by liquidity and the short position size. It does not necessarily flatten immediately.

These exits are evaluated only if the option module passes its data and fitting checks. Missing curve inputs can therefore prevent both new overlay entries and these model-driven exits.

### 4.10 Implementation details and practical limits

- There is no explicit delta, gamma, or vega hedge and no aggregate option-risk budget across strikes. Several short calls can create concentrated exposure to a Velvet rally.
- A code comment says not to add bids while carrying the short overlay, but the actual passive bid condition is `position < 52.5`. Modest shorts can still receive passive bids; sufficiently large absolute inventory disables passive quoting entirely.
- The cover test occurs before the entry test. Because they are separate conditions, a cheap-option cover can be followed by another sale in the same update if entry conditions also hold.
- Helpers named `safe` provide quantity accounting, not proof of all execution outcomes. Voucher routines update temporary positions between orders while also counting submitted orders. The outer routine additionally updates expected voucher positions after the option function already did so; this duplicated bookkeeping has no later trading consumer in the current update.
- The filename and comments claim official replay success. No performance figures or replay evidence are established by this README.

## 5. Round 5: selective market making and statistical pairs

### 5.1 Strategy thesis and product selection

Round 5 lists 50 products across ten families: Galaxy Sounds, Sleep Pods, Microchips, Pebbles, Robots, UV Visors, Translators, Panels, Oxygen Shakes, and Snackpacks. All have a configured position limit of ±10.

Its main idea is to avoid unfavorable passive fill patterns, adjust quotes to recent movement, and use selected relationships between products.

These ten products are excluded from ordinary market making at every update:

```text
GALAXY_SOUNDS_PLANETARY_RINGS
GALAXY_SOUNDS_SOLAR_FLAMES
SLEEP_POD_LAMB_WOOL
MICROCHIP_SQUARE
MICROCHIP_RECTANGLE
PEBBLES_XS
PEBBLES_M
ROBOT_IRONING
UV_VISOR_MAGENTA
PANEL_1X2
```

Square, Rectangle, Pebbles XS, and Robot Ironing can still trade through pair modules. The other six have no active trading module in this file. With all 50 products available, ordinary market making covers 40 products.

### 5.2 Step 1: restore and update histories

The trader stores:

- Up to 21 midpoint observations per product for momentum.
- Up to 260 Circle midpoint observations for lead signals.
- Mean, variance, observation count, and target direction for each pair.

It updates histories, runs the pair modules, then runs ordinary market making on permitted products. Observation lags count available midpoint samples; they are not elapsed seconds.

### 5.3 Step 2: establish market-making fair value

```text
Fair = current midpoint − 0.35 × current position
Initial buy margin = 3
Initial sell margin = 3
Normal quote size = 5
```

For example, a +6 position lowers fair by 2.1, making the bot more willing to sell and less willing to buy.

### 5.4 Step 3: lean quotes with recent momentum

```text
Momentum = current midpoint − midpoint 20 observations earlier
```

If momentum is at least +5:

- Buy margin becomes 2.
- Sell margin becomes 4.

If momentum is at most −5:

- Buy margin becomes 4.
- Sell margin becomes 2.

The midpoint reference itself is unchanged by this module. The margins become asymmetric, encouraging trading in the direction of recent movement and requiring more compensation on the opposite side.

### 5.5 Step 4: use Circle as a leading indicator

The code defines these comparisons:

| Target | Circle history lag |
|---|---:|
| MICROCHIP_OVAL | 50 observations |
| MICROCHIP_SQUARE | 100 observations |
| MICROCHIP_RECTANGLE | 150 observations |
| MICROCHIP_TRIANGLE | 200 observations |

```text
Signal = Circle midpoint now − Circle midpoint lag observations ago
```

If absolute signal is at least 15:

```text
Fair shift = clip(0.20 × signal, −12, +12)
```

A positive signal also reduces the buy margin by 0.5 and raises the sell margin by 0.5; a negative signal does the reverse. Reduced margins have a floor of 1.

Only Oval and Triangle actually receive this treatment in the final trading loop. Square and Rectangle are disabled for ordinary market making, and their pair strategies do not use this Circle signal.

Example: if Circle is 30 higher than 50 observations ago, Oval's fair is shifted up by 6, and its margins lean another 0.5 toward buying.

This is a preset lead–lag hypothesis. The bot does not estimate these lags online or directly compare the follower's price with Circle's old price.

### 5.6 Step 5: apply inventory boundaries and place orders

- At position +5 or above, buy margin is at least 4.
- At position −5 or below, sell margin is at least 4.

```text
Buy price  = min(best bid + 1, floor(fair − buy margin))
Sell price = max(best ask − 1, ceil(fair + sell margin))
```

It skips quoting if buy price is not below sell price. Buy orders are capped at `min(5, 10 − position)`; sell orders at `min(5, 10 + position)`.

This module normally supplies liquidity. It has no separate instruction to aggressively chase momentum. There is no minimum-spread gate like Round 3: its fair-value margins can place orders farther away when the current book is narrow.

### 5.7 Step 6: calculate statistical pair spreads

Two pairs run separately from market making:

| Pair | Spread definition | Entry threshold | Exit threshold |
|---|---|---:|---:|
| Rectangle / Pebbles XS | `Rectangle mid − 0.20 × Pebbles XS mid` | ±2.0 standard deviations | Absolute z-score <0.5 |
| Square / Robot Ironing | `Square mid + 0.32 × Robot Ironing mid` | ±2.5 standard deviations | Absolute z-score <0.5 |

For each pair, the first valid spread initializes the mean, variance starts at 1, and observation count starts at zero. A 50-observation warmup precedes signal-based entries.

The z-score is calculated using the previously stored statistics:

```text
z = (current spread − stored mean) / sqrt(stored variance)
```

After deciding on positions, the bot updates statistics:

```text
Difference = spread − old mean
New mean = old mean + 0.005 × difference
New variance = 0.995 × old variance + 0.005 × difference²
```

This creates a slowly adapting reference for spread mean reversion.

### 5.8 Step 7: set pair targets

**Rectangle / Pebbles XS**

| Signal | Rectangle target | Pebbles XS target |
|---|---:|---:|
| z > 2 | −10 | +10 |
| z < −2 | +10 | −10 |
| abs(z) <0.5 | 0 | 0 |

**Square / Robot Ironing**

| Signal | Square target | Robot Ironing target |
|---|---:|---:|
| z >2.5 | −10 | −10 |
| z <−2.5 | +10 | +10 |
| abs(z) <0.5 | 0 | 0 |

The second spread adds the two weighted prices because its hedge coefficient is negative. Both position targets therefore have the same sign.

Between the entry and exit thresholds, the previous target direction persists. An extreme opposite signal can reverse positions directly.

The 0.20 and −0.32 coefficients are used to construct signals, **not to scale order quantities**. Both legs target 10 units in magnitude. These are equal-unit pair trades, not coefficient-weighted hedges, and they are not guaranteed to be market-neutral.

### 5.9 Step 8: sweep the book toward pair targets

Pair execution is aggressive:

1. Compare actual position with the desired target.
2. If more units are needed, buy available asks from cheapest upward.
3. If fewer are needed, sell into bids from highest downward.
4. Continue until reaching the target or exhausting displayed liquidity.

The routine has no additional price cutoff. A reversal from −10 to +10 can request 20 units on a leg, even though the final target remains within ±10.

The two legs are submitted separately. One can fill more than the other, creating temporary unmatched exposure. Each later update again tries to reach the stored target using actual reported positions.

### 5.10 Worked pair example

Suppose the Rectangle/Pebbles spread has stored mean 100 and standard deviation 4, and the current spread is 110.

```text
z = (110 − 100) / 4 = 2.5
```

After warmup, this exceeds the entry threshold of 2. The bot targets short 10 Rectangle and long 10 Pebbles XS. When the absolute z-score falls below 0.5, it targets zero on both legs and takes liquidity to close them.

The thesis fails if the relationship shifts persistently, or if spread convergence is too small to cover execution costs. Equal-unit legs also do not precisely reproduce the weighted spread being measured.

### 5.11 Additional implementation notes

- No IV, Black–Scholes, volatility smile, or named-trader identity signal is used.
- The disabled list is fixed throughout the session; there is no start-time switch.
- A compatibility block updates limits in a locally installed backtester if available. It is not an alpha signal or live trading strategy.
- Comments describe robust historical pair behavior and toxic passive fills, but this file alone does not establish those empirical claims.

## 6. Comparing the intended sources of profit

| Component | Intended source of profit | Main way it can lose |
|---|---|---|
| Round 3 passive quotes | Buy below fair and sell above fair while capturing the spread | One-sided fills followed by an adverse price move |
| Round 3 VEV_4000 | Spread capture around the Velvet-minus-strike approximation | Underlying movement or omitted option time value |
| Round 3 zero bids | Positive eventual option value after acquisition at zero | No fills or no eventual positive value; rules and fees may matter |
| Round 4 underlying trades | Reversion toward anchored fair values, adjusted for trader flow | Persistent drift away from fixed anchors or unreliable identity signals |
| Round 4 option curve | A strike returns toward the valuation implied by other strikes | Poor curve fit, genuine strike-specific differences, or execution costs |
| Round 4 short-call overlay | Rich Velvet falls, reducing call prices | Velvet rallies or option volatility rises while calls are short |
| Round 5 market making | Spread capture with inventory and trend-aware quotes | Adverse selection or weak directional signals |
| Round 5 Circle signals | Followers respond to information already reflected in Circle | Lead–lag relationships change or fail to persist |
| Round 5 pairs | Extreme statistical spreads revert | Relationship breakdown, imperfect quantity hedges, or uneven execution |

## 7. Reading guide to the source code

| Round | Function | What to inspect |
|---|---|---|
| 3 | `run` | Active products and module sequence |
| 3 | `_fair_delta_one` | Wall/microprice/EMA blend and inventory skew |
| 3 | `_passive_inside_mm` | Spread filters, quote sizing, inventory gates, emergency trims |
| 3 | `_zero_tail_bid` | Zero-price distant-voucher orders |
| 4 | `update_mark_scores` | Named-trader signal construction |
| 4 | `compute_hydrogel_fair`, `compute_velvet_fair` | Anchored fair values |
| 4 | `trade_delta1`, `add_passive_quotes_safe` | Underlying execution and inventory-sensitive quotes |
| 4 | `trade_voucher_smile` | IV-curve relative value and directional short-call overlay |
| 4 | `bs_call`, `implied_vol_call`, `fit_parabola` | Black–Scholes, IV inversion, quadratic fitting |
| 5 | `run` | History updates, pair execution, product exclusions |
| 5 | `_market_make` | Inventory skew, momentum, Circle signal, passive quotes |
| 5 | `_trade_pair` | Spread statistics and persistent target states |
| 5 | `_sweep_to_target` | Aggressive execution toward pair targets |

The strategies describe intended behavior under their supplied assumptions. Evaluating realized returns, fill quality, and limit handling requires replay or live execution evidence in addition to reading the source.
