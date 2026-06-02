"""
notifier.py
Sends formatted signal cards to Telegram.
Telegram is free, instant, and reliable — perfect for trade alerts.
"""

import logging
import requests
from confluence_scorer import SignalCard

logger = logging.getLogger(__name__)


def _telegram_url(token: str, method: str) -> str:
    return f"https://api.telegram.org/bot{token}/{method}"


def send_telegram(card: SignalCard, token: str, chat_id: str) -> bool:
    """Format and send the signal card as a Telegram message."""
    msg = _format_message(card)
    try:
        resp = requests.post(
            _telegram_url(token, "sendMessage"),
            json={
                "chat_id":    chat_id,
                "text":       msg,
                "parse_mode": "HTML",
            },
            timeout=10,
        )
        if resp.status_code == 200:
            logger.info(f"Telegram message sent — score={card.confluence_score}")
            return True
        else:
            logger.error(f"Telegram error {resp.status_code}: {resp.text}")
            return False
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")
        return False


def _format_message(card: SignalCard) -> str:
    """Build a clean, information-dense Telegram message."""

    # Signal type emoji and header
    if card.signal_level == "EXECUTE":
        header = "🚀 EXECUTION SIGNAL"
        border = "=" * 30
    elif card.signal_level == "ALERT":
        header = "⚡ SETUP ALERT (Watch)"
        border = "-" * 30
    else:
        header = "📊 SCAN UPDATE — NO TRADE"
        border = "-" * 30

    direction_icon = "📈" if card.signal_type == "BULLISH" else (
                     "📉" if card.signal_type == "BEARISH" else "➡️")

    lines = [
        f"<b>{header}</b>",
        border,
        f"{direction_icon} <b>{card.signal_type}</b> | {card.underlying}",
        f"⏰ {card.timestamp}",
        "",
        f"<b>Confluence Score: {card.confluence_score}/100</b>",
        _score_bar(card.confluence_score),
        "",
    ]

    # Option details — only when we have a strike
    if card.strike:
        lines += [
            f"<b>Option:</b> {card.strike} {card.option_type}  |  Expiry: {card.expiry}",
            f"<b>Spot:</b> {card.spot:,.0f}  |  LTP: ₹{card.ltp}",
            "",
        ]

    # Trade levels — only on EXECUTE
    if card.signal_level == "EXECUTE" and card.entry:
        lines += [
            "— TRADE LEVELS —",
            f"📥 <b>Entry:</b>     ₹{card.entry}",
            f"🛑 <b>Stop Loss:</b> ₹{card.stop_loss}  (−40%)",
            f"🎯 <b>Target 1:</b>  ₹{card.target1}  (+60%)",
            f"🎯 <b>Target 2:</b>  ₹{card.target2}  (+120%)",
            f"🎯 <b>Target 3:</b>  ₹{card.target3}  (+200%)",
            f"⚖️  <b>Risk:Reward:</b> {card.risk_reward}",
            f"💡 <b>Confidence:</b> {card.confidence}",
            "",
        ]

    # Market context
    fii_icon = "🔴" if (card.fii_net or 0) < 0 else "🟢"
    lines += [
        "— MARKET CONTEXT —",
        f"India VIX: {card.vix:.1f}" if card.vix else "India VIX: N/A",
        f"PCR: {card.pcr}" if card.pcr else "PCR: N/A",
        f"Max Pain: {card.max_pain:,}" if card.max_pain else "Max Pain: N/A",
        f"FII Net: {fii_icon} ₹{card.fii_net:,.0f} Cr" if card.fii_net else "FII: N/A",
        "",
    ]

    # Confluence checklist
    lines.append("— CHECKS —")
    for c in card.checks:
        icon = "✅" if c.passed else "❌"
        lines.append(f"{icon} {c.name}: {c.detail}")

    if card.reasoning:
        lines += ["", f"<i>{card.reasoning}</i>"]

    lines += [
        "",
        "⚠️ <i>For educational use. Not SEBI advice. Trade at your own risk.</i>",
    ]

    return "\n".join(lines)


