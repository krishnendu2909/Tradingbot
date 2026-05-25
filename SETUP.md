# NIFTY OPTIONS ALERT SYSTEM — SETUP GUIDE
# Get running in 10 minutes. No paid APIs needed.

## WHAT YOU NEED
- Python 3.9 or higher (check: python --version)
- A Telegram account (you already have one if you use it)
- This folder of files on your computer

---

## STEP 1 — Install Python packages

Open terminal in this folder and run:

    pip install requests pandas numpy python-telegram-bot schedule pytz ta

---

## STEP 2 — Create your Telegram Bot (2 minutes, free forever)

1. Open Telegram and search for:  @BotFather
2. Send:  /newbot
3. Choose a name (e.g.  NiftyAlertBot)
4. Choose a username (e.g.  my_nifty_alert_bot)
5. BotFather gives you a TOKEN — looks like:
       7123456789:AAHdqTcvCH1vGBJ29_Dj5GaJg6a9yB_1234

   Copy it. Paste it into config.py as TELEGRAM_BOT_TOKEN.

---

## STEP 3 — Get your Chat ID

1. In Telegram, search for:  @userinfobot
2. Send:  /start
3. It replies with your ID — a number like  123456789

   Copy it. Paste it into config.py as TELEGRAM_CHAT_ID.

---

## STEP 4 — Edit config.py

Open config.py and set these two lines:

    TELEGRAM_BOT_TOKEN = "7123456789:AAHdqTcvCH1vGBJ29_Dj5GaJg6a9yB_1234"
    TELEGRAM_CHAT_ID   = "123456789"

Optionally adjust:
    SCAN_INTERVAL_MINUTES = 3      # how often to check (3 min recommended)
    ALERT_SCORE_THRESHOLD = 80     # send Telegram alert at this score
    EXECUTE_SCORE_THRESHOLD = 85   # execution signal at this score
    LOT_SIZE = 75                  # verify current Nifty lot size on NSE

---

## STEP 5 — Test it (before market hours is fine)

    python main.py

You will see logs in your terminal. As soon as you start, you get a
confirmation message on Telegram: "Nifty Alert System started".

To test the Telegram connection without waiting for a real signal:
    python test_telegram.py

---

## STEP 6 — Run it during market hours

Leave it running in a terminal window from 09:10 IST.
It auto-stops scanning outside market hours (09:15–15:25 IST).
It auto-skips weekends.
Logs are saved to alert_system.log.

---

## WHAT AN ALERT LOOKS LIKE ON TELEGRAM

    🚀 EXECUTION SIGNAL
    ==============================
    📈 BULLISH | NIFTY 50
    ⏰ 20-May-2026 10:12 IST

    Confluence Score: 87/100
    [████████░░] 87/100 — EXECUTE

    Option: 24000 CE  |  Expiry: 22-May-2026
    Spot: 23,810  |  LTP: ₹39.90

    — TRADE LEVELS —
    📥 Entry:     ₹39.90
    🛑 Stop Loss: ₹15.96  (−40%)
    🎯 Target 1:  ₹63.84  (+60%)
    🎯 Target 2:  ₹87.78  (+120%)
    🎯 Target 3:  ₹119.70  (+200%)
    ⚖️  Risk:Reward: 1 : 1.5
    💡 Confidence: High (85–91)

    — MARKET CONTEXT —
    India VIX: 14.2
    PCR: 1.28
    Max Pain: 23,600
    FII Net: 🔴 ₹-1,234 Cr

    — CHECKS —
    ✅ Market regime: Trending — move=1.2% today
    ✅ Trend alignment: Bullish — slope=positive
    ✅ EMA structure: EMA20(23750)>EMA50(23400)>EMA200(22900)
    ✅ VWAP: LTP 23810 above VWAP≈23640
    ✅ Volume expansion: ATM volume=82,400 — strong
    ✅ Candle structure: Strong bull candle — body ratio=0.72
    ✅ OI confirmation: Put writing dominant — bullish support
    ✅ PCR: PCR=1.28 — bullish (put writers dominant)
    ❌ Volatility (VIX): VIX=14.2 — acceptable
    ✅ Liquidity: OTM OI=142,000 — liquid
    ✅ Bid-ask spread: LTP=39.90, vol=28,000 — acceptable
    ❌ Risk-reward >1:3: LTP=39.90, VIX=14.2 — RR ~1:2 achievable

    ⚠️ For educational use. Not SEBI advice. Trade at your own risk.

---

## RUNNING ON A RASPBERRY PI / ALWAYS-ON MACHINE

To keep it running even after you close the terminal:

    nohup python main.py > output.log 2>&1 &

To stop it:
    kill $(pgrep -f main.py)

---

## FREE CLOUD DEPLOYMENT (Render.com)

1. Create a free account at render.com
2. New → Background Worker → connect your GitHub repo
3. Set environment variables:
   TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
4. Build command:  pip install -r requirements.txt
5. Start command:  python main.py
Render free tier keeps it running 24/7 at zero cost.

---

## IMPORTANT NOTES

- NSE scraping works without any API key but NSE occasionally blocks IPs.
  If you get repeated 403 errors, wait 10 minutes and restart.

- The system uses a 5-minute NSE session cache. If data seems stale,
  restart the script.

- LOT_SIZE must be current. Check NSE's F&O lot size page:
  https://www.nseindia.com/products/content/derivatives/equities/fo_underlying_details.htm

- This system is for educational and personal use. Do not share API tokens.

- SEBI disclaimer: This is not registered investment advice. All signals
  are algorithmic outputs. Final trading decisions are entirely yours.
