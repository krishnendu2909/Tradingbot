"""
test_telegram.py
Run this FIRST to verify your Telegram bot works before starting the main system.
    python test_telegram.py
"""

import sys
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from notifier import send_heartbeat, send_telegram
from confluence_scorer import SignalCard, CheckResult
from datetime import datetime

def test_connection():
    print("\nTesting Telegram connection...")

    if TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌  TELEGRAM_BOT_TOKEN not set in config.py")
        print("    Follow SETUP.md Steps 2 and 3 first.")
        sys.exit(1)

    send_heartbeat(
        TELEGRAM_BOT_TOKEN,
        TELEGRAM_CHAT_ID,
        "✅ Telegram connection test PASSED!\nYour Nifty Alert Bot is ready."
    )
    print("✅  Message sent. Check your Telegram now.")


def test_sample_signal():
    """Send a sample execution signal so you can see what it looks like."""
    print("\nSending sample EXECUTION signal...")

    sample = SignalCard(
        timestamp    = datetime.now().strftime("%d-%b-%Y %H:%M IST"),
        underlying   = "NIFTY 50",
        signal_type  = "BULLISH",
        confluence_score = 87.5,
        signal_level = "EXECUTE",
        checks = [
            CheckResult("Market regime",    True,  10,  10, "Trending — move=1.2% today"),
            CheckResult("Trend alignment",  True,  12,  12, "Bullish — slope=+14.2"),
            CheckResult("EMA structure",    True,  10,  10, "EMA20(23750)>EMA50(23400)>EMA200(22900)"),
            CheckResult("VWAP",             True,   8,   8, "LTP 23810 above VWAP≈23640"),
            CheckResult("Volume expansion", True,   8,   8, "ATM volume=82,400 — strong"),
            CheckResult("Candle structure", True,   8,   8, "Strong bull candle — body ratio=0.72"),
            CheckResult("OI confirmation",  True,  10,  10, "Put writing dominant — bullish support building"),
            CheckResult("PCR",              True,   8,   8, "PCR=1.28 — bullish (put writers dominant)"),
            CheckResult("Volatility (VIX)", False,  5,   8, "VIX=14.2 — acceptable"),
            CheckResult("Liquidity",        True,   6,   6, "OTM OI=142,000 — liquid"),
            CheckResult("Bid-ask spread",   True,   6,   6, "LTP=39.90, vol=28,000 — acceptable"),
            CheckResult("Risk-reward >1:3", False,  0,   6, "LTP=39.90, VIX=14.2 — RR ~1:2 achievable"),
        ],
        strike      = 24000,
        option_type = "CE",
        expiry      = "22-May-2026",
        spot        = 23810.0,
        ltp         = 39.90,
        entry       = 39.90,
        stop_loss   = 15.96,
        target1     = 63.84,
        target2     = 87.78,
        target3     = 119.70,
        risk_reward = "1 : 1.5",
        confidence  = "High (85–91)",
        vix         = 14.2,
        pcr         = 1.28,
        max_pain    = 23600,
        fii_net     = -1234.5,
        reasoning   = (
            "BULLISH setup on NIFTY. Key factors: Market regime, Trend alignment, "
            "EMA structure, VWAP, Volume, Candle, OI, PCR all aligned. "
            "Spot=23810, PCR=1.28, VIX=14.2, Max Pain=23600."
        ),
    )

    from notifier import send_telegram
    success = send_telegram(sample, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    if success:
        print("✅  Sample signal sent. Check Telegram!")
    else:
        print("❌  Send failed. Check token and chat ID in config.py")


if __name__ == "__main__":
    test_connection()
    test_sample_signal()
