"""
main.py  —  Adaptive scanner
Base: 1-minute scans
Alert mode (score ≥80): 30-second scans
Execute mode (score ≥85): 10-second scans
"""

import logging, time, threading
from datetime import datetime, time as dtime
import pytz

from config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
    SCAN_INTERVAL_MINUTES,
    ALERT_MODE_INTERVAL_SECONDS,
    EXECUTE_MODE_INTERVAL_SECONDS,
    ALERT_MODE_DURATION_MINUTES,
    ALERT_SCORE_THRESHOLD, EXECUTE_SCORE_THRESHOLD,
    MARKET_OPEN_HOUR, MARKET_OPEN_MINUTE,
    MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE,
    DEBUG_MODE,
)
from data_fetcher import fetch_all_data
from confluence_scorer import ConfluenceScorer
from notifier import send_telegram, send_heartbeat, send_macro_alert
from macro_triggers import run_macro_checks, reset_session_memory

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

# ── State ─────────────────────────────────────────────────────────────────────
_sent_signals: set = set()
_daily_scan_count  = 0
_daily_signals     = 0
_alert_mode_until  = None   # datetime — when fast scan mode expires
_current_interval  = SCAN_INTERVAL_MINUTES * 60   # seconds
_lock = threading.Lock()

def is_market_open() -> bool:
    if DEBUG_MODE: return True
    now = datetime.now(IST)
    if now.weekday() >= 5: return False
    return dtime(MARKET_OPEN_HOUR, MARKET_OPEN_MINUTE) \
           <= now.time() \
           <= dtime(MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE)

def _get_interval(score: float) -> int:
    """Return scan interval in seconds based on current score."""
    if score >= EXECUTE_SCORE_THRESHOLD:
        return EXECUTE_MODE_INTERVAL_SECONDS   # 10 sec
    if score >= ALERT_SCORE_THRESHOLD:
        return ALERT_MODE_INTERVAL_SECONDS     # 30 sec
    return SCAN_INTERVAL_MINUTES * 60          # 60 sec

def run_scan() -> float:
    """Single scan. Returns score (0 if no data)."""
    global _daily_scan_count, _daily_signals, _alert_mode_until, _current_interval

    if not is_market_open():
        return 0

    _daily_scan_count += 1
    logger.info(f"Scan #{_daily_scan_count} | interval={_current_interval}s")

    try:
        data = fetch_all_data()
        if not data["fetch_ok"]:
            logger.warning("Incomplete data — skipping")
            return 0

        # ── Macro trigger check (independent of confluence score) ──────────
        bar_time   = datetime.now(IST).strftime("%H:%M")
        spot       = data["option_chain"]["spot_price"] if data["option_chain"] else 0
        vix        = data["vix"] or 0
        prev_close = data["ohlcv"]["prev"] if data["ohlcv"] else spot

        macro_signals = run_macro_checks(spot, vix, prev_close, bar_time)
        for sig in macro_signals:
            mk = f"macro-{sig['signal']}-{sig['direction']}"
            if mk not in _sent_signals:
                ok = send_macro_alert(
                    sig, spot, vix, data["option_chain"],
                    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
                )
                if ok:
                    _sent_signals.add(mk)
                    _daily_signals += 1
                    logger.info(f"Macro alert sent: {mk}")

        card  = scorer.score(data)
        score = card.confluence_score

        logger.info(
            f"Score={score} | {card.signal_level} | "
            f"{card.signal_type} | {card.strike} {card.option_type}"
        )

        # ── Adaptive interval ──────────────────────────────────────────────
        with _lock:
            new_interval = _get_interval(score)
            if new_interval < _current_interval:
                _current_interval = new_interval
                _alert_mode_until = datetime.now(IST).replace(tzinfo=None) + \
                                    __import__('datetime').timedelta(
                                        minutes=ALERT_MODE_DURATION_MINUTES)
                logger.info(
                    f"🔥 Switched to {new_interval}s scan mode "
                    f"(score={score})"
                )
                send_heartbeat(
                    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                    f"⚡ Score hit {score:.0f} — scanning every {new_interval}s now"
                )

        # ── Notify ────────────────────────────────────────────────────────
        dedup_key = f"{card.strike}-{card.option_type}-{card.signal_level}"
        if score >= ALERT_SCORE_THRESHOLD and dedup_key not in _sent_signals:
            if send_telegram(card, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID):
                _sent_signals.add(dedup_key)
                _daily_signals += 1

        return score

    except Exception as e:
        logger.error(f"Scan error: {e}", exc_info=True)
        return 0

def _reset_interval_if_expired():
    """If alert mode has expired, go back to base interval."""
    global _alert_mode_until, _current_interval
    with _lock:
        if _alert_mode_until:
            now = datetime.now(IST).replace(tzinfo=None)
            if now > _alert_mode_until:
                _current_interval = SCAN_INTERVAL_MINUTES * 60
                _alert_mode_until = None
                logger.info("Alert mode expired — back to 60s scans")

def main():
    global _current_interval

    logger.info("=" * 50)
    logger.info("  NIFTY OPTIONS ALERT SYSTEM  (Adaptive Scan)")
    logger.info("=" * 50)

    if TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("\n❌  Set TELEGRAM_BOT_TOKEN in config.py first!\n")
        return

    send_heartbeat(
        TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
        f"✅ Adaptive Scanner started\n"
        f"Base: {SCAN_INTERVAL_MINUTES} min | Alert(80+): {ALERT_MODE_INTERVAL_SECONDS}s "
        f"| Execute(85+): {EXECUTE_MODE_INTERVAL_SECONDS}s"
    )

    _current_interval = SCAN_INTERVAL_MINUTES * 60

    # Daily reset at 09:10
    def daily_reset():
        global _sent_signals, _daily_scan_count, _daily_signals, _current_interval
        _sent_signals.clear()
        _daily_scan_count = 0
        _daily_signals    = 0
        _current_interval = SCAN_INTERVAL_MINUTES * 60
        logger.info("Daily reset done")

    import schedule
    schedule.every().day.at("09:10").do(daily_reset)
    schedule.every().day.at("09:10").do(reset_session_memory)
    schedule.every().day.at("15:35").do(
        lambda: send_heartbeat(
            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
            f"📋 Day done | Scans: {_daily_scan_count} | Signals: {_daily_signals}"
        )
    )

    # ── Main adaptive loop ─────────────────────────────────────────────────
    print(f"Running. Base scan: {SCAN_INTERVAL_MINUTES} min | Ctrl+C to stop")
    try:
        while True:
            schedule.run_pending()
            _reset_interval_if_expired()
            run_scan()
            # Sleep in small chunks so schedule tasks fire on time
            elapsed = 0
            chunk   = 5
            while elapsed < _current_interval:
                time.sleep(chunk)
                elapsed += chunk
                schedule.run_pending()
                _reset_interval_if_expired()

    except KeyboardInterrupt:
        send_heartbeat(
            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
            f"🔴 Scanner stopped | {datetime.now(IST).strftime('%H:%M IST')}"
        )
        logger.info("Stopped.")

if __name__ == "__main__":
    main()
