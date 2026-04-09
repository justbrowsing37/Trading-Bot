# risk.py

import pandas as pd
from config import (
    RISK_PER_TRADE,
    DAILY_LOSS_LIMIT,
    REWARD_RISK_RATIO,
    ATR_PERIOD,
    ATR_STOP_MULTIPLIER,
    TRAILING_ATR_MULTIPLIER,
)


def calc_atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> float:
    high       = df["high"]
    low        = df["low"]
    close      = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low),
         (high - prev_close).abs(),
         (low  - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return float(tr.rolling(period).mean().iloc[-1])


# --- LONG levels ---
def calc_stop_loss_long(price: float, atr: float) -> float:
    return round(price - (ATR_STOP_MULTIPLIER * atr), 2)

def calc_take_profit_long(price: float, atr: float) -> float:
    return round(price + (ATR_STOP_MULTIPLIER * atr * REWARD_RISK_RATIO), 2)

def calc_trailing_stop_long(current_price: float, atr: float) -> float:
    """Trail below current price by TRAILING_ATR_MULTIPLIER x ATR."""
    return round(current_price - (TRAILING_ATR_MULTIPLIER * atr), 2)


# --- SHORT levels ---
def calc_stop_loss_short(price: float, atr: float) -> float:
    return round(price + (ATR_STOP_MULTIPLIER * atr), 2)

def calc_take_profit_short(price: float, atr: float) -> float:
    return round(price - (ATR_STOP_MULTIPLIER * atr * REWARD_RISK_RATIO), 2)

def calc_trailing_stop_short(current_price: float, atr: float) -> float:
    """Trail above current price by TRAILING_ATR_MULTIPLIER x ATR."""
    return round(current_price + (TRAILING_ATR_MULTIPLIER * atr), 2)


# --- Position sizing ---
def calc_position_size(equity: float, price: float, stop_price: float) -> int:
    risk_dollars   = equity * RISK_PER_TRADE
    per_share_risk = max(abs(price - stop_price), 0.01)
    qty            = int(risk_dollars // per_share_risk)
    return max(qty, 1)


def is_daily_loss_breached(start_equity: float, current_equity: float) -> bool:
    if start_equity is None:
        return False
    return (start_equity - current_equity) / start_equity >= DAILY_LOSS_LIMIT