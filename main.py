# main.py
import json
import time

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

from config import (
    API_KEY, SECRET_KEY, PAPER,
    POLL_INTERVAL_SEC, MAX_POSITIONS,
    SCAN_INTERVAL_SEC, BATCH_SIZE,
    INTRADAY_LOOKBACK_DAYS, DAILY_LOOKBACK_DAYS,
)
from data import get_bars, get_bars_batch, get_intraday_bars, get_intraday_bars_batch
from strategy import get_daily_trend, get_intraday_signal, market_is_bullish
from risk import (
    calc_atr,
    calc_position_size,
    calc_stop_loss_long, calc_take_profit_long, calc_trailing_stop_long,
    calc_stop_loss_short, calc_take_profit_short, calc_trailing_stop_short,
    is_daily_loss_breached,
)
from bot_logger import get_logger
from report import log_trade, log_equity
from universe import get_sp500_tickers
from screener import passes_screen

log        = get_logger(__name__)
client     = TradingClient(API_KEY, SECRET_KEY, paper=PAPER)
STATE_FILE = "state.json"


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
def load_state() -> dict:
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"start_equity": None, "trailing_stops": {}}


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# ---------------------------------------------------------------------------
# Account helpers
# ---------------------------------------------------------------------------
def get_equity() -> float:
    return float(client.get_account().equity)


def get_position_side(symbol: str) -> str:
    try:
        pos = client.get_open_position(symbol)
        qty = float(pos.qty)
        if qty > 0:  return "long"
        if qty < 0:  return "short"
    except Exception:
        pass
    return "none"


def get_position_price(symbol: str) -> float:
    try:
        return float(client.get_open_position(symbol).current_price)
    except Exception:
        return 0.0


def count_open_positions() -> int:
    return len(client.get_all_positions())


def is_market_open() -> bool:
    return client.get_clock().is_open


# ---------------------------------------------------------------------------
# Order helpers
# ---------------------------------------------------------------------------
def place_buy(symbol: str, price: float, equity: float, atr: float) -> None:
    sl  = calc_stop_loss_long(price, atr)
    tp  = calc_take_profit_long(price, atr)
    qty = calc_position_size(equity, price, sl)
    resp = client.submit_order(MarketOrderRequest(
        symbol=symbol, qty=qty,
        side=OrderSide.BUY, time_in_force=TimeInForce.DAY
    ))
    log.info(f"LONG  {qty}x {symbol} @ ~${price:.2f} | ATR={atr:.2f} SL=${sl} TP=${tp} | {resp.id} {resp.status}")
    log_trade(symbol, "BUY", price, qty, equity, sl, tp)
    return sl  # initial trailing stop seed


def place_short(symbol: str, price: float, equity: float, atr: float) -> None:
    sl  = calc_stop_loss_short(price, atr)
    tp  = calc_take_profit_short(price, atr)
    qty = calc_position_size(equity, price, sl)
    resp = client.submit_order(MarketOrderRequest(
        symbol=symbol, qty=qty,
        side=OrderSide.SELL, time_in_force=TimeInForce.DAY
    ))
    log.info(f"SHORT {qty}x {symbol} @ ~${price:.2f} | ATR={atr:.2f} SL=${sl} TP=${tp} | {resp.id} {resp.status}")
    log_trade(symbol, "SHORT", price, qty, equity, sl, tp)
    return sl


def close_long(symbol: str, equity: float, reason: str = "signal") -> None:
    try:
        pos   = client.get_open_position(symbol)
        qty   = float(pos.qty)
        price = float(pos.current_price)
        resp  = client.submit_order(MarketOrderRequest(
            symbol=symbol, qty=qty,
            side=OrderSide.SELL, time_in_force=TimeInForce.DAY
        ))
        log.info(f"CLOSE LONG  {qty}x {symbol} @ ~${price:.2f} [{reason}] | {resp.id} {resp.status}")
        log_trade(symbol, "SELL", price, int(qty), equity)
    except Exception as e:
        log.warning(f"Could not close long {symbol}: {e}")


def cover_short(symbol: str, equity: float, reason: str = "signal") -> None:
    try:
        pos   = client.get_open_position(symbol)
        qty   = abs(float(pos.qty))
        price = float(pos.current_price)
        resp  = client.submit_order(MarketOrderRequest(
            symbol=symbol, qty=qty,
            side=OrderSide.BUY, time_in_force=TimeInForce.DAY
        ))
        log.info(f"COVER SHORT {qty}x {symbol} @ ~${price:.2f} [{reason}] | {resp.id} {resp.status}")
        log_trade(symbol, "COVER", price, int(qty), equity)
    except Exception as e:
        log.warning(f"Could not cover short {symbol}: {e}")


