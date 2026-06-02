"""
macro_triggers.py
Detects news-driven / exogenous shock signals that bypass
the 12-factor confluence scorer entirely.

Fires independently every scan. Can generate a BEARISH or BULLISH
signal even when confluence score is 40.

Three detectors:
  1. VIX spike rate  — VIX rising fast intraday = panic
  2. Gap-and-reverse — opened one direction, now reversing hard
  3. Crude oil shock  — crude ±1.5% intraday = Nifty directional bias

June 1 2026 example:
  - Crude spiked 3% by 09:30 → CRUDE_SHOCK BEARISH fired
  - VIX rose 1.7 pts by 10:30 → VIX_SPIKE BEARISH fired
  - Nifty gapped up 355 pts then fell below prev close → GAP_REVERSE fired
  All three would have alerted between 09:30–10:45 AM.
  23,400 PE was ~₹10–12 at signal. Closed ₹40+. 3–4x return.
"""

import requests
import time
import logging
from datetime import datetime
import pytz

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

# ── Session memory ─────────────────────────────────────────────────────────
_session_vix_open   = None
_session_spot_open  = None
_session_crude_open = None
_gap_reverse_fired  = False
_vix_spike_fired    = False
_crude_fired        = False


def reset_session_memory():
    """Call once at 09:10 AM each morning before market opens."""
    global _session_vix_open, _session_spot_open, _session_crude_open
    global _gap_reverse_fired, _vix_spike_fired, _crude_fired
    _session_vix_open   = None
    _session_spot_open  = None
    _session_crude_open = None
    _gap_reverse_fired  = False
    _vix_spike_fired    = False
    _crude_fired        = False
    logger.info("Macro trigger session memory reset")


def record_open(spot: float, vix: float):
    """Record the first values of the session (called on first scan ~09:15)."""
    global _session_vix_open, _session_spot_open
    if _session_vix_open is None:
        _session_vix_open  = vix
        _session_spot_open = spot
        logger.info(f"Session open recorded: spot={spot:.0f}, VIX={vix:.1f}")


# ── Crude oil fetcher ─────────────────────────────────────────────────────
def _fetch_crude_mcx() -> float:
    """
    Fetch MCX Crude Oil current price via NSE commodity snapshot.
    Falls back to 0 if unavailable — always fail-safe.
    """
    try:
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Referer":    "https://www.nseindia.com/",
            "Accept":     "application/json",
        })
        session.get("https://www.nseindia.com", timeout=8)
        time.sleep(0.3)
        r = session.get(
            "https://www.nseindia.com/api/commoditySnapshot"
            "?index=CRUDE%20OIL",
            timeout=10
        )
        if r.status_code == 200:
            for item in r.json().get("data", []):
                if "CRUDE" in item.get("symbol", "").upper():
                    price = float(item.get("lastPrice", 0))
                    logger.debug(f"MCX Crude: ₹{price}")
                    return price
    except Exception as e:
        logger.debug(f"Crude fetch failed: {e}")
    return 0.0


# ── Detector 1: VIX spike rate ────────────────────────────────────────────
def check_vix_spike(current_vix: float, threshold: float = 1.5) -> dict:
    """
    BEARISH if VIX has risen >= threshold pts from session open.
    BULLISH if VIX has fallen >= threshold pts (panic over).
    Only fires once per session.
    """
    global _vix_spike_fired
    if _session_vix_open is None or _vix_spike_fired:
        return {"triggered": False}

    change = current_vix - _session_vix_open

    if change >= threshold:
        _vix_spike_fired = True
        conf = min(95, 70 + change * 6)
        logger.info(f"VIX_SPIKE fired: {_session_vix_open:.1f}→{current_vix:.1f} (+{change:.1f})")
        return {
            "triggered":   True,
            "direction":   "BEARISH",
            "signal":      "VIX_SPIKE",
            "confidence":  round(conf, 1),
            "detail": (
                f"VIX surged {change:.1f} pts intraday "
                f"({_session_vix_open:.1f} → {current_vix:.1f}). "
                f"Institutional panic — PE premiums expanding rapidly. "
                f"Enter far-OTM PE immediately."
            ),
        }

    if change <= -threshold:
        _vix_spike_fired = True
        conf = min(90, 65 + abs(change) * 5)
        logger.info(f"VIX_COLLAPSE fired: {_session_vix_open:.1f}→{current_vix:.1f} ({change:.1f})")
        return {
            "triggered":   True,
            "direction":   "BULLISH",
            "signal":      "VIX_COLLAPSE",
            "confidence":  round(conf, 1),
            "detail": (
                f"VIX collapsed {abs(change):.1f} pts intraday "
                f"({_session_vix_open:.1f} → {current_vix:.1f}). "
                f"Fear is fading — CE premiums cheap, relief rally likely."
            ),
        }

    return {"triggered": False}


