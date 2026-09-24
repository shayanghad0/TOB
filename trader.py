"""
ob_bot.py — Order Block Bot v1
===============================

Trading Logic (from Tradable_Order_Blocks):
────────────────────────────────────────────
Detects valid Order Blocks across M1/M5/M15/M30 timeframes and trades them
using the six OB quality rules:

  Rule 1 — OB near a Support/Resistance level
  Rule 2 — OB near or on a Flip Zone (FZ)
  Rule 3 — OB broke Market Structure (BMS or BOS)
  Rule 4 — IMB after OB is ≥ 2× OB size + RR ≥ 1:3
  Rule 5 — OB broke an opposing Order Block
  Rule 6 — Bearish OB above SSR / Bullish OB below SSR

Execution (from order.py):
────────────────────────────
  - BUY LIMIT / SELL LIMIT only (bounce trades — no STOP orders)
  - ATR-based TP/SL with 1:2 RR (M30 ATR)
  - Broker-side TP/SL attached to every pending order
  - Emergency P&L cap as safety net
  - Position monitored with rich live dashboard

Database (trade.json — same schema as trader.py):
───────────────────────────────────────────────────
  - Every signal, order, fill, exit is recorded
  - Zone blacklist prevents re-entering losing levels
  - HTML report exported on Ctrl+C
"""

import json, os, sys, time, uuid
from collections import deque
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_UP

import numpy as np
import MetaTrader5 as mt5
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.align import Align
from rich import box

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────
SYMBOL           = "XAUUSD"
LOT              = 0.02
DEVIATION        = 20
MAGIC            = 888001

# TP/SL — ATR-based (M30 ATR, 1:2 RR — Rule 4)
TP_ATR_MULT      = 2.0
SL_ATR_MULT      = 1.0
ATR_PERIOD       = 14

# Emergency caps — safety net if broker TP/SL misses
MAX_PROFIT_USD   =  50.00
MAX_LOSS_USD     = -25.00

ORDER_EXPIRY_SEC = 3600         # cancel pending after 1 h
COOLDOWN_CANDLES = 5            # M15 bars to wait after a trade exits
LIMIT_FILL_BUFFER = 0.50        # $ buffer toward market price for fill reliability

# ── OB Detection ─────────────────────────────────────────────────────────────
OB_LOOKBACK      = 300          # closed bars per timeframe to scan
OB_BODY_RATIO    = 0.30         # was 0.60 — OB candle just needs a real body; 30% is enough
OB_SWING_RADIUS  = 3            # was 5 — relax swing confirmation

# ── S&R / SSR Detection ──────────────────────────────────────────────────────
SR_LOOKBACK      = 300
SR_SWING_RADIUS  = 3            # was 5 — strict swing radius misses many valid swings on XAUUSD
SR_ZONE_MERGE    = 0.30         # was 0.10% — merge levels that are within 0.30% of each other
MIN_TOUCHES      = 2            # was 3 — require only 2 touches so SSR list is not empty
SSR_PROXIMITY    = 2.00         # was 0.50% — widened to match zone proximity

# ── IMB (Imbalance) Detection ─────────────────────────────────────────────────
IMB_MIN_RATIO    = 0.5          # was 2.0 — next_l/ob_low gap is usually small; 0.5× is realistic

# ── Zone Proximity ────────────────────────────────────────────────────────────
ZONE_PROXIMITY   = 2.00         # was 0.50% — on XAUUSD ~3300 that is ±$16; widened to ±$66
MIN_ZONE_PROX    = 0.05         # % — skip if price is already sitting on the OB
BMS_LOOKBACK     = 50           # bars to check for BMS/BOS after the OB

# ── Filters ───────────────────────────────────────────────────────────────────
RSI_PERIOD       = 14
RSI_BUY_MIN      = 30           # block only deeply oversold; XAUUSD bull RSI stays 50–70
RSI_BUY_MAX      = 75           # was 62 — blocked most bull-trend entries
RSI_SELL_MIN     = 25           # was 38
RSI_SELL_MAX     = 70           # was 80

EMA_FAST         = 9
EMA_SLOW         = 21
EMA_TREND        = 50          # was 200 — 200-bar EMA on M30 needs 100 h of data; 50 is reliable
VOL_MIN_RATIO    = 0.20        # was 0.35 — XAUUSD tick-volume can be low; relax

# ── Zone Blacklist ────────────────────────────────────────────────────────────
ZONE_BLACKLIST_PCT   = 0.10     # was 0.20% — tighter so nearby valid OBs aren't killed
ZONE_BLACKLIST_HOURS = 4        # was 6 h

# ── OB Scoring Weights ────────────────────────────────────────────────────────
# Each rule that the OB satisfies adds points — best scoring OB wins
RULE_WEIGHTS = {
    "near_sr":       30,    # Rule 1 — near S/R
    "near_fz":       25,    # Rule 2 — near Flip Zone
    "broke_bms":     20,    # Rule 3 — broke market structure
    "imb_2x":        20,    # Rule 4 — IMB ≥ 2× OB
    "broke_opp_ob":  15,    # Rule 5 — broke opposing OB
    "ssr_position":  20,    # Rule 6 — correct side of SSR
}
MIN_SCORE        = 20           # was 50 — just Rule 1 (near S/R, weight=30) is enough to trade

TF_WEIGHT        = {"M1": 1, "M5": 2, "M15": 4, "M30": 6}
TIMEFRAMES       = {
    "M1":  mt5.TIMEFRAME_M1,
    "M5":  mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
}

CHECK_INTERVAL   = 1
DEAL_RETRY_N     = 8
DEAL_RETRY_SLEEP = 0.5

EXPORT_DIR      = "export"
TRADE_DB_PATH   = os.path.join(EXPORT_DIR, "trade.json")
OHLCV_DIR       = os.path.join(EXPORT_DIR, "ohlcv")
os.makedirs(OHLCV_DIR, exist_ok=True)
os.makedirs(EXPORT_DIR, exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# CONSOLE / LOGGING
# ─────────────────────────────────────────────────────────────────────────────
console = Console()
events  = deque(maxlen=14)

def log(msg: str, style: str = "white"):
    ts = datetime.now().strftime("%H:%M:%S")
    events.append((ts, msg, style))
    console.print(f"[dim]{ts}[/]  [{style}]{msg}[/{style}]")


# ─────────────────────────────────────────────────────────────────────────────
# INDICATORS
# ─────────────────────────────────────────────────────────────────────────────
def _ema(vals: list, p: int) -> list:
    k = 2 / (p + 1)
    out = [vals[0]]
    for v in vals[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def _rsi(closes: list, p: int = RSI_PERIOD) -> float:
    if len(closes) < p + 2:
        return 50.0
    g = [max(closes[i] - closes[i-1], 0.0) for i in range(1, len(closes))]
    l = [max(closes[i-1] - closes[i], 0.0) for i in range(1, len(closes))]
    ag = sum(g[:p]) / p
    al = sum(l[:p]) / p
    for i in range(p, len(g)):
        ag = (ag * (p-1) + g[i]) / p
        al = (al * (p-1) + l[i]) / p
    return 100.0 if al == 0 else 100 - 100 / (1 + ag / al)


def _atr(h: np.ndarray, l: np.ndarray, c: np.ndarray, p: int = ATR_PERIOD) -> float:
    trs = [max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))
           for i in range(1, len(h))]
    if len(trs) < p:
        return float(np.mean(trs)) if trs else 1.0
    a = sum(trs[:p]) / p
    for t in trs[p:]:
        a = (a * (p-1) + t) / p
    return max(a, 0.01)


# ─────────────────────────────────────────────────────────────────────────────
# TRADE DATABASE  (same schema as trader.py)
# ─────────────────────────────────────────────────────────────────────────────
def _load_db() -> list:
    if not os.path.exists(TRADE_DB_PATH):
        return []
    try:
        with open(TRADE_DB_PATH) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save_db(records: list):
    tmp = TRADE_DB_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(records, f, indent=2, default=str)
    os.replace(tmp, TRADE_DB_PATH)


