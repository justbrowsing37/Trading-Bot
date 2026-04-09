# config.py
import os

API_KEY    = os.getenv("ALPACA_API_KEY")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
PAPER      = True

POLL_INTERVAL_SEC    = 60
MAX_POSITIONS        = 5
MAX_POSITION_VALUE   = 15000  # max $15k per position

RISK_PER_TRADE       = 0.01   # 1% of equity per trade
DAILY_LOSS_LIMIT     = 0.03   # circuit breaker at 3% drawdown
REWARD_RISK_RATIO    = 2.0    # TP = 2x stop distance

ATR_PERIOD           = 14
ATR_STOP_MULTIPLIER  = 2.0

# Trailing stop
TRAILING_ATR_MULTIPLIER = 1.5  # trail by 1.5x ATR behind price

# Timeframes
DAILY_LOOKBACK_DAYS  = 120    # for trend/regime
INTRADAY_LOOKBACK_DAYS = 5    # for 15m entry bars

SPY_MA_PERIOD        = 50

# Scan
SCAN_INTERVAL_SEC    = 300
BATCH_SIZE           = 50
