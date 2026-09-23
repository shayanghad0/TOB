# Tradable Order Blocks — Complete Guide
*by KenneDyne Spot | Translated by TFL Academy*

---

## Part 1 — Definitions and Terminology

### 1.1 Order Block (OB)

An **Order Block** is a bearish or bullish candle near a support or resistance level, formed just before price moves strongly in the opposite direction.

- A **bearish candle** is called a **Bearish candle (Bearish)**.
- A **bullish candle** is called a **Bullish candle (Bullish)**.

| Type | Abbreviation | Definition |
|------|-------------|------------|
| **Bullish Order Block** | BuOB | A bearish candle near or at a support level, formed just before price moves up |
| **Bearish Order Block** | BeOB | A bullish candle near or at a resistance level, formed just before price moves down |

> **Note — Entry Placement for Risky Entries:**
> - If the bullish OB has **no wick**: place a Buy Limit order at the **highest point** of the candle; set Stop Loss at the **lowest point**.
> - If the bullish OB **has a wick**: place the Buy Limit at the **candle Open**; set Stop Loss at the **lowest point**.
> - For bearish OBs, everything is reversed.

---

### 1.2 Imbalance (IMB) / Liquidity Void (LV)

**Imbalances** are areas where very few trades took place. For this reason they are also called:
- **Insufficient** areas
- **Liquidity Void (LV)** areas

Wherever there is a shortage of trades in the market, price will return to that area to fill the resting orders waiting there.

> Imbalances are created by **2–3 ERC (Extended Range Candles)** — candles where the body makes up at least 80% of the total candle length.

**Why this happens — the assumption:**

When a Market Maker (MM) decides to push price up from a level, they need enough sell orders to fill their buy orders (that is how they profit). When the MM moves price up with momentum, a liquidity void forms behind price because not enough sell orders existed to match the buys. Price is expected to return to fill this void — this process is called **Mitigation**.

---

### 1.3 Mitigation

**Mitigation** literally means *risk reduction*.

Assume the MM is buying and pushes price up strongly from a level. This move acts as a trap for retail traders who chase the move and set their stop losses below the swing. The MM then pulls price back to collect those stop losses, reducing its own risk before continuing in the original direction.

> **Important:** To determine whether the MM is actually in a risk-reduction phase, the Liquidity Void must have completed certain "missions" before the Order Block can be considered valid.

**Validation of a Bullish OB via a Bullish Liquidity Void — the LV must have:**

1. Broken a bearish (opposing) Order Block, **or**
2. Broken market structure (BMS), **or**
3. Created **Equal Highs (EQH)** — this is especially valid when price is pulling back from a higher-timeframe bullish OB (counter-trend entries or re-entries in trend direction)

---

### 1.4 Flip Zone (FZ)

A **Flip Zone** occurs when a **Resistance (R)** level converts into **Support (S)**, or vice versa.

> **Note:** Before buying at a support that was previously resistance, examine how strongly the resistance was broken. You should identify the Liquidity Void (LV) before marking the Order Block.

---

### 1.5 Significant Support and Resistance (SSR)

An **SSR** is a Flip Zone that has been tested by price multiple times.

- SSR is where the MM returns to **reduce its risk** (cut its losses).
- Because retail traders cluster their stop orders at SSR levels (both breakout traders with Buy Stops above the level, and S/R traders with Sell Limits at the level), the MM sweeps those orders before continuing the original move.

**What happens when price reaches an SSR?**

The MM breaks the SSR, activating the stop orders of both groups of retail traders. Price then reverses and continues the original trend — triggering the stop losses of both groups simultaneously.

---

## Part 2 — What Makes a Tradable Order Block?

Not every Order Block is worth trading. The criteria below define a **high-quality OB**. Before entering the market, your OB must be confirmed by your personal Multi-Timeframe matrix AND meet the rules below.

> It is essential to know that an Order Block in any timeframe is only tradable when confirmed through multi-timeframe analysis (MTF) that aligns with your timeframe matrix (TFM), AND it meets the following rules.

---

### Rule 1 — The OB Must Be Near or At a Support/Resistance Level

The OB should sit close to or directly on a meaningful support or resistance zone. This is the most basic filter — an OB floating in open space with no S/R context has much lower probability.

---

### Rule 2 — The OB Must Be Near or On a Flip Zone

The OB should be located near or on a Flip Zone (FZ). This rule is especially powerful for **reversal entries** (counter-trend pullback entries).

---

### Rule 3 — The OB Must Break Market Structure (BMS or BOS)

The candle that forms the OB must have broken market structure — either a **Break of Market Structure (BMS)** or a **Break of Structure (BOS)**.

This confirms that the OB is not just a random candle but one that actually shifted the direction of price, giving it structural significance.

---

### Rule 4 — Imbalance Must Be at Least 2× the OB Size + RR ≥ 1:3

After the OB forms, the imbalance (LV) created must be **at least 2 times the size of the Order Block**.

Additionally, the **Risk-to-Reward ratio (RR) must be at minimum 1:3**.

> This ensures the trade has enough room to breathe and enough reward potential to justify the risk. If the imbalance is too small relative to the OB, the price likely does not have enough "unfinished business" to drive it back to fill the zone with conviction.