def db_create_trade(signal: dict) -> str:
    trade_id = str(uuid.uuid4())[:8]
    records  = _load_db()
    records.append({
        "trade_id":           trade_id,
        "symbol":             SYMBOL,
        "lot":                LOT,
        "direction":          signal["direction"],
        "zone_price":         round(signal["ob_price"], 5),
        "zone_type":          signal["ob_type"],        # "bullish_ob" / "bearish_ob"
        "zone_tfs":           signal["tfs"],
        "zone_score":         signal["score"],
        "zone_touches":       signal.get("sr_touches", 0),
        # OB-specific fields
        "ob_high":            signal.get("ob_high"),
        "ob_low":             signal.get("ob_low"),
        "ob_body_ratio":      signal.get("ob_body_ratio"),
        "imb_size":           signal.get("imb_size"),
        "imb_ratio":          signal.get("imb_ratio"),
        "rules_passed":       signal.get("rules_passed", []),
        # Filters
        "signal_rsi":         signal.get("rsi"),
        "signal_trend_m30":   signal.get("trend_m30"),
        "signal_trend_m15":   signal.get("trend_m15"),
        "signal_atr_m30":     signal.get("atr_m30"),
        # Order / position fields (filled in later)
        "order_ticket":       None,
        "order_placed_at":    None,
        "order_type":         None,
        "limit_price":        None,
        "tp_price":           None,
        "sl_price":           None,
        "position_ticket":    None,
        "entry_price":        None,
        "entry_time":         None,
        "exit_price":         None,
        "exit_time":          None,
        "exit_reason":        None,
        "pnl":                None,
        "ohlcv_file":         f"ohlcv/{trade_id}.json",
        "created_at":         datetime.now(timezone.utc).isoformat(),
        "status":             "pending",
    })
    _save_db(records)
    log(f"[DB] {trade_id} created  {signal['direction'].upper()} OB @ {signal['ob_price']:.2f}  "
        f"score={signal['score']}  rules={signal.get('rules_passed')}", "dim")
    return trade_id


def db_update_trade(trade_id: str, **kwargs):
    records = _load_db()
    for r in records:
        if r["trade_id"] == trade_id:
            r.update(kwargs)
            break
    _save_db(records)


def db_stats() -> dict:
    records = _load_db()
    closed  = [r for r in records if r.get("pnl") is not None]
    wins    = [r for r in closed if r["pnl"] > 0]
    losses  = [r for r in closed if r["pnl"] <= 0]
    gross   = sum(r["pnl"] for r in closed)
    wr      = len(wins) / len(closed) * 100 if closed else 0.0
    return {"total": len(records), "closed": len(closed),
            "wins": len(wins), "losses": len(losses),
            "gross": gross, "wr": wr}


def get_blacklisted_zones() -> list:
    records   = _load_db()
    now_ts    = time.time()
    cutoff_s  = ZONE_BLACKLIST_HOURS * 3600
    BAD_REASONS = {"sl", "sl_emergency", "cancelled", "order_failed",
                   "no_fill", "expired_1h", "external"}
    LIVE_STATUS = {"pending", "waiting_fill", "open"}
    blacklisted = []
    for r in records:
        if r.get("zone_price") is None:
            continue
        status = r.get("status", "")
        reason = r.get("exit_reason") or ""
        if status in LIVE_STATUS:
            blacklisted.append(float(r["zone_price"]))
            continue
        if reason not in BAD_REASONS:
            continue
        ref_time_str = r.get("exit_time") or r.get("created_at") or ""
        try:
            ref_ts = datetime.fromisoformat(ref_time_str).timestamp()
        except (ValueError, TypeError):
            continue
        if now_ts - ref_ts <= cutoff_s:
            blacklisted.append(float(r["zone_price"]))
    return blacklisted


# ─────────────────────────────────────────────────────────────────────────────
# MT5 HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def mt5_connect():
    if not mt5.initialize():
        console.print("[bold red]✗ MT5 initialize() failed[/]", mt5.last_error())
        sys.exit(1)
    log("MT5 connected", "bold green")


def get_symbol_info():
    info = mt5.symbol_info(SYMBOL)
    if info is None:
        log(f"✗ symbol_info({SYMBOL}) failed", "red")
        return None
    if not info.visible:
        mt5.symbol_select(SYMBOL, True)
        info = mt5.symbol_info(SYMBOL)
    return info


def get_filling_mode(si):
    m = si.filling_mode
    if m & 1: return mt5.ORDER_FILLING_FOK
    if m & 2: return mt5.ORDER_FILLING_IOC
    return mt5.ORDER_FILLING_RETURN


def fetch_closed_bars(tf_value: int, count: int = OB_LOOKBACK):
    """Fetch count+1 bars, drop the last open bar — returns closed bars only."""
    rates = mt5.copy_rates_from_pos(SYMBOL, tf_value, 0, count + 1)
    if rates is None or len(rates) < 2:
        return None
    rates = rates[:-1]  # drop open bar
    return (rates["open"].astype(float),  rates["high"].astype(float),
            rates["low"].astype(float),   rates["close"].astype(float),
            rates["tick_volume"].astype(float),
            rates["time"].astype(int))


# ─────────────────────────────────────────────────────────────────────────────
# TREND DETECTION
# ─────────────────────────────────────────────────────────────────────────────
def get_trend(tf_value: int) -> str:
    need = max(OB_LOOKBACK, EMA_TREND + 10)
    data = fetch_closed_bars(tf_value, need)
    if data is None:
        return "mixed"
    _, _, _, c, _, _ = data
    closes = list(c)
    # Need at least EMA_SLOW bars for meaningful signals
    if len(closes) < EMA_SLOW + 5:
        return "mixed"
    e_fast  = _ema(closes, EMA_FAST)
    e_slow  = _ema(closes, EMA_SLOW)
    f, s = e_fast[-1], e_slow[-1]
    # If we have enough bars for EMA_TREND use it as confirmation
    if len(closes) >= EMA_TREND + 5:
        e_trend = _ema(closes, EMA_TREND)
        t = e_trend[-1]
        if f > s > t: return "bull"
        if f < s < t: return "bear"
    # Short-term bias from fast/slow only
    if f > s:  return "bull"
    if f < s:  return "bear"
    return "mixed"


# ─────────────────────────────────────────────────────────────────────────────
# S&R / SSR DETECTION
# ─────────────────────────────────────────────────────────────────────────────
def _find_swing_highs_lows(h: np.ndarray, l: np.ndarray, r: int = SR_SWING_RADIUS):
    n = len(h)
    sh, sl = [], []
    for i in range(r, n - r):
        if all(h[i] > h[i-j] for j in range(1, r+1)) and \
           all(h[i] > h[i+j] for j in range(1, r+1)):
            sh.append(h[i])
        if all(l[i] < l[i-j] for j in range(1, r+1)) and \
           all(l[i] < l[i+j] for j in range(1, r+1)):
            sl.append(l[i])
    return sh, sl


def _merge_levels(levels: list) -> list:
    if not levels: return []
    levels = sorted(levels)
    m = [levels[0]]
    for lv in levels[1:]:
        if (lv - m[-1]) / m[-1] * 100 <= SR_ZONE_MERGE:
            m[-1] = (m[-1] + lv) / 2
        else:
            m.append(lv)
    return m


def _count_touches(level: float, h: np.ndarray, l: np.ndarray) -> int:
    tol = level * 0.15 / 100   # was 0.04% — on XAUUSD ~3300 that was only ±$1.3; now ±$5
    touches = 0
    for i in range(len(h)):
        if abs(h[i] - level) <= tol or abs(l[i] - level) <= tol:
            touches += 1
    return touches


def get_sr_levels(tf_value: int = mt5.TIMEFRAME_M30) -> dict:
    """
    Returns dict with:
      'supports'    — list of support price levels
      'resistances' — list of resistance price levels
      'ssrs'        — levels with ≥ MIN_TOUCHES (flip zones tested multiple times)
    """
    data = fetch_closed_bars(tf_value, SR_LOOKBACK)
    if data is None:
        return {"supports": [], "resistances": [], "ssrs": []}
    _, h, l, _, _, _ = data
    swing_h, swing_l = _find_swing_highs_lows(h, l, SR_SWING_RADIUS)

    supports    = _merge_levels(swing_l)
    resistances = _merge_levels(swing_h)

    # SSRs = levels with enough touches to be considered "significant"
    ssrs = []
    for lv in supports + resistances:
        touches = _count_touches(lv, h, l)
        if touches >= MIN_TOUCHES:
            ssrs.append(lv)

    return {"supports": supports, "resistances": resistances,
            "ssrs": _merge_levels(ssrs)}


def nearest_level(price: float, levels: list) -> float | None:
    if not levels:
        return None
    return min(levels, key=lambda lv: abs(lv - price))


def is_near_level(price: float, levels: list, pct: float = SSR_PROXIMITY) -> tuple:
    """Returns (True/False, nearest_level, distance_pct)."""
    n = nearest_level(price, levels)
    if n is None:
        return False, None, None
    dist_pct = abs(price - n) / price * 100
    return dist_pct <= pct, n, dist_pct


