# report.py
import csv
import os
from datetime import datetime

TRADE_LOG  = "trades.csv"
EQUITY_LOG = "equity.csv"


def _append_row(path: str, header: list, row: list):
    file_exists = os.path.exists(path)
    with open(path, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(header)
        writer.writerow(row)


def log_trade(symbol: str, side: str, price: float, qty: int,
              equity: float, sl=None, tp=None):
    _append_row(
        TRADE_LOG,
        ["timestamp", "symbol", "side", "price", "qty", "equity", "stop_loss", "take_profit"],
        [datetime.now().isoformat(), symbol, side, price, qty, equity, sl, tp]
    )


def log_equity(equity: float, start_equity: float):
    pnl = None if start_equity is None else round(equity - start_equity, 2)
    _append_row(
        EQUITY_LOG,
        ["timestamp", "equity", "start_equity", "pnl"],
        [datetime.now().isoformat(), equity, start_equity, pnl]
    )