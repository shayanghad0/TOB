# OB-Bot — Tradable Order Blocks Auto-Trader

Automated order-block trading system built for MetaTrader 5, following the *Tradable Order Blocks* methodology by KenneDyne Spot (TFL Academy). Detects high-quality OBs across M1/M5/M15/M30 timeframes and executes limit orders with ATR-based TP/SL.

## What It Does

- Scans multiple timeframes for valid Bullish & Bearish Order Blocks (BuOB / BeOB)
- Scores each OB against **six quality rules** (S/R proximity, Flip Zone, BMS/BOS, IMB ≥ 2× size, opposing OB break, SSR positioning)
- Places **BUY LIMIT / SELL LIMIT** orders only — bounce trades, no stop entries
- Attaches broker-side TP/SL and monitors with a rich live dashboard
- Logs every signal, fill, and exit to `export/trade.json`
- Blacklists losing zones temporarily to avoid repeat failures

## Requirements

- Python 3.10+ · `pip install MetaTrader5 rich numpy`
- Active MT5 terminal logged into a broker

## Quick Start

```bash
# One-off manual trade (entry at market)
python trader.py buy    # or sell

# Persistent OB-scanning bot (runs until Ctrl+C)
python order.py
```

## Files

| File | Purpose |
|------|---------|
| `trader.py` | Market-entry script — opens and manages a position live |
| `order.py` | OB-scan daemon — scores zones, places limits, tracks fills |
| `AGENTS.md` | Full OB methodology (definitions, rules, TFM) |

## Rule Summary

| # | Rule | Weight |
|---|------|--------|
| 1 | OB near Support/Resistance | 30 |
| 2 | OB near Flip Zone | 25 |
| 3 | OB broke BMS/BOS | 20 |
| 4 | IMB ≥ 2× OB size + RR ≥ 1:3 | 20 |
| 5 | OB broke opposing OB | 15 |
| 6 | Correct SSR side (be above / bull below) | 20 |

Min score to trade: **50**. Pick ≥2 confirmations from above.

```python
SYMBOL        = "XAUUSD"   # pair
LOT           = 0.02       # trade size
TP_ATR_MULT   = 2.0        # take-profit = ATR × 2
SL_ATR_MULT   = 1.0        # stop-loss  = ATR × 1  (RR = 1:2)
MAX_PROFIT_USD = 50.00     # emergency P&L cap
MAX_LOSS_USD   = -25.00
```

## Risk Warning

This software connects directly to a live brokerage account via MT5. Trading carries substantial risk of loss. Test on a demo account first. The authors are not responsible for any financial losses.

## License

Private use only. Documentation (AGENTS.md) is derived from KenneDyne Spot / TFL Academy.
