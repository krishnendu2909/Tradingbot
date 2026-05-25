"""
main.py
Scheduler — runs the scanner every N minutes during market hours (IST).
Handles startup, shutdown, error recovery, and daily summary.

Run:
    python main.py
"""

import logging
import time
import schedule
from datetime import datetime, time as dtime
import pytz

from config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    SCAN_INTERVAL_MINUTES,
    MARKET_OPEN_HOUR, MARKET_OPEN_MINUTE,
    MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE,
    ALERT_SCORE_THRESHOLD,
    EXECUTE_SCORE_THRESHOLD,
    DEBUG_MODE,
    MONITOR_NIFTY,
)
from data_fetcher import fetch_all_data
from confluence_scorer import ConfluenceScorer
from notifier import send_telegram, send_heartbeat

# ------------------------------------------------------------------ #
#  LOGGING SETUP
# ------------------------------------------------------------------ #
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("alert_system.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("main")

IST = pytz.timezone("Asia/Kolkata")
scorer = ConfluenceScorer()

# Track signals sent to avoid duplicate alerts within the same session
_sent_signals: set = set()   # stores "strike-optiontype-level" keys
_daily_scan_count = 0
_daily_signals_sent = 0


def is_market_open() -> bool:
    if DEBUG_MODE:
        return True
    now = datetime.now(IST)
    if now.weekday() >= 5:   # Saturday=5, Sunday=6
        return False
    market_open  = dtime(MARKET_OPEN_HOUR,  MARKET_OPEN_MINUTE)
    market_close = dtime(MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE)
    return market_open <= now.time() <= market_close


def run_scan() -> None:
    global _daily_scan_count, _daily_signals_sent

    if not is_market_open():
        logger.debug("Market closed — skipping scan")
        return

    _daily_scan_count += 1
    logger.info(f"--- Scan #{_daily_scan_count} starting ---")

    try:
        data = fetch_all_data()

        if not data["fetch_ok"]:
            logger.warning("Data fetch incomplete — skipping this scan")
            return

        if MONITOR_NIFTY:
            card = scorer.score(data)
            score = card.confluence_score

            logger.info(
                f"Score={score} | Level={card.signal_level} | "
                f"Direction={card.signal_type} | Strike={card.strike} {card.option_type}"
            )

            # Deduplication key — don't spam the same signal every 3 min
            dedup_key = f"{card.strike}-{card.option_type}-{card.signal_level}"

            should_notify = (
                score >= ALERT_SCORE_THRESHOLD
                and dedup_key not in _sent_signals
            )

            if should_notify:
                success = send_telegram(card, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
                if success:
                    _sent_signals.add(dedup_key)
                    _daily_signals_sent += 1
                    logger.info(f"Signal sent: {dedup_key}")
            else:
                logger.info(
                    f"No alert — score={score} (threshold={ALERT_SCORE_THRESHOLD}) "
                    f"or duplicate"
                )

    except Exception as e:
        logger.error(f"Scan error: {e}", exc_info=True)
        send_heartbeat(
            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
            f"⚠️ Scanner error at {datetime.now(IST).strftime('%H:%M IST')}:\n{e}"
        )


def reset_daily_state() -> None:
    """Called at market open each day — fresh start."""
    global _sent_signals, _daily_scan_count, _daily_signals_sent
    _sent_signals.clear()
    _daily_scan_count    = 0
    _daily_signals_sent  = 0
    logger.info("Daily state reset")


def send_daily_summary() -> None:
    msg = (
        f"📋 <b>Daily Summary</b>\n"
        f"Scans run: {_daily_scan_count}\n"
        f"Signals sent: {_daily_signals_sent}\n"
        f"Date: {datetime.now(IST).strftime('%d-%b-%Y')}"
    )
    send_heartbeat(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, msg)
    logger.info("Daily summary sent")


def main() -> None:
    logger.info("=" * 50)
    logger.info("  NIFTY OPTIONS ALERT SYSTEM — STARTING")
    logger.info("=" * 50)

    # Validate config
    if TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("Please set TELEGRAM_BOT_TOKEN in config.py before running!")
        print("\n❌  TELEGRAM_BOT_TOKEN not set in config.py — please read SETUP.md\n")
        return

    send_heartbeat(
        TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
        f"✅ Nifty Alert System started\n"
        f"Scanning every {SCAN_INTERVAL_MINUTES} min during 09:15–15:25 IST\n"
        f"Alert threshold: {ALERT_SCORE_THRESHOLD} | Execute threshold: {EXECUTE_SCORE_THRESHOLD}"
    )

    # Schedule scans
    schedule.every(SCAN_INTERVAL_MINUTES).minutes.do(run_scan)

    # Daily reset at 09:10 IST (before market opens)
    schedule.every().day.at("09:10").do(reset_daily_state)

    # Daily summary at 15:35 IST
    schedule.every().day.at("15:35").do(send_daily_summary)

    # Run first scan immediately
    run_scan()

    logger.info(f"Scheduler running — scan every {SCAN_INTERVAL_MINUTES} minutes")
    logger.info("Press Ctrl+C to stop\n")

    try:
        while True:
            schedule.run_pending()
            time.sleep(30)
    except KeyboardInterrupt:
        logger.info("Shutdown requested by user")
        send_heartbeat(
            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
            f"🔴 Nifty Alert System stopped at "
            f"{datetime.now(IST).strftime('%H:%M IST')}"
        )
        logger.info("Goodbye.")


if __name__ == "__main__":
    main()