# ─────────────────────────────────────────────────────────────────────────────
# ORDER BLOCK DETECTION
# ─────────────────────────────────────────────────────────────────────────────
def _is_erc(o: float, h: float, l: float, c: float,
            body_ratio: float = OB_BODY_RATIO) -> bool:
    """Extended Range Candle: body ≥ body_ratio of total range."""
    rng  = h - l
    body = abs(c - o)
    return rng > 0 and body / rng >= body_ratio


def detect_order_blocks(tf_name: str, tf_value: int,
                        direction: str) -> list:
    """
    Detect Order Blocks for the given direction.

    Bullish OB (BuOB): a BEARISH candle (close < open) that precedes
      a strong bullish move (next ERC is bullish) → buy zone.

    Bearish OB (BeOB): a BULLISH candle (close > open) that precedes
      a strong bearish move (next ERC is bearish) → sell zone.

    Returns list of OB dicts sorted by recency (most recent first).
    """
    data = fetch_closed_bars(tf_value, OB_LOOKBACK)
    if data is None:
        return []

    o_arr, h_arr, l_arr, c_arr, v_arr, t_arr = data
    n   = len(o_arr)
    obs = []

    for i in range(n - 2):
        o, h, l, c = o_arr[i], h_arr[i], l_arr[i], c_arr[i]
        no, nh, nl, nc = o_arr[i+1], h_arr[i+1], l_arr[i+1], c_arr[i+1]

        if direction == "buy":
            # OB candle: bearish (close < open)
            ob_is_bearish = c < o
            # Next candle: bullish ERC (strong move up)
            next_is_bull_erc = nc > no and _is_erc(no, nh, nl, nc)
            if not ob_is_bearish or not next_is_bull_erc:
                continue

            ob_type  = "bullish_ob"     # BuOB — we BUY when price returns here
            ob_price = l                # entry zone = low of the bearish OB candle
            ob_top   = h
            ob_bot   = l
        else:
            # OB candle: bullish (close > open)
            ob_is_bullish = c > o
            # Next candle: bearish ERC (strong move down)
            next_is_bear_erc = nc < no and _is_erc(no, nh, nl, nc)
            if not ob_is_bullish or not next_is_bear_erc:
                continue

            ob_type  = "bearish_ob"     # BeOB — we SELL when price returns here
            ob_price = h                # entry zone = high of the bullish OB candle
            ob_top   = h
            ob_bot   = l

        ob_size       = abs(o - c)      # body size
        ob_body_ratio = ob_size / (h - l) if (h - l) > 0 else 0.0
        bars_ago      = n - 1 - i

        obs.append({
            "tf":           tf_name,
            "ob_type":      ob_type,
            "ob_price":     ob_price,   # zone entry reference price
            "ob_top":       ob_top,
            "ob_bot":       ob_bot,
            "ob_high":      h,
            "ob_low":       l,
            "ob_open":      o,
            "ob_close":     c,
            "ob_size":      ob_size,
            "ob_body_ratio":round(ob_body_ratio, 3),
            "ob_bar_index": i,
            "bars_ago":     bars_ago,
            "timestamp":    int(t_arr[i]),
            # Imbalance = move created after the OB
            "next_o":       no,
            "next_h":       nh,
            "next_l":       nl,
            "next_c":       nc,
        })

    # Most recent first
    obs.sort(key=lambda x: x["bars_ago"])
    return obs


def compute_imbalance(ob: dict) -> float:
    """
    IMB size = gap between the OB candle's far edge and the next candle's near edge.

    Bullish OB:  gap between OB low  and next candle's low  (space price skipped upward)
    Bearish OB:  gap between OB high and next candle's high (space price skipped downward)
    """
    if ob["ob_type"] == "bullish_ob":
        # Price jumped up: gap = next_low - ob_low  (if positive, there's a void)
        imb = ob["next_l"] - ob["ob_low"]
    else:
        # Price jumped down: gap = ob_high - next_high
        imb = ob["ob_high"] - ob["next_h"]
    return max(imb, 0.0)


def check_bms_after_ob(ob: dict, tf_value: int) -> bool:
    """
    Rule 3: Did the candles AFTER this OB break market structure?
    BMS = the move after the OB broke the previous swing high (for bull) or low (for bear).

    Simple proxy: the ERC after the OB moved enough to create a new swing
    (we check if the move was ≥ 1 ATR14 in the right direction).
    """
    data = fetch_closed_bars(tf_value, OB_LOOKBACK)
    if data is None:
        return False
    _, h_arr, l_arr, c_arr, _, _ = data

    idx = ob["ob_bar_index"]
    if idx + 2 >= len(c_arr):
        return False

    # Look at the post-OB window
    post_h = h_arr[idx+1:]
    post_l = l_arr[idx+1:]
    post_c = c_arr[idx+1:]

    if len(post_c) < 3:
        return False

    atr = _atr(post_h[:20] if len(post_h) >= 20 else post_h,
               post_l[:20] if len(post_l) >= 20 else post_l,
               post_c[:20] if len(post_c) >= 20 else post_c)

    if ob["ob_type"] == "bullish_ob":
        # Bull: did price go up by ≥ 1 ATR from the OB?
        swing_high_after = np.max(post_h[:min(BMS_LOOKBACK, len(post_h))])
        return swing_high_after - ob["ob_high"] >= atr
    else:
        # Bear: did price go down by ≥ 1 ATR from the OB?
        swing_low_after = np.min(post_l[:min(BMS_LOOKBACK, len(post_l))])
        return ob["ob_low"] - swing_low_after >= atr


def check_opposing_ob_broken(ob: dict, tf_value: int) -> bool:
    """
    Rule 5: Did the move after this OB break an opposing OB?
    Bull OB → did the post-OB rally break through a prior bearish OB above?
    Bear OB → did the post-OB drop break through a prior bullish OB below?
    """
    data = fetch_closed_bars(tf_value, OB_LOOKBACK)
    if data is None:
        return False
    _, h_arr, l_arr, _, _, _ = data

    idx = ob["ob_bar_index"]
    if idx < 5:
        return False

    # Look at candles BEFORE the OB for opposing zones
    pre_h = h_arr[:idx]
    pre_l = l_arr[:idx]

    if ob["ob_type"] == "bullish_ob":
        # Look for a bearish OB above that was broken by the post-OB high
        post_max = np.max(h_arr[idx+1:idx+1+BMS_LOOKBACK]) if idx+1 < len(h_arr) else ob["ob_high"]
        # A prior resistance (swing high) that was penetrated
        prior_highs = [pre_h[i] for i in range(len(pre_h)-1, max(0, len(pre_h)-50), -1)
                       if pre_h[i] > ob["ob_high"]]
        if not prior_highs:
            return False
        nearest_res = min(prior_highs)
        return post_max > nearest_res
    else:
        # Look for a bullish OB below that was broken by the post-OB low
        post_min = np.min(l_arr[idx+1:idx+1+BMS_LOOKBACK]) if idx+1 < len(l_arr) else ob["ob_low"]
        prior_lows = [pre_l[i] for i in range(len(pre_l)-1, max(0, len(pre_l)-50), -1)
                      if pre_l[i] < ob["ob_low"]]
        if not prior_lows:
            return False
        nearest_sup = max(prior_lows)
        return post_min < nearest_sup