---

### Rule 5 — The OB Must Have Broken an Opposing Order Block

The Order Block being used for the entry must have **broken an Order Block on the opposite side**.

- A **Bullish OB** (for buy entries) must have broken a **Bearish OB** above it.
- A **Bearish OB** (for sell entries) must have broken a **Bullish OB** below it.

This shows the OB had enough force to consume opposing institutional supply or demand, which increases the probability it will hold when price returns.

---

### Rule 6 — Bearish OB Must Be Above SSR; Bullish OB Must Be Below SSR

- A **Bearish Order Block** (for sell entries) must be located **above the SSR level**.
- A **Bullish Order Block** (for buy entries) must be located **below the SSR level**.

This rule ensures the OB is positioned in a structurally logical location relative to the market's key institutional reference level (SSR), increasing the likelihood that the MM will respect that area.

---

## Part 3 — Timeframe Matrix (TFM)

Every valid OB trade must align with your personal **Timeframe Matrix**. A trade on any timeframe is only valid as long as price has not reached the opposing OB on the confirmation timeframe.

| Big Picture Timeframe | Confirmation Timeframe | Entry Timeframe |
|-----------------------|------------------------|-----------------|
| MN (Monthly) | WK (Weekly) | D1 (Daily) |
| WK (Weekly) | D1 (Daily) | H4 (4-Hour) |
| D1 (Daily) | H4 (4-Hour) | H1 (1-Hour) |
| H4 (4-Hour) | H1 (1-Hour) | M15 (15-Min) |
| H1 (1-Hour) | M15 (15-Min) | M5 / M3 / M1 |

**Example using H4-H1-M15 matrix:**

1. Price respects a **4-hour Bullish OB** → identify the opposing **4-hour Bearish OB** on the other side. That zone defines your trading range.
2. Inside this range, look for **1-hour Bullish OBs** to buy from.
3. Use a **15-minute OB** as confirmation for a sniper entry.
4. This approach is only valid **until price reaches the opposing 4-hour Bearish OB**.

---

## Part 4 — Summary of Trade Setup Rules

| # | Rule | Notes |
|---|------|-------|
| 1 | OB near or at Support/Resistance | Structural context required |
| 2 | OB near or on a Flip Zone | Especially important for reversal entries |
| 3 | OB broke market structure (BMS or BOS) | Confirms structural validity |
| 4 | IMB ≥ 2× OB size + RR ≥ 1:3 | Ensures adequate target space |
| 5 | OB broke an opposing OB | Confirms institutional force |
| 6 | Bearish OB above SSR / Bullish OB below SSR | Correct structural positioning |

---

## Part 5 — Step-by-Step Trade Process

### Step 1 — Choose Your Timeframe Matrix
Select the matrix that suits your trading style, e.g. **H4-H1-M15**.

### Step 2 — Choose Your Confirmations
Select at least **2 of the 6 rules** as your primary confirmations, e.g. **LV + BMS + 3RR**.

### Step 3 — Wait for the Setup
Do not force entries. Wait for all your selected confirmations to align before entering.

---

## Part 6 — Key Concepts Reference Table

| Concept | Abbreviation | Meaning |
|---------|-------------|---------|
| Order Block | OB | The candle before a strong impulsive move |
| Bullish Order Block | BuOB | Bearish candle before a bullish move; buy zone |
| Bearish Order Block | BeOB | Bullish candle before a bearish move; sell zone |
| Imbalance / Liquidity Void | IMB / LV | Price area with insufficient trades; price tends to return |
| Mitigation | — | MM returning to fill imbalance / reduce risk |
| Flip Zone | FZ | Former resistance becomes support, or vice versa |
| Significant Support & Resistance | SSR | A tested Flip Zone; key MM reference level |
| Break of Structure | BOS | Price breaks a prior swing high/low in trend direction |
| Break of Market Structure | BMS | Structural break signalling a potential reversal |
| Equal Highs | EQH | Two or more highs at the same price; liquidity target |
| Risk-to-Reward | RR | Ratio of potential loss to potential profit (min 1:3) |
| Extended Range Candle | ERC | Candle with body ≥ 80% of total length; creates IMB |
| Timeframe Matrix | TFM | Three-level timeframe framework for MTF analysis |
| Market Maker | MM | Large institutional participant that moves price |
| Stop Loss | SL | Exit level if trade moves against you |
| Take Profit | TP | Target exit level |

---

## Part 7 — Final Thoughts

> *"You can build your own set of rules and determine them before entering the market."*

With 6 characteristics described above, choose **2 as your primary confirmations** for a valid Order Block. The right combination depends on you — backtest and practice until you find the approach that fits your style.

Key reminders:
- **Always use Multi-Timeframe analysis** — an OB is only valid when confirmed on a higher timeframe.
- **Stick to your TFM** — trades are only valid until price reaches the opposing OB on the confirmation timeframe.
- **Imbalance size matters** — small imbalances mean the market has little reason to return with force.
- **SSR is your anchor** — Bearish OBs above, Bullish OBs below.
- **Patience wins** — wait for setups to form fully; do not chase price.