# ---------------------------------------------------------------------------
# Trailing stop manager
# ---------------------------------------------------------------------------
def update_trailing_stops(state: dict, equity: float,
                           long_positions: set, short_positions: set,
                           daily_bars_cache: dict) -> None:
    """
    For every open position, ratchet the trailing stop in the
    direction of the trade. If price crosses the trail, close it.
    """
    if "trailing_stops" not in state:
        state["trailing_stops"] = {}

    for symbol in list(long_positions):
        try:
            price = get_position_price(symbol)
            if price == 0:
                continue
            df_daily = daily_bars_cache.get(symbol)
            if df_daily is None or len(df_daily) < 15:
                continue

            atr   = calc_atr(df_daily)
            trail = calc_trailing_stop_long(price, atr)

            # Only ratchet upward
            prev  = state["trailing_stops"].get(symbol, 0)
            new_trail = max(trail, prev)
            state["trailing_stops"][symbol] = new_trail

            if price <= new_trail:
                log.info(f"Trailing stop HIT (long) {symbol}: price=${price} trail=${new_trail}")
                close_long(symbol, equity, reason="trailing_stop")
                long_positions.discard(symbol)
                state["trailing_stops"].pop(symbol, None)

        except Exception as e:
            log.warning(f"Trailing stop error (long) {symbol}: {e}")

    for symbol in list(short_positions):
        try:
            price = get_position_price(symbol)
            if price == 0:
                continue
            df_daily = daily_bars_cache.get(symbol)
            if df_daily is None or len(df_daily) < 15:
                continue

            atr   = calc_atr(df_daily)
            trail = calc_trailing_stop_short(price, atr)

            # Only ratchet downward
            prev  = state["trailing_stops"].get(symbol, float("inf"))
            new_trail = min(trail, prev)
            state["trailing_stops"][symbol] = new_trail

            if price >= new_trail:
                log.info(f"Trailing stop HIT (short) {symbol}: price=${price} trail=${new_trail}")
                cover_short(symbol, equity, reason="trailing_stop")
                short_positions.discard(symbol)
                state["trailing_stops"].pop(symbol, None)

        except Exception as e:
            log.warning(f"Trailing stop error (short) {symbol}: {e}")

    save_state(state)


# ---------------------------------------------------------------------------
# Screener
# ---------------------------------------------------------------------------
def run_screener(universe: list[str]) -> list[str]:
    shortlist = []
    for i in range(0, len(universe), BATCH_SIZE):
        batch = universe[i:i + BATCH_SIZE]
        try:
            batch_bars = get_bars_batch(batch)
            available  = set(batch_bars.index.get_level_values(0))
            for symbol in batch:
                if symbol not in available:
                    continue
                sym_bars = batch_bars.loc[symbol].reset_index()
                if passes_screen(symbol, sym_bars):
                    shortlist.append(symbol)
        except Exception as e:
            log.warning(f"Batch screen error {i}-{i+BATCH_SIZE}: {e}")
    log.info(f"Screened {len(universe)} tickers -> {len(shortlist)} candidates")
    return shortlist


