# screener.py
import pandas as pd
from bot_logger import get_logger

log = get_logger(__name__)

MIN_PRICE   = 10.0
MIN_VOLUME  = 500_000
MIN_ADR_PCT = 1.0


def passes_screen(symbol: str, bars: pd.DataFrame) -> bool:
    """Return True if the ticker is worth running the strategy on."""
    try:
        if bars is None or len(bars) < 21:
            return False

        price  = float(bars["close"].iloc[-1])
        volume = float(bars["volume"].iloc[-1])
        adr    = float(((bars["high"] - bars["low"]) / bars["close"]).tail(20).mean() * 100)

        if price  < MIN_PRICE:   return False
        if volume < MIN_VOLUME:  return False
        if adr    < MIN_ADR_PCT: return False

        return True

    except Exception as e:
        log.debug(f"Screen error {symbol}: {e}")
        return False