# ─────────────────────────────────────────────────────────────────────────────
# OB SCORING — Six Rules
# ─────────────────────────────────────────────────────────────────────────────
def score_ob(ob: dict, sr_data: dict, mid: float,
             atr_val: float, tf_value: int) -> tuple:
    """
    Scores an Order Block against the 6 rules.
    Returns (score, rules_passed, extra_data).
    """
    score        = 0
    rules_passed = []
    extra        = {}

    ob_price = ob["ob_price"]
    ob_size  = ob["ob_size"]

    # ── Rule 1 — Near S/R ────────────────────────────────────────────────────
    all_levels = sr_data["supports"] + sr_data["resistances"]
    near_sr, sr_level, sr_dist = is_near_level(ob_price, all_levels)
    if near_sr:
        score += RULE_WEIGHTS["near_sr"]
        rules_passed.append("near_sr")
        extra["sr_level"]   = sr_level
        extra["sr_dist_pct"]= round(sr_dist, 3)

    # ── Rule 2 — Near Flip Zone ───────────────────────────────────────────────
    # A flip zone is where the level type has changed: a prior resistance
    # that became support or vice versa. We approximate by checking if the
    # OB sits on a level that appears in BOTH supports and resistances lists.
    flip_zones = []
    tol = mid * 0.002  # 0.2% tolerance
    for s in sr_data["supports"]:
        for r in sr_data["resistances"]:
            if abs(s - r) <= tol:
                flip_zones.append((s + r) / 2)
    near_fz, fz_level, fz_dist = is_near_level(ob_price, flip_zones, SSR_PROXIMITY)
    if near_fz:
        score += RULE_WEIGHTS["near_fz"]
        rules_passed.append("near_fz")
        extra["fz_level"] = fz_level

    # ── Rule 3 — Broke Market Structure ──────────────────────────────────────
    if check_bms_after_ob(ob, tf_value):
        score += RULE_WEIGHTS["broke_bms"]
        rules_passed.append("broke_bms")

    # ── Rule 4 — IMB ≥ 2× OB + RR ≥ 1:3 ─────────────────────────────────────
    imb_size  = compute_imbalance(ob)
    imb_ratio = imb_size / ob_size if ob_size > 0 else 0.0
    extra["imb_size"]  = round(imb_size, 5)
    extra["imb_ratio"] = round(imb_ratio, 2)

    # RR check using ATR-based TP/SL
    tp_dist = atr_val * TP_ATR_MULT
    sl_dist = atr_val * SL_ATR_MULT
    rr = tp_dist / sl_dist if sl_dist > 0 else 0.0
    extra["rr"] = round(rr, 2)

    min_rr = TP_ATR_MULT / SL_ATR_MULT   # = 2.0 with current config
    if imb_ratio >= IMB_MIN_RATIO and rr >= min_rr:
        score += RULE_WEIGHTS["imb_2x"]
        rules_passed.append("imb_2x")
    elif imb_ratio >= 0.3:                # partial credit even with small IMB
        score += RULE_WEIGHTS["imb_2x"] // 2
        rules_passed.append("imb_2x_partial")

    # ── Rule 5 — Broke Opposing OB ───────────────────────────────────────────
    if check_opposing_ob_broken(ob, tf_value):
        score += RULE_WEIGHTS["broke_opp_ob"]
        rules_passed.append("broke_opp_ob")

    # ── Rule 6 — Correct Side of SSR ─────────────────────────────────────────
    ssrs = sr_data["ssrs"]
    near_ssr, ssr_level, ssr_dist = is_near_level(mid, ssrs, SSR_PROXIMITY * 2)
    if near_ssr and ssr_level is not None:
        if ob["ob_type"] == "bullish_ob" and ob_price < ssr_level:
            # Bullish OB below SSR ✓
            score += RULE_WEIGHTS["ssr_position"]
            rules_passed.append("ssr_position")
            extra["ssr_level"] = ssr_level
        elif ob["ob_type"] == "bearish_ob" and ob_price > ssr_level:
            # Bearish OB above SSR ✓
            score += RULE_WEIGHTS["ssr_position"]
            rules_passed.append("ssr_position")
            extra["ssr_level"] = ssr_level

    return score, rules_passed, extra


# ─────────────────────────────────────────────────────────────────────────────
# CONFIRMATION FILTERS
# ─────────────────────────────────────────────────────────────────────────────
def check_filters(direction: str, ob_price: float) -> dict | None:
    data = fetch_closed_bars(mt5.TIMEFRAME_M15, 250)
    if data is None:
        log("Filter FAIL: no M15 data", "dim red")
        return None

    o, h, l, c, v, _ = data
    closes = list(c)
    vols   = list(v)
    opens  = list(o)
    highs  = list(h)
    lows   = list(l)

    # RSI filter
    rsi_val = _rsi(closes[-52:])
    if direction == "buy":
        rsi_lo, rsi_hi = RSI_BUY_MIN, RSI_BUY_MAX
    else:
        rsi_lo, rsi_hi = RSI_SELL_MIN, RSI_SELL_MAX
    if not (rsi_lo <= rsi_val <= rsi_hi):
        log(f"Filter FAIL: RSI={rsi_val:.1f} not in [{rsi_lo},{rsi_hi}] for {direction.upper()}", "dim red")
        return None

    # Volume filter (use bar[-2] — last confirmed closed bar before current)
    if len(vols) < 22:
        log("Filter FAIL: not enough volume history", "dim red")
        return None
    avg_v  = float(np.mean(vols[-22:-2]))
    last_v = float(vols[-2])
    if avg_v > 0 and last_v / avg_v < VOL_MIN_RATIO:
        log(f"Filter FAIL: vol {last_v:.0f} = {last_v/avg_v:.2f}x avg (need ≥{VOL_MIN_RATIO}x)", "dim red")
        return None

    # ATR from M30
    data30 = fetch_closed_bars(mt5.TIMEFRAME_M30, 50)
    if data30 is None:
        log("Filter FAIL: no M30 data for ATR", "dim red")
        return None
    _, h30, l30, c30, _, _ = data30
    atr_val = _atr(h30, l30, c30, ATR_PERIOD)

    log(f"Filters OK ✓  RSI={rsi_val:.1f}  vol={last_v/avg_v:.2f}x  ATR(M30)={atr_val:.2f}", "dim green")
    return {"rsi": round(rsi_val, 1), "atr_m30": round(atr_val, 2),
            "vol_ratio": round(last_v / avg_v, 2)}


# ─────────────────────────────────────────────────────────────────────────────
# SIGNAL ENGINE — finds the best scoring OB
# ─────────────────────────────────────────────────────────────────────────────
def get_signal() -> dict | None:
    """
    1. Determine direction from M30 trend (M15 must not oppose).
    2. Scan all TFs for OBs matching the direction.
    3. Score each OB against the 6 rules.
    4. Return the best-scoring OB above MIN_SCORE that passes all filters.
    """
    trend_m30 = get_trend(mt5.TIMEFRAME_M30)
    trend_m15 = get_trend(mt5.TIMEFRAME_M15)
    log(f"Trend → M30={trend_m30}  M15={trend_m15}", "dim")

    if trend_m30 == "mixed":
        log("No signal: M30 trend mixed", "dim")
        return None
    if trend_m15 != "mixed" and trend_m15 != trend_m30:
        log(f"No signal: M15 ({trend_m15}) opposes M30 ({trend_m30})", "dim")
        return None

    direction = "buy" if trend_m30 == "bull" else "sell"

    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        return None
    mid = (tick.ask + tick.bid) / 2

    # Get M30 ATR early for scoring
    data30 = fetch_closed_bars(mt5.TIMEFRAME_M30, 50)
    if data30 is None:
        return None
    _, h30, l30, c30, _, _ = data30
    atr_val = _atr(h30, l30, c30, ATR_PERIOD)

    # S&R levels (M30 for reliability)
    sr_data = get_sr_levels(mt5.TIMEFRAME_M30)

    # Blacklisted zones
    blacklisted = get_blacklisted_zones()
    if blacklisted:
        log(f"Blacklisted zones: {[round(b, 2) for b in blacklisted]}", "dim yellow")

    # Scan all TFs for OBs
    all_obs   = []
    for tf_name, tf_val in TIMEFRAMES.items():
        obs = detect_order_blocks(tf_name, tf_val, direction)
        log(f"  [{tf_name}] found {len(obs)} raw {direction} OBs", "dim")
        passed_prox = 0
        for ob in obs:
            ob_price  = ob["ob_price"]
            # Proximity = distance from mid to the NEAREST edge of the OB zone
            nearest_edge = ob["ob_top"] if direction == "buy" else ob["ob_bot"]
            prox_pct  = abs(mid - nearest_edge) / mid * 100

            # Proximity gate — OB must be near price but not already hit
            if prox_pct > ZONE_PROXIMITY:
                continue   # too far — silent skip
            if prox_pct < MIN_ZONE_PROX:
                log(f"    [{tf_name}] OB {ob_price:.2f} skip: price already on zone ({prox_pct:.3f}%)", "dim")
                continue

            # Direction gate — zone must be on the correct side of current price.
            if direction == "buy"  and ob["ob_top"] >= mid:
                log(f"    [{tf_name}] OB {ob_price:.2f} skip: zone top {ob['ob_top']:.2f} >= mid {mid:.2f}", "dim")
                continue
            if direction == "sell" and ob["ob_bot"] <= mid:
                log(f"    [{tf_name}] OB {ob_price:.2f} skip: zone bot {ob['ob_bot']:.2f} <= mid {mid:.2f}", "dim")
                continue

            # Blacklist check
            if any(abs(ob_price - bl) / mid * 100 <= ZONE_BLACKLIST_PCT
                   for bl in blacklisted):
                log(f"    [{tf_name}] OB {ob_price:.2f} blacklisted", "dim yellow")
                continue

            score, rules_passed, extra = score_ob(ob, sr_data, mid, atr_val, tf_val)
            ob["score"]        = score
            ob["rules_passed"] = rules_passed
            ob["extra"]        = extra
            ob["tf_weight"]    = TF_WEIGHT.get(tf_name, 1)
            all_obs.append(ob)
            passed_prox += 1
            log(f"    [{tf_name}] OB {ob_price:.2f} → score={score}  rules={rules_passed}  prox={prox_pct:.3f}%", "dim cyan")
        if passed_prox == 0:
            log(f"  [{tf_name}] no OBs passed proximity/direction gate", "dim")

    if not all_obs:
        band_lo = mid * (1 - ZONE_PROXIMITY / 100)
        band_hi = mid * (1 + ZONE_PROXIMITY / 100)
        log(f"No valid {direction} OBs in band {band_lo:.2f}–{band_hi:.2f} "
            f"(mid={mid:.2f}  ±{ZONE_PROXIMITY}%)", "dim red")
        return None

    # Pick best OB by score, then by TF weight (higher TF preferred), then recency
    all_obs.sort(key=lambda x: (x["score"], x["tf_weight"], -x["bars_ago"]), reverse=True)
    best = all_obs[0]

    if best["score"] < MIN_SCORE:
        log(f"Best OB score {best['score']} < MIN_SCORE {MIN_SCORE} — skipping", "dim red")
        return None

    log(f"Best OB: {direction.upper()} @ {best['ob_price']:.2f}  "
        f"TF={best['tf']}  score={best['score']}  rules={best['rules_passed']}", "dim cyan")

    # Run filters
    filt = check_filters(direction, best["ob_price"])
    if filt is None:
        return None

    signal = {
        "direction":    direction,
        "ob_price":     best["ob_price"],
        "ob_type":      best["ob_type"],
        "ob_high":      best["ob_high"],
        "ob_low":       best["ob_low"],
        "ob_body_ratio":best["ob_body_ratio"],
        "imb_size":     best["extra"].get("imb_size"),
        "imb_ratio":    best["extra"].get("imb_ratio"),
        "score":        best["score"],
        "rules_passed": best["rules_passed"],
        "tfs":          [best["tf"]],
        "sr_touches":   0,
        "trend_m30":    trend_m30,
        "trend_m15":    trend_m15,
        "ask":          tick.ask,
        "bid":          tick.bid,
        **filt,
    }
    return signal