# ---------------------------------------------------------------------------
# Symbol processor
# ---------------------------------------------------------------------------
def process_symbol(symbol: str,
                   df_daily, df_15m,
                   equity: float,
                   long_positions: set, short_positions: set,
                   spy_bullish: bool,
                   state: dict) -> None:

    daily_trend = get_daily_trend(df_daily)
    signal      = get_intraday_signal(df_15m, daily_trend)
    price       = float(df_15m.iloc[-1]["close"])
    atr         = calc_atr(df_daily)
    side        = get_position_side(symbol)

    log.info(f"{symbol} | trend={daily_trend} signal={signal} price=${price:.2f} side={side}")

    if signal == "BUY":
        if side == "short":
            cover_short(symbol, equity, reason="signal_flip")
            short_positions.discard(symbol)
            state["trailing_stops"].pop(symbol, None)
        elif side == "long" or symbol in long_positions:
            log.info(f"HOLD {symbol} — already long")
        elif count_open_positions() < MAX_POSITIONS:
            initial_trail = place_buy(symbol, price, equity, atr)
            long_positions.add(symbol)
            state["trailing_stops"][symbol] = initial_trail
            save_state(state)
        else:
            log.info(f"SKIP {symbol} — max positions reached")

    elif signal == "SELL":
        if side == "long":
            close_long(symbol, equity, reason="signal_flip")
            long_positions.discard(symbol)
            state["trailing_stops"].pop(symbol, None)
        elif side == "short" or symbol in short_positions:
            log.info(f"HOLD {symbol} — already short")
        elif count_open_positions() < MAX_POSITIONS:
            initial_trail = place_short(symbol, price, equity, atr)
            short_positions.add(symbol)
            state["trailing_stops"][symbol] = initial_trail
            save_state(state)
        else:
            log.info(f"SKIP {symbol} — max positions reached")

    else:
        if side == "long":
            log.info(f"Neutral signal — closing long {symbol}")
            close_long(symbol, equity, reason="neutral")
            long_positions.discard(symbol)
            state["trailing_stops"].pop(symbol, None)
        elif side == "short":
            log.info(f"Neutral signal — covering short {symbol}")
            cover_short(symbol, equity, reason="neutral")
            short_positions.discard(symbol)
            state["trailing_stops"].pop(symbol, None)
        else:
            log.info(f"No action for {symbol}")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def run():
    log.info("=== Bot starting ===")
    state           = load_state()
    equity          = get_equity()
    universe        = get_sp500_tickers()
    shortlist       = []
    long_positions  : set = set()
    short_positions : set = set()
    daily_bars_cache: dict = {}
    market_closed_logged = False
    last_scan       = 0.0

    for pos in client.get_all_positions():
        qty = float(pos.qty)
        if qty > 0:
            long_positions.add(pos.symbol)
            log.info(f"Existing LONG on startup: {pos.symbol}")
        elif qty < 0:
            short_positions.add(pos.symbol)
            log.info(f"Existing SHORT on startup: {pos.symbol}")

    if state.get("start_equity") is None:
        state["start_equity"] = equity
        save_state(state)
        log.info(f"Start equity set: ${equity:.2f}")

    if "trailing_stops" not in state:
        state["trailing_stops"] = {}

    while True:
        try:
            equity = get_equity()

            if not is_market_open():
                if not market_closed_logged:
                    log.info("Market closed. Waiting for open...")
                    market_closed_logged = True
                time.sleep(POLL_INTERVAL_SEC)
                continue

            market_closed_logged = False

            if is_daily_loss_breached(state["start_equity"], equity):
                log.warning("Circuit breaker active. Sleeping 1 hour.")
                time.sleep(3600)
                continue

            # SPY regime
            spy_df      = get_bars("SPY", lookback_days=DAILY_LOOKBACK_DAYS)
            spy_bullish = market_is_bullish(spy_df)
            log.info(f"SPY regime bullish: {spy_bullish}")

            # Re-screen every 5 mins
            now = time.time()
            if now - last_scan >= SCAN_INTERVAL_SEC:
                shortlist = run_screener(universe)
                last_scan = now

            if not shortlist:
                log.info("Shortlist empty — waiting for next scan.")
                time.sleep(POLL_INTERVAL_SEC)
                continue

            # Update trailing stops every loop
            update_trailing_stops(state, equity, long_positions, short_positions, daily_bars_cache)

            # Process shortlist in batches
            for i in range(0, len(shortlist), BATCH_SIZE):
                batch = shortlist[i:i + BATCH_SIZE]
                try:
                    # Fetch both daily and 15m bars in parallel batches
                    daily_batch = get_bars_batch(batch, lookback_days=DAILY_LOOKBACK_DAYS)
                    intra_batch = get_intraday_bars_batch(batch, lookback_days=INTRADAY_LOOKBACK_DAYS)

                    daily_avail = set(daily_batch.index.get_level_values(0))
                    intra_avail = set(intra_batch.index.get_level_values(0))

                    for symbol in batch:
                        if symbol not in daily_avail or symbol not in intra_avail:
                            continue

                        df_daily = daily_batch.loc[symbol].reset_index()
                        df_15m   = intra_batch.loc[symbol].reset_index()

                        # Cache daily bars for trailing stop use
                        daily_bars_cache[symbol] = df_daily

                        log.info(f"--- Processing {symbol} ---")
                        process_symbol(
                            symbol, df_daily, df_15m,
                            equity, long_positions, short_positions,
                            spy_bullish, state
                        )

                except Exception as e:
                    log.warning(f"Batch process error: {e}")

            log_equity(equity, state["start_equity"])

        except Exception as e:
            log.error(f"Loop error: {e}", exc_info=True)

        log.info(f"Sleeping {POLL_INTERVAL_SEC}s...\n")
        time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    run()