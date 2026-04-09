# strategy.py
import pandas as pd
from config import SPY_MA_PERIOD


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta    = series.diff()
    gain     = delta.clip(lower=0)
    loss     = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs       = avg_gain / avg_loss.replace(0, 1e-9)
    return 100 - (100 / (1 + rs))


def vwap(df: pd.DataFrame) -> pd.Series:
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    return (typical_price * df["volume"]).cumsum() / df["volume"].cumsum()


def market_is_bullish(spy_df: pd.DataFrame) -> bool:
    if spy_df is None or len(spy_df) < SPY_MA_PERIOD:
        return False
    spy_close = float(spy_df["close"].iloc[-1])
    spy_sma50 = float(sma(spy_df["close"], SPY_MA_PERIOD).iloc[-1])
    return spy_close > spy_sma50


def get_daily_trend(df: pd.DataFrame) -> str:
    """
    Uses daily bars to determine the macro trend.
    Returns 'bullish', 'bearish', or 'neutral'.
    """
    if df is None or len(df) < 50:
        return "neutral"

    close        = df["close"]
    sma50_val    = sma(close, 50).iloc[-1]
    sma200_val   = sma(close, min(200, len(close) - 1)).iloc[-1]
    current_rsi  = rsi(close, 14).iloc[-1]
    price        = float(close.iloc[-1])

    if price > sma50_val and sma50_val > sma200_val and current_rsi > 50:
        return "bullish"
    if price < sma50_val and sma50_val < sma200_val and current_rsi < 50:
        return "bearish"
    return "neutral"


def get_intraday_signal(df_15m: pd.DataFrame, daily_trend: str) -> str:
    """
    Uses 15-minute bars for precise entry timing.
    Only triggers in the direction of the daily trend.

    BUY  requires: daily_trend == bullish, EMA9 > EMA21 on 15m,
                   price > VWAP, RSI > 50, volume spike
    SELL requires: daily_trend == bearish, EMA9 < EMA21 on 15m,
                   price < VWAP, RSI < 50, volume spike
    """
    if df_15m is None or len(df_15m) < 30:
        return "HOLD"

    close    = df_15m["close"]
    volume   = df_15m["volume"]
    ema9     = ema(close, 9).iloc[-1]
    ema21    = ema(close, 21).iloc[-1]
    rsi_val  = rsi(close, 14).iloc[-1]
    vwap_val = vwap(df_15m).iloc[-1]
    price    = float(close.iloc[-1])

    avg_vol  = float(volume.tail(20).mean())
    cur_vol  = float(volume.iloc[-1])
    vol_spike = cur_vol > avg_vol * 1.2

    if (daily_trend == "bullish" and
            ema9 > ema21 and
            price > vwap_val and
            rsi_val > 50 and
            vol_spike):
        return "BUY"

    if (daily_trend == "bearish" and
            ema9 < ema21 and
            price < vwap_val and
            rsi_val < 50 and
            vol_spike):
        return "SELL"

    return "HOLD"