# ─────────────────────────────────────────────────────────────────────────────
# TP/SL COMPUTATION  (ATR-based, same as order.py's compute_tp_sl_prices)
# ─────────────────────────────────────────────────────────────────────────────
def floor_price(px: float, digits: int) -> float:
    q = Decimal(1).scaleb(-digits)
    return float(Decimal(str(float(px))).quantize(q, rounding=ROUND_DOWN))


def ceil_price(px: float, digits: int) -> float:
    q = Decimal(1).scaleb(-digits)
    return float(Decimal(str(float(px))).quantize(q, rounding=ROUND_UP))


def compute_tp_sl(limit_price: float, direction: str,
                  atr_val: float, sym_info) -> tuple:
    digits = sym_info.digits
    point  = sym_info.point
    stops  = sym_info.trade_stops_level
    min_d  = max(stops, 10) * point

    dt = max(atr_val * TP_ATR_MULT, min_d * 2)
    ds = max(atr_val * SL_ATR_MULT, min_d)

    if direction == "buy":
        tp = round(limit_price + dt, digits)
        sl = round(limit_price - ds, digits)
    else:
        tp = round(limit_price - dt, digits)
        sl = round(limit_price + ds, digits)
    return tp, sl


# ─────────────────────────────────────────────────────────────────────────────
# ORDER MANAGEMENT  (same pattern as order.py + trader.py)
# ─────────────────────────────────────────────────────────────────────────────
def place_limit_order(signal: dict, sym_info, trade_id: str):
    """
    Places a BUY LIMIT or SELL LIMIT at the OB zone.
    Entry is at the OB's reference price (ob_high for bull, ob_low for bear).
    """
    direction    = signal["direction"]
    digits       = sym_info.digits
    point        = sym_info.point
    stops_level  = sym_info.trade_stops_level
    filling_mode = get_filling_mode(sym_info)
    atr_val      = signal.get("atr_m30", 8.0)

    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        log("✗ No tick data", "red")
        return None, None

    ask      = tick.ask
    bid      = tick.bid
    min_dist = max(stops_level, 10) * point
    raw_px   = signal["ob_price"]

    if direction == "buy":
        if raw_px > ask - min_dist:
            log(f"Skip: BUY OB {raw_px:.2f} inside min_dist of ask {ask:.2f}", "yellow")
            return None, None
        target      = raw_px + LIMIT_FILL_BUFFER
        max_px      = floor_price(ask - min_dist, digits)
        if target > max_px: target = max_px
        order_type  = mt5.ORDER_TYPE_BUY_LIMIT
        limit_price = ceil_price(target, digits)
        if limit_price > max_px: limit_price = max_px
    else:
        if raw_px < bid + min_dist:
            log(f"Skip: SELL OB {raw_px:.2f} inside min_dist of bid {bid:.2f}", "yellow")
            return None, None
        target      = raw_px - LIMIT_FILL_BUFFER
        min_px      = ceil_price(bid + min_dist, digits)
        if target < min_px: target = min_px
        order_type  = mt5.ORDER_TYPE_SELL_LIMIT
        limit_price = floor_price(target, digits)
        if limit_price < min_px: limit_price = min_px

    tp_price, sl_price = compute_tp_sl(limit_price, direction, atr_val, sym_info)
    expiry = tick.time + ORDER_EXPIRY_SEC
    label  = "BUY LIMIT" if order_type == mt5.ORDER_TYPE_BUY_LIMIT else "SELL LIMIT"

    request = {
        "action":       mt5.TRADE_ACTION_PENDING,
        "symbol":       SYMBOL,
        "volume":       LOT,
        "type":         order_type,
        "price":        limit_price,
        "sl":           sl_price,
        "tp":           tp_price,
        "deviation":    DEVIATION,
        "magic":        MAGIC,
        "comment":      f"OB {trade_id}",
        "type_time":    mt5.ORDER_TIME_SPECIFIED,
        "expiration":   expiry,
        "type_filling": filling_mode,
    }

    chk = mt5.order_check(request)
    if chk is None or chk.retcode != 0:
        log(f"✗ order_check: {getattr(chk,'comment','?')} (rc={getattr(chk,'retcode','?')})  "
            f"px={limit_price:.{digits}f}  ask={ask:.{digits}f}  bid={bid:.{digits}f}", "red")
        return None, None

    res = mt5.order_send(request)
    if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
        log(f"✗ order_send: {getattr(res,'comment','?')} (rc={getattr(res,'retcode','?')})", "red")
        return None, None

    log(f"✓ {label} @ {limit_price:.{digits}f}  TP {tp_price:.{digits}f}  SL {sl_price:.{digits}f}  "
        f"ATR={atr_val:.2f}  RR=1:{int(TP_ATR_MULT/SL_ATR_MULT)}  score={signal['score']}  "
        f"rules={signal['rules_passed']}", "bold cyan")

    db_update_trade(trade_id,
        order_ticket    = res.order,
        order_type      = label,
        order_placed_at = datetime.now(timezone.utc).isoformat(),
        limit_price     = round(limit_price, digits),
        tp_price        = round(tp_price, digits),
        sl_price        = round(sl_price, digits),
        status          = "waiting_fill",
    )
    return res.order, label


def cancel_order(ticket: int, trade_id: str):
    res = mt5.order_send({
        "action": mt5.TRADE_ACTION_REMOVE,
        "order":  ticket,
        "magic":  MAGIC,
    })
    if res and res.retcode == mt5.TRADE_RETCODE_DONE:
        log(f"Pending #{ticket} cancelled (1 h expiry)", "yellow")
        db_update_trade(trade_id, status="cancelled", exit_reason="expired_1h")
        return True
    log(f"✗ cancel #{ticket}: {getattr(res,'comment','?')}", "red")
    return False


def close_position(ticket: int, direction: str, volume: float, sym_info):
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        return False, None
    close_px = tick.bid if direction == "buy" else tick.ask
    res = mt5.order_send({
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       SYMBOL,
        "volume":       volume,
        "type":         mt5.ORDER_TYPE_SELL if direction == "buy" else mt5.ORDER_TYPE_BUY,
        "position":     ticket,
        "price":        close_px,
        "deviation":    DEVIATION,
        "magic":        MAGIC,
        "comment":      "OB emergency close",
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": get_filling_mode(sym_info),
    })
    ok = res is not None and res.retcode == mt5.TRADE_RETCODE_DONE
    return ok, close_px


