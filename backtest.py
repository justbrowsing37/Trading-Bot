# backtest.py
"""
Simple event-driven backtester using daily bars from yfinance.

Usage:
    python backtest.py --tickers AAPL MSFT NVDA --start 2022-01-01 --end 2024-01-01

Requires: pip install yfinance
"""
import argparse
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime


# ── Inline copies of strategy/risk so backtest is self-contained ────────────

def sma(series, period):
    return series.rolling(period).mean()

def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def rsi_calc(series, period=14):
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, 1e-9)
    return 100 - (100 / (1 + rs))

ATR_MULT     = 2.0
TRAIL_MULT   = 1.5
RR_RATIO     = 2.0
RISK_PCT     = 0.01
MAX_POS      = 5


def calc_atr_series(df, period=14):
    h, l, c = df["High"], df["Low"], df["Close"]
    tr = pd.concat([(h - l), (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def get_daily_trend(df):
    if len(df) < 50:
        return "neutral"
    c      = df["Close"]
    s50    = sma(c, 50).iloc[-1]
    s200   = sma(c, min(200, len(c)-1)).iloc[-1]
    r      = rsi_calc(c, 14).iloc[-1]
    price  = float(c.iloc[-1])
    if price > s50 and s50 > s200 and r > 50:
        return "bullish"
    if price < s50 and s50 < s200 and r < 50:
        return "bearish"
    return "neutral"


def get_signal_for_bar(df, idx):
    """Generate signal at bar `idx` using data up to and including that bar."""
    window = df.iloc[:idx + 1]
    if len(window) < 50:
        return "HOLD"

    trend = get_daily_trend(window)
    c     = window["Close"]
    v     = window["Volume"]
    s9    = sma(c, 9).iloc[-1]
    s21   = sma(c, 21).iloc[-1]
    r     = rsi_calc(c, 14).iloc[-1]
    price = float(c.iloc[-1])
    avg_v = float(v.tail(20).mean())
    cur_v = float(v.iloc[-1])
    vol_spike = cur_v > avg_v * 1.2

    if trend == "bullish" and s9 > s21 and r > 50 and vol_spike:
        return "BUY"
    if trend == "bearish" and s9 < s21 and r < 50 and vol_spike:
        return "SELL"
    return "HOLD"


# ── Backtester ───────────────────────────────────────────────────────────────

def run_backtest(tickers: list, start: str, end: str, initial_equity: float = 100_000):
    print(f"\n{'='*60}")
    print(f"Backtest: {', '.join(tickers)}")
    print(f"Period  : {start} → {end}")
    print(f"Capital : ${initial_equity:,.2f}")
    print(f"{'='*60}\n")

    # Download data
    raw = yf.download(tickers, start=start, end=end, group_by="ticker", auto_adjust=True, progress=False)

    all_trades   = []
    equity       = initial_equity
    equity_curve = [equity]
    open_positions = {}   # symbol -> {side, entry, qty, trail}

    # Build per-ticker dataframes
    ticker_dfs = {}
    for t in tickers:
        try:
            if len(tickers) == 1:
                df = raw.copy()
            else:
                df = raw[t].copy()
            df.dropna(inplace=True)
            ticker_dfs[t] = df
        except Exception:
            pass

    if not ticker_dfs:
        print("No data fetched. Check tickers.")
        return

    # Align dates
    all_dates = sorted(set.union(*[set(df.index) for df in ticker_dfs.values()]))

    for date in all_dates:
        # Update trailing stops first
        for sym in list(open_positions.keys()):
            if date not in ticker_dfs.get(sym, pd.DataFrame()).index:
                continue
            pos   = open_positions[sym]
            price = float(ticker_dfs[sym].loc[date, "Close"])
            atr   = float(calc_atr_series(ticker_dfs[sym].loc[:date]).iloc[-1])

            if pos["side"] == "long":
                new_trail = price - TRAIL_MULT * atr
                pos["trail"] = max(pos["trail"], new_trail)
                if price <= pos["trail"]:
                    pnl = (price - pos["entry"]) * pos["qty"]
                    equity += pnl
                    all_trades.append({"date": date, "symbol": sym, "side": "long",
                                       "entry": pos["entry"], "exit": price,
                                       "qty": pos["qty"], "pnl": pnl, "reason": "trail"})
                    del open_positions[sym]

            elif pos["side"] == "short":
                new_trail = price + TRAIL_MULT * atr
                pos["trail"] = min(pos["trail"], new_trail)
                if price >= pos["trail"]:
                    pnl = (pos["entry"] - price) * pos["qty"]
                    equity += pnl
                    all_trades.append({"date": date, "symbol": sym, "side": "short",
                                       "entry": pos["entry"], "exit": price,
                                       "qty": pos["qty"], "pnl": pnl, "reason": "trail"})
                    del open_positions[sym]

        # Generate signals
        for sym, df in ticker_dfs.items():
            if date not in df.index:
                continue
            idx = df.index.get_loc(date)
            signal = get_signal_for_bar(df, idx)
            price  = float(df.loc[date, "Close"])
            atr_s  = calc_atr_series(df.iloc[:idx+1])
            if atr_s.isna().all():
                continue
            atr = float(atr_s.iloc[-1])

            if signal == "BUY" and sym not in open_positions:
                if len(open_positions) >= MAX_POS:
                    continue
                sl  = price - ATR_MULT * atr
                qty = max(int((equity * RISK_PCT) // (price - sl)), 1)
                trail = sl
                open_positions[sym] = {"side": "long", "entry": price, "qty": qty, "trail": trail}

            elif signal == "SELL" and sym not in open_positions:
                if len(open_positions) >= MAX_POS:
                    continue
                sl  = price + ATR_MULT * atr
                qty = max(int((equity * RISK_PCT) // (sl - price)), 1)
                trail = sl
                open_positions[sym] = {"side": "short", "entry": price, "qty": qty, "trail": trail}

            elif signal == "HOLD" and sym in open_positions:
                pos = open_positions[sym]
                pnl = (price - pos["entry"]) * pos["qty"] if pos["side"] == "long" \
                      else (pos["entry"] - price) * pos["qty"]
                equity += pnl
                all_trades.append({"date": date, "symbol": sym, "side": pos["side"],
                                   "entry": pos["entry"], "exit": price,
                                   "qty": pos["qty"], "pnl": pnl, "reason": "signal"})
                del open_positions[sym]

        equity_curve.append(equity)

    # Close remaining
    for sym, pos in open_positions.items():
        df = ticker_dfs.get(sym)
        if df is None or df.empty:
            continue
        price = float(df["Close"].iloc[-1])
        pnl   = (price - pos["entry"]) * pos["qty"] if pos["side"] == "long" \
                else (pos["entry"] - price) * pos["qty"]
        equity += pnl
        all_trades.append({"date": all_dates[-1], "symbol": sym, "side": pos["side"],
                           "entry": pos["entry"], "exit": price,
                           "qty": pos["qty"], "pnl": pnl, "reason": "eod"})

    # ── Results ──────────────────────────────────────────────────────────────
    trades_df = pd.DataFrame(all_trades)

    if trades_df.empty:
        print("No trades generated.")
        return

    wins       = trades_df[trades_df["pnl"] > 0]
    losses     = trades_df[trades_df["pnl"] <= 0]
    total_pnl  = trades_df["pnl"].sum()
    win_rate   = len(wins) / len(trades_df) * 100
    avg_win    = wins["pnl"].mean() if len(wins) > 0 else 0
    avg_loss   = losses["pnl"].mean() if len(losses) > 0 else 0
    profit_factor = abs(wins["pnl"].sum() / losses["pnl"].sum()) if len(losses) > 0 else float("inf")

    eq   = pd.Series(equity_curve)
    roll_max = eq.cummax()
    dd   = (eq - roll_max) / roll_max
    max_dd = float(dd.min()) * 100

    returns = eq.pct_change().dropna()
    sharpe  = float(returns.mean() / returns.std() * np.sqrt(252)) if returns.std() > 0 else 0

    print(f"Total trades     : {len(trades_df)}")
    print(f"Win rate         : {win_rate:.1f}%")
    print(f"Avg win          : ${avg_win:,.2f}")
    print(f"Avg loss         : ${avg_loss:,.2f}")
    print(f"Profit factor    : {profit_factor:.2f}")
    print(f"Total P&L        : ${total_pnl:,.2f}")
    print(f"Final equity     : ${equity:,.2f}")
    print(f"Return           : {((equity - initial_equity) / initial_equity * 100):.2f}%")
    print(f"Max drawdown     : {max_dd:.2f}%")
    print(f"Sharpe ratio     : {sharpe:.2f}")
    print(f"\nTop 5 trades by P&L:")
    print(trades_df.nlargest(5, "pnl")[["date","symbol","side","entry","exit","pnl"]].to_string(index=False))
    print(f"\nWorst 5 trades by P&L:")
    print(trades_df.nsmallest(5, "pnl")[["date","symbol","side","entry","exit","pnl"]].to_string(index=False))

    trades_df.to_csv("backtest_trades.csv", index=False)
    print(f"\nFull trade log saved to backtest_trades.csv")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", nargs="+", default=["AAPL","MSFT","NVDA","AMD","TSLA"])
    parser.add_argument("--start",   default="2022-01-01")
    parser.add_argument("--end",     default="2024-01-01")
    parser.add_argument("--equity",  type=float, default=100_000)
    args = parser.parse_args()
    run_backtest(args.tickers, args.start, args.end, args.equity)