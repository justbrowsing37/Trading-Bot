# data.py
import pandas as pd
from datetime import datetime, timedelta, timezone
from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from config import API_KEY, SECRET_KEY
from bot_logger import get_logger

log = get_logger(__name__)
data_client = StockHistoricalDataClient(API_KEY, SECRET_KEY)


def _fetch(symbols, timeframe, start, end) -> pd.DataFrame:
    req  = StockBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=timeframe,
        start=start,
        end=end,
        feed=DataFeed.IEX
    )
    bars = data_client.get_stock_bars(req)
    df   = bars.df.sort_index()
    return df


def get_bars(symbol: str, lookback_days: int = 120) -> pd.DataFrame:
    end   = datetime.now(timezone.utc)
    start = end - timedelta(days=lookback_days)
    df    = _fetch(symbol, TimeFrame.Day, start, end)
    if isinstance(df.index, pd.MultiIndex):
        df = df.xs(symbol, level="symbol")
    df = df.sort_index()
    log.info(f"Fetched {len(df)} daily bars for {symbol}")
    return df


def get_bars_batch(symbols: list[str], lookback_days: int = 90) -> pd.DataFrame:
    end   = datetime.now(timezone.utc)
    start = end - timedelta(days=lookback_days)
    df    = _fetch(symbols, TimeFrame.Day, start, end)
    log.info(f"Batch fetched {len(symbols)} symbols -> {len(df)} total daily bars")
    return df


def get_intraday_bars(symbol: str, lookback_days: int = 5) -> pd.DataFrame:
    """Fetch 15-minute bars for a single symbol."""
    end   = datetime.now(timezone.utc)
    start = end - timedelta(days=lookback_days)
    df    = _fetch(symbol, TimeFrame.Minute15, start, end)
    if isinstance(df.index, pd.MultiIndex):
        df = df.xs(symbol, level="symbol")
    df = df.sort_index()
    log.info(f"Fetched {len(df)} 15m bars for {symbol}")
    return df


def get_intraday_bars_batch(symbols: list[str], lookback_days: int = 5) -> pd.DataFrame:
    """Fetch 15-minute bars for multiple symbols in one call."""
    end   = datetime.now(timezone.utc)
    start = end - timedelta(days=lookback_days)
    df    = _fetch(symbols, TimeFrame.Minute15, start, end)
    log.info(f"Batch fetched {len(symbols)} symbols -> {len(df)} 15m bars")
    return df