# ─────────────────────────────────────────────────────────────────────────────
# DEAL HISTORY READER  (with retry — same as trader.py FIX A/B/C)
# ─────────────────────────────────────────────────────────────────────────────
def _read_deals_with_retry(position_ticket: int) -> list:
    for attempt in range(DEAL_RETRY_N):
        deals = mt5.history_deals_get(position=position_ticket)
        if deals is not None and len(deals) > 0:
            return list(deals)
        if attempt < DEAL_RETRY_N - 1:
            time.sleep(DEAL_RETRY_SLEEP)
    deals = mt5.history_deals_get(
        date_from=int(time.time()) - 86400,
        date_to  =int(time.time()) + 60,
    )
    if deals:
        deals = [d for d in deals if d.position_id == position_ticket]
        if deals:
            return list(deals)
    return []


def read_entry_info(position_ticket: int) -> dict:
    deals    = _read_deals_with_retry(position_ticket)
    in_deals = [d for d in deals if d.entry == mt5.DEAL_ENTRY_IN]
    if not in_deals:
        return {}
    d = in_deals[0]
    return {
        "entry_price": d.price,
        "entry_time":  datetime.utcfromtimestamp(d.time).isoformat(),
        "entry_epoch": d.time,
    }


def read_exit_info(position_ticket: int) -> dict:
    deals = _read_deals_with_retry(position_ticket)
    if not deals:
        return {}
    out_deals = [d for d in deals if d.entry == mt5.DEAL_ENTRY_OUT]
    if not out_deals:
        out_deals = deals
    deal = out_deals[-1]
    reason_map = {
        mt5.DEAL_REASON_TP:     "tp",
        mt5.DEAL_REASON_SL:     "sl",
        mt5.DEAL_REASON_CLIENT: "manual",
        mt5.DEAL_REASON_EXPERT: "bot",
        mt5.DEAL_REASON_MOBILE: "mobile",
    }
    reason = reason_map.get(deal.reason, f"code_{deal.reason}")
    pnl    = sum(d.profit + d.commission + d.swap for d in deals)
    return {
        "exit_price":  deal.price,
        "exit_time":   datetime.utcfromtimestamp(deal.time).isoformat(),
        "exit_reason": reason,
        "pnl":         round(pnl, 2),
    }


# ─────────────────────────────────────────────────────────────────────────────
# OHLCV SNAPSHOT
# ─────────────────────────────────────────────────────────────────────────────
def _rates_to_list(rates) -> list:
    return [{
        "time":        int(r["time"]),
        "time_str":    datetime.utcfromtimestamp(int(r["time"])).strftime("%Y-%m-%d %H:%M"),
        "open":  float(r["open"]),  "high":  float(r["high"]),
        "low":   float(r["low"]),   "close": float(r["close"]),
        "tick_volume": int(r["tick_volume"]),
    } for r in rates]


def snapshot_ohlcv(trade_id: str, signal: dict):
    payload = {
        "trade_id":      trade_id,
        "symbol":        SYMBOL,
        "snapshot_type": "analyse",
        "snapshot_at":   datetime.now(timezone.utc).isoformat(),
        "signal":        {k: signal.get(k) for k in
                         ["direction","ob_price","ob_type","score","rules_passed",
                          "rsi","trend_m30","trend_m15","atr_m30","imb_ratio"]},
        "timeframes":    {},
    }
    for tf_name, tf_val in TIMEFRAMES.items():
        rates = mt5.copy_rates_from_pos(SYMBOL, tf_val, 0, OB_LOOKBACK + 50)
        if rates is not None and len(rates) > 0:
            payload["timeframes"][tf_name] = {
                "total_candles": len(rates),
                "candles":       _rates_to_list(rates),
            }
    path = os.path.join(OHLCV_DIR, f"{trade_id}.json")
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
    log(f"[DB] OHLCV → ohlcv/{trade_id}.json", "dim")


# ─────────────────────────────────────────────────────────────────────────────
# RICH DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────
def build_dashboard(state: dict):
    mode   = state.get("mode", "idle")
    signal = state.get("signal")
    stats  = state.get("stats", {})

    # Header
    hdr = Text(justify="center")
    hdr.append("◆ OB-Bot v1  ", style="bold yellow")
    hdr.append(SYMBOL, style="bold white")
    hdr.append("  ●  ", style="dim")
    hdr.append(datetime.now().strftime("%H:%M:%S"), style="bold cyan")
    hdr.append(f"  ●  {mode.upper()}", style="bold yellow")
    panels = [Panel(Align.center(hdr), box=box.ROUNDED,
                    border_style="yellow", padding=(0, 1))]

    # Signal panel
    if signal:
        tbl = Table.grid(expand=True, padding=(0, 2))
        for _ in range(4): tbl.add_column()
        d   = signal["direction"]
        col = "bold green" if d == "buy" else "bold red"
        arr = "▲" if d == "buy" else "▼"
        tbl.add_row("OB Signal",    Text.from_markup(f"[{col}]{arr} {d.upper()}[/{col}]"),
                    "OB Price",     f"{signal['ob_price']:.2f}")
        tbl.add_row("OB Type",      signal.get("ob_type","?"),
                    "Score",        str(signal.get("score","?")))
        tbl.add_row("M30 Trend",    signal.get("trend_m30","?"),
                    "M15 Trend",    signal.get("trend_m15","?"))
        tbl.add_row("RSI",          str(signal.get("rsi","?")),
                    "ATR(M30)",     str(signal.get("atr_m30","?")))
        tbl.add_row("IMB Ratio",    f"{signal.get('imb_ratio','?')}×",
                    "Vol Ratio",    f"{signal.get('vol_ratio','?')}×")
        tbl.add_row("Rules",        ",".join(signal.get("rules_passed",[])),
                    "TF",           ",".join(signal.get("tfs",[])))
        if state.get("trade_id"):
            tbl.add_row("ID", state["trade_id"], "OHLCV", f"ohlcv/{state['trade_id']}.json")
        panels.append(Panel(tbl, title="[bold]OB Signal[/]", title_align="left",
                            box=box.ROUNDED, border_style="cyan", padding=(0, 1)))

    # Position / pending panel
    pos     = state.get("pos")
    pos_txt = Text()
    if mode == "waiting_fill" and signal:
        elapsed   = int(time.time() - (state.get("order_placed_at") or time.time()))
        remaining = max(0, ORDER_EXPIRY_SEC - elapsed)
        pos_txt.append(f"  Pending #{state.get('order_ticket','?')}  "
                       f"Limit @ {signal['ob_price']:.2f}\n", style="white")
        pos_txt.append(f"  Expires in {remaining}s\n",
                       style="yellow" if remaining < 300 else "white")
    elif pos is not None:
        profit = pos.profit
        col    = "green" if profit > 0 else "red"
        pct    = max(0.0, min(1.0, (profit - MAX_LOSS_USD) / (MAX_PROFIT_USD - MAX_LOSS_USD)))
        bw     = 36
        filled = int(round(pct * bw))
        bar = Text()
        bar.append("SL│", style="bold red")
        bar.append("━" * filled, style=col)
        bar.append("●", style=f"bold {col}")
        bar.append("━" * (bw - filled), style="dim")
        bar.append("│TP", style="bold green")
        pos_txt.append(f"  #{pos.ticket}  entry={pos.price_open:.2f}  P&L=", style="white")
        pos_txt.append(f"${profit:+.2f}\n", style=f"bold {col}")
        pos_txt.append("  "); pos_txt.append_text(bar); pos_txt.append("\n")

    if pos_txt.plain.strip():
        border = "blue" if mode == "waiting_fill" else (
            "green" if pos and pos.profit >= 0 else "red")
        panels.append(Panel(pos_txt, title="[bold]Position[/]", title_align="left",
                            box=box.ROUNDED, border_style=border, padding=(0, 1)))

    # Cooldown
    if mode == "cooldown":
        cd = Text(f"  Waiting {state.get('cooldown_remaining',0)} M15 candles…",
                  style="dim yellow")
        panels.append(Panel(cd, title="[bold]Cooldown[/]", title_align="left",
                            box=box.ROUNDED, border_style="yellow", padding=(0, 1)))

    # Stats
    if stats:
        wr  = stats.get("wr", 0)
        g   = stats.get("gross", 0)
        txt = Text()
        txt.append(f"  {stats.get('closed',0)} closed  ", style="white")
        txt.append(f"W:{stats.get('wins',0)} ", style="green")
        txt.append(f"L:{stats.get('losses',0)}  ", style="red")
        txt.append("WR ", style="white")
        txt.append(f"{wr:.0f}%  ", style="bold green" if wr >= 55 else "bold red")
        txt.append("Net ", style="white")
        txt.append(f"${g:+.2f}  ", style="bold green" if g >= 0 else "bold red")
        txt.append(f"DB→{TRADE_DB_PATH}", style="dim")
        panels.append(Panel(txt, title="[bold]Database[/]", title_align="left",
                            box=box.ROUNDED, border_style="yellow dim", padding=(0, 1)))

    # Events log
    ev = Text()
    for ts, msg, sty in list(events)[-9:]:
        ev.append(f"  {ts}  ", style="dim")
        ev.append(f"{msg}\n", style=sty)
    panels.append(Panel(ev, title="[bold]Events[/]", title_align="left",
                        box=box.ROUNDED, border_style="dim", padding=(0, 1)))

    return Group(*panels)