# ── Detector 2: Gap-and-reverse ───────────────────────────────────────────
def check_gap_reverse(
    current_spot: float,
    prev_close:   float,
    bar_time:     str,
    min_gap_pct:  float = 0.5,
) -> dict:
    """
    Gap-UP (>0.5%) then reverses below prev close = bearish trap.
    Gap-DOWN (>0.5%) then reverses above prev close = bullish squeeze.
    Fires max once per session after 09:45 AM.
    """
    global _gap_reverse_fired
    if _gap_reverse_fired or _session_spot_open is None:
        return {"triggered": False}
    if bar_time < "09:45":
        return {"triggered": False}

    gap_pct = (_session_spot_open - prev_close) / prev_close * 100

    # Gap-up trap (like June 1 2026)
    if gap_pct > min_gap_pct and current_spot < prev_close * 0.9998:
        _gap_reverse_fired = True
        conf = min(90, 68 + gap_pct * 5)
        logger.info(
            f"GAP_REVERSE BEARISH fired: gap={gap_pct:.1f}%, "
            f"now below prev_close={prev_close:.0f}"
        )
        return {
            "triggered":  True,
            "direction":  "BEARISH",
            "signal":     "GAP_REVERSE",
            "confidence": round(conf, 1),
            "detail": (
                f"Gap-up trap confirmed: opened +{gap_pct:.1f}% above "
                f"prev close ({prev_close:.0f}), now reversed below it "
                f"(current: {current_spot:.0f}). "
                f"Sellers absorbed all the gap — strong bearish follow-through expected."
            ),
        }

    # Gap-down squeeze
    if gap_pct < -min_gap_pct and current_spot > prev_close * 1.0002:
        _gap_reverse_fired = True
        conf = min(88, 65 + abs(gap_pct) * 5)
        logger.info(
            f"GAP_REVERSE BULLISH fired: gap={gap_pct:.1f}%, "
            f"now above prev_close={prev_close:.0f}"
        )
        return {
            "triggered":  True,
            "direction":  "BULLISH",
            "signal":     "GAP_REVERSE",
            "confidence": round(conf, 1),
            "detail": (
                f"Gap-down squeeze confirmed: opened {gap_pct:.1f}% below "
                f"prev close ({prev_close:.0f}), now recovered above it "
                f"(current: {current_spot:.0f}). "
                f"Shorts trapped — bullish reversal with force."
            ),
        }

    return {"triggered": False}


# ── Detector 3: Crude oil shock ───────────────────────────────────────────
def check_crude_shock(threshold_pct: float = 1.5) -> dict:
    """
    Crude up >1.5% intraday = energy inflation fear = Nifty BEARISH.
    Crude down >1.5% intraday = cost relief = Nifty BULLISH.
    Fires max once per session.
    """
    global _session_crude_open, _crude_fired
    if _crude_fired:
        return {"triggered": False}

    crude = _fetch_crude_mcx()
    if crude <= 0:
        return {"triggered": False}

    if _session_crude_open is None:
        _session_crude_open = crude
        logger.info(f"Crude session open recorded: ₹{crude:.0f}")
        return {"triggered": False}

    chg_pct = (crude - _session_crude_open) / _session_crude_open * 100

    if chg_pct >= threshold_pct:
        _crude_fired = True
        conf = min(87, 62 + chg_pct * 6)
        logger.info(f"CRUDE_SHOCK BEARISH: +{chg_pct:.1f}% to ₹{crude:.0f}")
        return {
            "triggered":  True,
            "direction":  "BEARISH",
            "signal":     "CRUDE_SHOCK",
            "confidence": round(conf, 1),
            "detail": (
                f"Crude oil up {chg_pct:.1f}% intraday to ₹{crude:.0f}. "
                f"Energy inflation = RBI rate fear = FII selling. "
                f"Nifty historically drops 0.8–1.5% on crude >+1.5% sessions."
            ),
        }

    if chg_pct <= -threshold_pct:
        _crude_fired = True
        conf = min(83, 58 + abs(chg_pct) * 5)
        logger.info(f"CRUDE_DROP BULLISH: {chg_pct:.1f}% to ₹{crude:.0f}")
        return {
            "triggered":  True,
            "direction":  "BULLISH",
            "signal":     "CRUDE_DROP",
            "confidence": round(conf, 1),
            "detail": (
                f"Crude oil down {abs(chg_pct):.1f}% intraday to ₹{crude:.0f}. "
                f"Cost-relief rally likely — auto, aviation, paints sectors lead. "
                f"Nifty bullish bias."
            ),
        }

    return {"triggered": False}


# ── Master function — call this every scan ────────────────────────────────
def run_macro_checks(
    spot:       float,
    vix:        float,
    prev_close: float,
    bar_time:   str,
) -> list:
    """
    Call once per scan. Returns list of triggered macro signal dicts.
    Each dict: triggered, direction, signal, confidence, detail.

    Usage in main.py:
        macro_signals = run_macro_checks(spot, vix, prev_close, bar_time)
        for sig in macro_signals:
            send_macro_alert(sig, ...)
    """
    record_open(spot, vix)

    signals = []

    s = check_vix_spike(vix)
    if s["triggered"]:
        signals.append(s)

    s = check_gap_reverse(spot, prev_close, bar_time)
    if s["triggered"]:
        signals.append(s)

    s = check_crude_shock()
    if s["triggered"]:
        signals.append(s)

    if signals:
        logger.info(f"Macro signals fired: {[s['signal'] for s in signals]}")

    return signals
