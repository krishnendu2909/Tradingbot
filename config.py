# ============================================================
#  NIFTY OPTIONS ALERT SYSTEM — CONFIG
# ============================================================

# --- TELEGRAM ---
TELEGRAM_BOT_TOKEN = "8259465333:AAG3Tx6KI7XZVoPBALVg2RsSYg6bIzeWD08"   # from @BotFather
TELEGRAM_CHAT_ID   = "1797060991"     # from @userinfobot

# --- ADAPTIVE SCAN SETTINGS ---
SCAN_INTERVAL_MINUTES       = 1    # base scan every 1 minute
ALERT_MODE_INTERVAL_SECONDS = 30   # when score hits 80, switch to 30-sec scans
EXECUTE_MODE_INTERVAL_SECONDS = 10 # when score hits 85, switch to 10-sec scans
ALERT_MODE_DURATION_MINUTES = 10   # stay in fast mode for 10 min after trigger

ALERT_SCORE_THRESHOLD = 80         # send alert (watch signal)
EXECUTE_SCORE_THRESHOLD = 85       # send execution signal

# --- MARKET HOURS (IST) ---
MARKET_OPEN_HOUR   = 9
MARKET_OPEN_MINUTE = 15
MARKET_CLOSE_HOUR  = 15
MARKET_CLOSE_MINUTE = 25           # stop 5 min before close

# --- OPTION FILTERS ---
MIN_OTM_DISTANCE_PCT  = 0.5        # strike must be >=0.5% OTM
MAX_OTM_DISTANCE_PCT  = 4.0        # but not more than 4% away
MIN_OPTION_PREMIUM    = 10         # minimum LTP in rupees
MAX_OPTION_PREMIUM    = 200        # maximum LTP in rupees
MIN_OI                = 50_000     # minimum open interest (contracts)
MIN_VOLUME            = 5_000      # minimum volume for the day

# --- RISK SETTINGS (for signal card) ---
MAX_RISK_PER_TRADE_PCT = 1.0       # % of account
LOT_SIZE = 75                      # Nifty lot size (verify current)

# --- INDICES TO MONITOR ---
MONITOR_NIFTY      = True
MONITOR_BANK_NIFTY = True       # set True to also scan Bank Nifty

# --- DEBUG ---
DEBUG_MODE = False                 # True = print scores even if market closed