# ─────────────────────────────────────────────────────────────────────────────
# COOLDOWN
# ─────────────────────────────────────────────────────────────────────────────
def wait_cooldown(live, state: dict):
    log(f"Cooldown: {COOLDOWN_CANDLES} M15 bars…", "yellow")

    def last_bar():
        r = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M15, 0, 2)
        return int(r[0]["time"]) if r is not None and len(r) >= 2 else None

    seen = set()
    t0   = last_bar()
    if t0: seen.add(t0)
    while len(seen) - 1 < COOLDOWN_CANDLES:
        state["mode"]               = "cooldown"
        state["cooldown_remaining"] = COOLDOWN_CANDLES - (len(seen) - 1)
        live.update(build_dashboard(state))
        time.sleep(5)
        t = last_bar()
        if t and t not in seen:
            seen.add(t)
            log(f"Cooldown {len(seen)-1}/{COOLDOWN_CANDLES}", "dim")
    log("Cooldown done → re-analysing", "green")


# ─────────────────────────────────────────────────────────────────────────────
# HTML REPORT EXPORT  (triggered on Ctrl+C — same style as trader.py)
# ─────────────────────────────────────────────────────────────────────────────
XAU_POINT = 0.01
XAU_PIP   = 0.10
XAU_OZ    = 100.0


def _fmt(v, nd=2, suffix="", empty="—"):
    if v is None: return empty
    if isinstance(v, float):
        return f"{v:+.{nd}f}{suffix}" if nd <= 2 else f"{v:.{nd}f}{suffix}"
    return str(v)


def _fmt_signed(v, nd=2, suffix=""):
    if v is None: return "—"
    return f"{float(v):+.{nd}f}{suffix}"


def export_html_report() -> str | None:
    records = _load_db()
    if not records:
        return None

    total_pnl = 0.0
    wins = losses = closed_n = 0
    for r in records:
        pnl = r.get("pnl")
        if pnl is not None:
            closed_n  += 1
            total_pnl += float(pnl)
            if pnl > 0: wins += 1
            else:        losses += 1

    wr  = (wins / closed_n * 100.0) if closed_n else 0.0
    avg = (total_pnl / closed_n) if closed_n else 0.0
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    def badge(r):
        st  = r.get("status") or "?"
        rsn = r.get("exit_reason") or ""
        cls = {"closed": "ok" if (r.get("pnl") or 0) > 0 else
               ("bad" if (r.get("pnl") or 0) < 0 else "mid"),
               "open": "live", "waiting_fill": "warn",
               "cancelled": "dim", "pending": "warn"}.get(st, "mid")
        label = st if not rsn else f"{st} · {rsn}"
        return f'<span class="badge {cls}">{label}</span>'

    rows_html = []
    for r in records:
        d    = (r.get("direction") or "?").upper()
        dcls = "buy" if d == "BUY" else "sell"
        pnl  = r.get("pnl")
        pc   = "pos" if pnl and pnl > 0 else ("neg" if pnl and pnl < 0 else "")
        rules= ", ".join(r.get("rules_passed") or []) or "—"
        rows_html.append(f"""
        <tr>
          <td class="mono">{r.get('trade_id','')}</td>
          <td><span class="dir {dcls}">{d}</span></td>
          <td>{badge(r)}</td>
          <td class="mono num">{_fmt(r.get('zone_price'), 2)}</td>
          <td class="mono num">{_fmt(r.get('limit_price'), 2)}</td>
          <td class="mono num">{_fmt(r.get('entry_price'), 2)}</td>
          <td class="mono num">{_fmt(r.get('exit_price'), 2)}</td>
          <td class="mono num">{_fmt(r.get('tp_price'), 2)}</td>
          <td class="mono num">{_fmt(r.get('sl_price'), 2)}</td>
          <td class="mono num {pc} bold">{_fmt_signed(pnl, 2)}</td>
          <td class="mono num">{r.get('zone_score','—')}</td>
          <td class="mono dim small">{rules}</td>
          <td class="mono num">{_fmt(r.get('imb_ratio'), 2, '×')}</td>
          <td class="mono dim small">{r.get('ob_type','—')}</td>
          <td class="mono dim">{r.get('entry_time') or '—'}</td>
          <td class="mono dim">{r.get('exit_time') or '—'}</td>
        </tr>""")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OB-Bot Trade Report — {now}</title>
<style>
  :root {{
    --bg:#0d1117;--card:#161b22;--border:#30363d;--text:#e6edf3;
    --dim:#8b949e;--green:#3fb950;--red:#f85149;--blue:#58a6ff;
    --orange:#d29922;--purple:#bc8cff;
  }}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:"Segoe UI",system-ui,sans-serif;background:var(--bg);
        color:var(--text);padding:24px;min-height:100vh}}
  h1{{font-size:1.4rem;font-weight:600;margin-bottom:4px}}
  .sub{{color:var(--dim);font-size:.85rem;margin-bottom:20px}}
  .cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
          gap:12px;margin-bottom:24px}}
  .card{{background:var(--card);border:1px solid var(--border);
         border-radius:10px;padding:14px 16px}}
  .card .label{{color:var(--dim);font-size:.75rem;text-transform:uppercase;
                letter-spacing:.05em}}
  .card .value{{font-size:1.45rem;font-weight:700;margin-top:4px;
                font-variant-numeric:tabular-nums}}
  .value.pos{{color:var(--green)}}.value.neg{{color:var(--red)}}
  .value.blue{{color:var(--blue)}}.value.orange{{color:var(--orange)}}
  .table-wrap{{background:var(--card);border:1px solid var(--border);
               border-radius:10px;overflow-x:auto}}
  table{{width:100%;border-collapse:collapse;font-size:.82rem}}
  th{{text-align:left;padding:10px;color:var(--dim);font-weight:600;
      font-size:.72rem;text-transform:uppercase;letter-spacing:.04em;
      border-bottom:1px solid var(--border);background:#21262d;
      position:sticky;top:0;white-space:nowrap}}
  td{{padding:9px 10px;border-bottom:1px solid var(--border);white-space:nowrap}}
  tr:last-child td{{border-bottom:none}}
  tr:hover td{{background:rgba(88,166,255,.04)}}
  .mono{{font-family:"Cascadia Code","Fira Code",Consolas,monospace}}
  .num{{text-align:right;font-variant-numeric:tabular-nums}}
  .bold{{font-weight:700}}.dim{{color:var(--dim)}}.small{{font-size:.75rem}}
  .pos{{color:var(--green)}}.neg{{color:var(--red)}}
  .badge{{display:inline-block;padding:2px 8px;border-radius:99px;
          font-size:.7rem;font-weight:600;text-transform:uppercase}}
  .badge.ok{{background:rgba(63,185,80,.15);color:var(--green)}}
  .badge.bad{{background:rgba(248,81,73,.15);color:var(--red)}}
  .badge.live{{background:rgba(88,166,255,.15);color:var(--blue)}}
  .badge.warn{{background:rgba(210,153,34,.15);color:var(--orange)}}
  .badge.dim{{background:rgba(139,148,158,.15);color:var(--dim)}}
  .badge.mid{{background:rgba(188,140,255,.15);color:var(--purple)}}
  .dir{{font-weight:700;font-size:.75rem;padding:2px 7px;border-radius:4px;
        letter-spacing:.04em}}
  .dir.buy{{background:rgba(63,185,80,.15);color:var(--green)}}
  .dir.sell{{background:rgba(248,81,73,.15);color:var(--red)}}
  footer{{margin-top:16px;color:var(--dim);font-size:.75rem;text-align:center}}