def _score_bar(score: float) -> str:
    """ASCII progress bar for the score."""
    filled = int(score / 10)
    empty  = 10 - filled
    bar = "█" * filled + "░" * empty
    label = "NO TRADE" if score < 80 else ("ALERT" if score < 85 else "EXECUTE")
    return f"[{bar}] {score:.0f}/100 — {label}"


def send_heartbeat(token: str, chat_id: str, message: str) -> None:
    """Send a plain status message (startup, shutdown, errors)."""
    try:
        requests.post(
            _telegram_url(token, "sendMessage"),
            json={"chat_id": chat_id, "text": message},
            timeout=10,
        )
    except Exception:
        pass


def send_macro_alert(
    sig: dict, spot: float, vix: float,
    oc, token: str, chat_id: str
) -> bool:
    """Format and send a macro trigger alert (exogenous shock signal)."""
    direction   = sig["direction"]
    signal_name = sig["signal"]
    confidence  = sig["confidence"]
    detail      = sig["detail"]

    icons = {
        "VIX_SPIKE":    "⚡",
        "VIX_COLLAPSE": "💨",
        "GAP_REVERSE":  "🔄",
        "CRUDE_SHOCK":  "🛢️",
        "CRUDE_DROP":   "🟢",
    }
    s_icon = icons.get(signal_name, "🔔")
    d_icon = "📉" if direction == "BEARISH" else "📈"

    ltp_val = 0.0
    strike  = 0
    opt     = "CE" if direction == "BULLISH" else "PE"

    if oc:
        df = oc["df"]
        otm_pct = 0.02
        if direction == "BULLISH":
            strike  = round(spot * (1 + otm_pct) / 50) * 50
            row     = df[df["strike"] == strike]
            ltp_val = float(row.iloc[0]["ce_ltp"]) if not row.empty else 0
        else:
            strike  = round(spot * (1 - otm_pct) / 50) * 50
            row     = df[df["strike"] == strike]
            ltp_val = float(row.iloc[0]["pe_ltp"]) if not row.empty else 0

    sl = round(ltp_val * 0.45, 2)
    t1 = round(ltp_val * 1.80, 2)
    t2 = round(ltp_val * 2.50, 2)
    t3 = round(ltp_val * 3.50, 2)

    lines = [
        f"{s_icon} <b>MACRO TRIGGER — {signal_name}</b>",
        "=" * 28,
        f"{d_icon} <b>{direction}</b> | NIFTY 50",
        f"Spot: {spot:,.0f}  |  VIX: {vix:.1f}",
        "",
        f"<b>Signal:</b> {detail}",
        "",
    ]
    if ltp_val > 0:
        lines += [
            f"<b>Option:</b> {strike} {opt}  |  LTP ₹{ltp_val:.2f}",
            f"📥 <b>Entry:</b>     ₹{ltp_val:.2f}",
            f"🛑 <b>Stop Loss:</b> ₹{sl}  (−45%)",
            f"🎯 <b>T1:</b>        ₹{t1}  (+80%)",
            f"🎯 <b>T2:</b>        ₹{t2}  (+150%)",
            f"🎯 <b>T3:</b>        ₹{t3}  (+250%)",
            "",
        ]
    lines += [
        f"💡 <b>Confidence:</b> {confidence:.0f}%",
        "",
        "<i>⚠️ Macro trigger — exit immediately if trigger reverses.</i>",
        "<i>Not SEBI advice. Trade at your own risk.</i>",
    ]

    try:
        resp = requests.post(
            _telegram_url(token, "sendMessage"),
            json={"chat_id": chat_id, "text": "\n".join(lines), "parse_mode": "HTML"},
            timeout=10,
        )
        if resp.status_code == 200:
            logger.info(f"Macro alert sent: {signal_name}")
            return True
        logger.error(f"Telegram macro error {resp.status_code}: {resp.text}")
    except Exception as e:
        logger.error(f"Macro alert send failed: {e}")
    return False