</style>
</head>
<body>
  <h1>OB-Bot Trade Report</h1>
  <p class="sub">{SYMBOL} · lot {LOT} · exported {now} · source {TRADE_DB_PATH}</p>
  <div class="cards">
    <div class="card"><div class="label">Total Orders</div>
      <div class="value blue">{len(records)}</div></div>
    <div class="card"><div class="label">Closed</div>
      <div class="value">{closed_n}</div></div>
    <div class="card"><div class="label">Wins</div>
      <div class="value pos">{wins}</div></div>
    <div class="card"><div class="label">Losses</div>
      <div class="value neg">{losses}</div></div>
    <div class="card"><div class="label">Win Rate</div>
      <div class="value {'pos' if wr>=50 else 'neg'}">{wr:.1f}%</div></div>
    <div class="card"><div class="label">Net PnL</div>
      <div class="value {'pos' if total_pnl>=0 else 'neg'}">${total_pnl:+.2f}</div></div>
    <div class="card"><div class="label">Avg / Trade</div>
      <div class="value {'pos' if avg>=0 else 'neg'}">${avg:+.2f}</div></div>
    <div class="card"><div class="label">Open / Pending</div>
      <div class="value orange">{sum(1 for r in records if r.get('status') in ('open','waiting_fill','pending'))}</div></div>
  </div>
  <div class="table-wrap">
    <table>
      <thead><tr>
        <th>ID</th><th>Dir</th><th>Status</th>
        <th class="num">OB Zone</th><th class="num">Limit</th>
        <th class="num">Entry</th><th class="num">Exit</th>
        <th class="num">TP</th><th class="num">SL</th>
        <th class="num">PnL $</th>
        <th class="num">Score</th><th>Rules Passed</th>
        <th class="num">IMB×</th><th>OB Type</th>
        <th>Entry Time</th><th>Exit Time</th>
      </tr></thead>
      <tbody>{''.join(rows_html)}</tbody>
    </table>
  </div>
  <footer>OB-Bot v1 · generated by ob_bot.py</footer>
</body>
</html>"""

    os.makedirs(EXPORT_DIR, exist_ok=True)
    stamp    = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(EXPORT_DIR, f"ob_report_{stamp}.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path


# ─────────────────────────────────────────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────────────────────────────────────────
def run_bot():
    mt5_connect()
    sym_info = get_symbol_info()
    if sym_info is None:
        mt5.shutdown()
        sys.exit(1)

    log(f"OB-Bot v1  {SYMBOL}  lot={LOT}  "
        f"TP×{TP_ATR_MULT}ATR  SL×{SL_ATR_MULT}ATR  "
        f"MIN_SCORE={MIN_SCORE}  RULES={list(RULE_WEIGHTS.keys())}", "bold yellow")

    state = {
        "mode":               "idle",
        "signal":             None,
        "pos":                None,
        "order_ticket":       None,
        "order_placed_at":    None,
        "cooldown_remaining": 0,
        "trade_id":           None,
        "stats":              db_stats(),
    }

    try:
        with Live(console=console, refresh_per_second=2,
                  screen=True, transient=False) as live:
            while True:
                try:
                    # ── 1. ANALYSE ──────────────────────────────────────────
                    state.update({"mode": "analysing", "signal": None, "trade_id": None})
                    live.update(build_dashboard(state))
                    log("Scanning: trend → OBs → rules → filters…", "cyan")

                    signal = get_signal()

                    if signal is None:
                        state["mode"] = "idle"
                        live.update(build_dashboard(state))
                        time.sleep(60)
                        continue

                    state["signal"] = signal
                    log(f"✓ OB Signal: {signal['direction'].upper()} @ {signal['ob_price']:.2f}  "
                        f"score={signal['score']}  rules={signal['rules_passed']}  "
                        f"RSI={signal['rsi']}  ATR={signal['atr_m30']}", "bold green")

                    # ── 2. DB + OHLCV ───────────────────────────────────────
                    trade_id = db_create_trade(signal)
                    state["trade_id"] = trade_id
                    snapshot_ohlcv(trade_id, signal)

                    # ── 3. PLACE ORDER ──────────────────────────────────────
                    state["mode"] = "placing_order"
                    live.update(build_dashboard(state))
                    sym_info = get_symbol_info()
                    ticket, label = place_limit_order(signal, sym_info, trade_id)

                    if ticket is None:
                        db_update_trade(trade_id, status="cancelled",
                                        exit_reason="order_failed")
                        state.update({"mode": "idle", "stats": db_stats()})
                        live.update(build_dashboard(state))
                        time.sleep(30)
                        continue

                    state.update({
                        "mode":             "waiting_fill",
                        "order_ticket":     ticket,
                        "order_placed_at":  time.time(),
                    })
                    live.update(build_dashboard(state))

                    # ── 4. WAIT FOR FILL ────────────────────────────────────
                    position_ticket = None
                    position_dir    = signal["direction"]
                    entry_epoch     = None

                    while True:
                        elapsed = time.time() - state["order_placed_at"]
                        pending = mt5.orders_get(ticket=ticket)

                        if pending is None or len(pending) == 0:
                            positions = mt5.positions_get(magic=MAGIC)
                            if positions:
                                for p in positions:
                                    if p.magic == MAGIC:
                                        position_ticket = p.ticket
                                        entry_info = read_entry_info(position_ticket)
                                        entry_epoch = entry_info.get("entry_epoch")
                                        log(f"Filled! #{position_ticket}  "
                                            f"entry={entry_info.get('entry_price','?')}", "bold green")
                                        db_update_trade(trade_id,
                                            position_ticket = position_ticket,
                                            entry_price     = entry_info.get("entry_price"),
                                            entry_time      = entry_info.get("entry_time"),
                                            status          = "open",
                                        )
                                        break

                            if position_ticket is None:
                                log("Pending gone — no fill", "yellow")
                                db_update_trade(trade_id, status="cancelled",
                                                exit_reason="no_fill")
                            break

                        if elapsed >= ORDER_EXPIRY_SEC:
                            cancel_order(ticket, trade_id)
                            break

                        state["mode"] = "waiting_fill"
                        live.update(build_dashboard(state))
                        time.sleep(CHECK_INTERVAL)

                    # ── 5. MONITOR POSITION ─────────────────────────────────
                    if position_ticket is None:
                        state["stats"] = db_stats()
                        wait_cooldown(live, state)
                        continue

                    state["mode"] = "in_position"
                    close_reason  = None
                    exit_info_dict= {}

                    while True:
                        positions = mt5.positions_get(ticket=position_ticket)

                        if positions is None or len(positions) == 0:
                            exit_info_dict = read_exit_info(position_ticket)
                            close_reason   = exit_info_dict.get("exit_reason", "external")
                            log(f"Closed: reason={close_reason}  "
                                f"exit={exit_info_dict.get('exit_price')}  "
                                f"pnl=${exit_info_dict.get('pnl')}", "bold white")
                            break

                        pos    = positions[0]
                        profit = pos.profit
                        state["pos"] = pos
                        live.update(build_dashboard(state))

                        # Emergency safety net
                        if profit >= MAX_PROFIT_USD:
                            log(f"Emergency TP @ ${profit:+.2f}", "bold green")
                            close_reason = "tp_emergency"; break
                        if profit <= MAX_LOSS_USD:
                            log(f"Emergency SL @ ${profit:+.2f}", "bold red")
                            close_reason = "sl_emergency"; break

                        time.sleep(CHECK_INTERVAL)

                    # ── 6. EMERGENCY CLOSE ──────────────────────────────────
                    if close_reason in ("tp_emergency", "sl_emergency"):
                        positions = mt5.positions_get(ticket=position_ticket)
                        if positions and len(positions) > 0:
                            close_position(position_ticket, position_dir,
                                           positions[0].volume, sym_info)
                        time.sleep(0.5)
                        exit_info_dict = read_exit_info(position_ticket)
                        close_reason   = exit_info_dict.get("exit_reason", close_reason)

                    # ── 7. RECORD RESULT ────────────────────────────────────
                    final_pnl = exit_info_dict.get("pnl")
                    db_update_trade(trade_id,
                        exit_price  = exit_info_dict.get("exit_price"),
                        exit_time   = exit_info_dict.get("exit_time"),
                        exit_reason = close_reason,
                        pnl         = final_pnl,
                        status      = "closed",
                    )

                    pnl_str = f"${final_pnl:+.2f}" if final_pnl is not None else "?"
                    log(f"[DB] {trade_id} → {close_reason}  {pnl_str}", "bold white")

                    state.update({"pos": None, "mode": "idle", "stats": db_stats()})
                    live.update(build_dashboard(state))
                    wait_cooldown(live, state)

                except KeyboardInterrupt:
                    log("Stopped by user", "yellow"); break
                except Exception as exc:
                    log(f"Error: {exc}", "red")
                    console.print_exception()
                    log("Retry in 30 s…", "dim")
                    time.sleep(30)

    except KeyboardInterrupt:
        log("Stopped by user", "yellow")
    finally:
        try:
            html_path = export_html_report()
            if html_path:
                log(f"HTML report → {html_path}", "bold green")
            else:
                log("No trades in DB — report skipped", "yellow")
        except Exception as exc:
            log(f"HTML export failed: {exc}", "red")
        mt5.shutdown()
        log("MT5 disconnected.", "dim")
        console.print()


if __name__ == "__main__":
    run_bot()