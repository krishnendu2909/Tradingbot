"""
confluence_scorer.py
Runs all 12 confluence factors, scores 0–100, and builds the signal card.
Mirrors the institutional framework defined in config.
"""

import numpy as np
import pandas as pd
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Tuple
from config import (
    ALERT_SCORE_THRESHOLD,
    EXECUTE_SCORE_THRESHOLD,
    MIN_OTM_DISTANCE_PCT,
    MAX_OTM_DISTANCE_PCT,
    MIN_OPTION_PREMIUM,
    MAX_OPTION_PREMIUM,
    MIN_OI,
    MIN_VOLUME,
)

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
#  DATA CLASSES
# ------------------------------------------------------------------ #

@dataclass
class CheckResult:
    name: str
    passed: bool
    score: float        # contribution to total (0 to weight)
    weight: float       # max possible contribution
    detail: str         # one-line explanation


@dataclass
class SignalCard:
    # Identity
    timestamp: str
    underlying: str
    signal_type: str    # BULLISH / BEARISH / NO_TRADE

    # Scores
    confluence_score: float
    signal_level: str   # EXECUTE / ALERT / NO_TRADE
    checks: List[CheckResult] = field(default_factory=list)

    # Option details (populated only on ALERT/EXECUTE)
    strike: Optional[int]   = None
    option_type: str        = ""   # CE / PE
    expiry: str             = ""
    spot: Optional[float]   = None
    ltp: Optional[float]    = None

    # Levels (populated only on EXECUTE)
    entry: Optional[float]  = None
    stop_loss: Optional[float] = None
    target1: Optional[float]   = None
    target2: Optional[float]   = None
    target3: Optional[float]   = None
    risk_reward: str           = ""
    confidence: str            = ""
    reasoning: str             = ""

    # Market context
    vix: Optional[float]    = None
    pcr: Optional[float]    = None
    max_pain: Optional[int] = None
    fii_net: Optional[float]= None


# ------------------------------------------------------------------ #
#  SCORER
# ------------------------------------------------------------------ #

class ConfluenceScorer:
    """
    12 checks, each weighted. Total possible = 100.
    Weights are tuned so that structural/trend checks dominate,
    and volatility/risk-reward act as gatekeepers.
    """

    WEIGHTS = {
        "market_regime":        10,
        "trend_alignment":      12,
        "ema_structure":        10,
        "vwap_position":         8,
        "volume_expansion":      8,
        "candle_structure":      8,
        "oi_confirmation":      10,
        "pcr_confirmation":      8,
        "volatility_favorable":  8,
        "liquidity":             6,
        "bid_ask":               6,
        "risk_reward":           6,
    }

    def score(self, data: dict) -> SignalCard:
        oc   = data.get("option_chain")
        ohlc = data.get("ohlcv")
        vix  = data.get("vix")
        fii  = data.get("fii_dii")
        hist = data.get("historical")
        ts   = data.get("timestamp")

        spot = oc["spot_price"] if oc else None

        checks: List[CheckResult] = []
        total_score = 0.0

        # --- 1. Market regime ---
        c = self._check_regime(ohlc, hist, vix)
        checks.append(c); total_score += c.score

        # --- 2. Trend alignment (multi-timeframe proxy) ---
        c = self._check_trend_alignment(ohlc, hist)
        checks.append(c); total_score += c.score

        # --- 3. EMA structure (20 > 50 > 200) ---
        c = self._check_ema_structure(hist)
        checks.append(c); total_score += c.score

        # --- 4. VWAP position ---
        c = self._check_vwap(ohlc)
        checks.append(c); total_score += c.score

        # --- 5. Volume expansion ---
        c = self._check_volume(oc)
        checks.append(c); total_score += c.score

        # --- 6. Candle structure ---
        c = self._check_candle(ohlc)
        checks.append(c); total_score += c.score

        # --- 7. OI confirmation ---
        c = self._check_oi(oc)
        checks.append(c); total_score += c.score

        # --- 8. PCR confirmation ---
        c = self._check_pcr(oc)
        checks.append(c); total_score += c.score

        # --- 9. Volatility ---
        c = self._check_volatility(vix)
        checks.append(c); total_score += c.score

        # --- 10. Liquidity ---
        c = self._check_liquidity(oc, spot)
        checks.append(c); total_score += c.score

        # --- 11. Bid-ask (proxy via OI and volume ratio) ---
        c = self._check_bid_ask(oc, spot)
        checks.append(c); total_score += c.score

        # --- 12. Risk-reward (gating check) ---
        direction = self._determine_direction(checks)
        c = self._check_rr(oc, spot, direction, vix)
        checks.append(c); total_score += c.score

        score = round(total_score, 1)

        # Determine signal level
        if score >= EXECUTE_SCORE_THRESHOLD:
            level = "EXECUTE"
        elif score >= ALERT_SCORE_THRESHOLD:
            level = "ALERT"
        else:
            level = "NO_TRADE"

        card = SignalCard(
            timestamp       = ts.strftime("%d-%b-%Y %H:%M IST") if ts else "",
            underlying      = "NIFTY 50",
            signal_type     = direction if level != "NO_TRADE" else "NO_TRADE",
            confluence_score= score,
            signal_level    = level,
            checks          = checks,
            vix             = vix,
            pcr             = oc["pcr"]      if oc else None,
            max_pain        = oc["max_pain"] if oc else None,
            fii_net         = fii["fii_net"] if fii else None,
            spot            = spot,
        )

        if level in ("EXECUTE", "ALERT") and oc:
            self._populate_trade_levels(card, oc, direction, vix)

        logger.info(
            f"Score={score} | Level={level} | Direction={direction} | "
            f"Strike={card.strike} {card.option_type}"
        )
        return card

    # ---------------------------------------------------------------- #
    #  INDIVIDUAL CHECKS
    # ---------------------------------------------------------------- #

    def _check_regime(self, ohlc, hist, vix) -> CheckResult:
        w = self.WEIGHTS["market_regime"]
        if ohlc is None or hist is None:
            return CheckResult("Market regime", False, 0, w, "Data unavailable")

        close = ohlc.get("ltp", 0)
        prev  = ohlc.get("prev", 0)
        day_range = ohlc.get("high", 0) - ohlc.get("low", 0)
        prev_range = hist["close"].diff().abs().mean() if len(hist) > 1 else 0

        # Trending if today's move > 0.6% OR range expansion
        move_pct = abs(close - prev) / prev * 100 if prev else 0
        is_trending = move_pct >= 0.6 or (day_range > prev_range * 1.2)
        is_high_vol  = (vix or 0) > 22
        is_range_bound = move_pct < 0.3 and day_range < prev_range

        if is_high_vol:
            return CheckResult("Market regime", False, 0, w,
                               f"High VIX={vix:.1f} — regime unfavorable")
        if is_trending:
            return CheckResult("Market regime", True, w, w,
                               f"Trending — move={move_pct:.2f}% today")
        if is_range_bound:
            return CheckResult("Market regime", False, w * 0.2, w,
                               f"Range-bound — move only {move_pct:.2f}%")
        return CheckResult("Market regime", True, w * 0.6, w,
                           f"Moderate trend — move={move_pct:.2f}%")

    def _check_trend_alignment(self, ohlc, hist) -> CheckResult:
        w = self.WEIGHTS["trend_alignment"]
        if ohlc is None or hist is None or len(hist) < 5:
            return CheckResult("Trend alignment", False, 0, w, "Insufficient data")

        close = ohlc.get("ltp", 0)
        recent = hist.tail(5)["close"]
        slope = np.polyfit(range(len(recent)), recent.values, 1)[0]

        # Price above recent closes AND slope positive = bullish alignment
        bullish = close > hist["close"].iloc[-1] and slope > 0
        bearish = close < hist["close"].iloc[-1] and slope < 0

        if bullish:
            return CheckResult("Trend alignment", True, w, w,
                               f"Bullish — slope={slope:.1f}, close above recent")
        if bearish:
            return CheckResult("Trend alignment", True, w, w,
                               f"Bearish — slope={slope:.1f}, close below recent")
        return CheckResult("Trend alignment", False, w * 0.3, w,
                           "Mixed signals — no clear alignment")

    def _check_ema_structure(self, hist) -> CheckResult:
        w = self.WEIGHTS["ema_structure"]
        if hist is None or len(hist) < 20:
            return CheckResult("EMA structure", False, 0, w, "Insufficient history")

        last = hist.iloc[-1]
        e20, e50, e200 = last["ema20"], last["ema50"], last["ema200"]

        bullish = e20 > e50 > e200
        bearish = e20 < e50 < e200
        partial = (e20 > e50) or (e20 < e50)

        if bullish:
            return CheckResult("EMA structure", True, w, w,
                               f"EMA20({e20:.0f})>EMA50({e50:.0f})>EMA200({e200:.0f})")
        if bearish:
            return CheckResult("EMA structure", True, w, w,
                               f"EMA20({e20:.0f})<EMA50({e50:.0f})<EMA200({e200:.0f})")
        if partial:
            return CheckResult("EMA structure", True, w * 0.5, w,
                               f"Partial alignment — EMA20={e20:.0f}, EMA50={e50:.0f}")
        return CheckResult("EMA structure", False, 0, w,
                           "EMAs tangled — no structure")

    def _check_vwap(self, ohlc) -> CheckResult:
        w = self.WEIGHTS["vwap_position"]
        if ohlc is None:
            return CheckResult("VWAP", False, 0, w, "No data")
        # Approximate VWAP as (H+L+C)/3 for today (proper VWAP needs tick data)
        h, l, c = ohlc.get("high",0), ohlc.get("low",0), ohlc.get("ltp",0)
        vwap_approx = (h + l + c) / 3
        above = c > vwap_approx * 1.002   # >0.2% above = bullish
        below = c < vwap_approx * 0.998
        near  = abs(c - vwap_approx) / vwap_approx < 0.002

        if above:
            return CheckResult("VWAP", True, w, w,
                               f"LTP {c:.0f} above VWAP≈{vwap_approx:.0f}")
        if below:
            return CheckResult("VWAP", True, w, w,
                               f"LTP {c:.0f} below VWAP≈{vwap_approx:.0f}")
        return CheckResult("VWAP", False, w * 0.4, w,
                           f"LTP {c:.0f} hugging VWAP≈{vwap_approx:.0f}")

    def _check_volume(self, oc) -> CheckResult:
        w = self.WEIGHTS["volume_expansion"]
        if oc is None:
            return CheckResult("Volume expansion", False, 0, w, "No data")
        df = oc["df"]
        spot = oc["spot_price"]
        atm  = oc["atm_strike"]

        # Check ATM volume is healthy (proxy for overall participation)
        atm_df = df[df["strike"] == atm]
        if atm_df.empty:
            return CheckResult("Volume expansion", False, 0, w, "ATM row missing")

        atm_ce_vol = atm_df.iloc[0]["ce_vol"]
        atm_pe_vol = atm_df.iloc[0]["pe_vol"]
        total_atm_vol = atm_ce_vol + atm_pe_vol

        if total_atm_vol > 50_000:
            return CheckResult("Volume expansion", True, w, w,
                               f"ATM volume={total_atm_vol:,.0f} — strong participation")
        if total_atm_vol > 15_000:
            return CheckResult("Volume expansion", True, w * 0.6, w,
                               f"ATM volume={total_atm_vol:,.0f} — moderate")
        return CheckResult("Volume expansion", False, 0, w,
                           f"ATM volume={total_atm_vol:,.0f} — thin")

    def _check_candle(self, ohlc) -> CheckResult:
        w = self.WEIGHTS["candle_structure"]
        if ohlc is None:
            return CheckResult("Candle structure", False, 0, w, "No data")

        o, h, l, c = ohlc.get("open",0), ohlc.get("high",0), ohlc.get("low",0), ohlc.get("ltp",0)
        body   = abs(c - o)
        total  = h - l if h > l else 1
        body_r = body / total

        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - l

        # Strong bullish: large body, close near high, small upper wick
        strong_bull = body_r > 0.6 and c > o and upper_wick < body * 0.3
        # Strong bearish: large body, close near low, small lower wick
        strong_bear = body_r > 0.6 and c < o and lower_wick < body * 0.3
        # Doji / indecision
        doji = body_r < 0.2

        if strong_bull:
            return CheckResult("Candle structure", True, w, w,
                               f"Strong bull candle — body ratio={body_r:.2f}")
        if strong_bear:
            return CheckResult("Candle structure", True, w, w,
                               f"Strong bear candle — body ratio={body_r:.2f}")
        if doji:
            return CheckResult("Candle structure", False, 0, w,
                               f"Doji / indecision — body ratio={body_r:.2f}")
        return CheckResult("Candle structure", True, w * 0.5, w,
                           f"Moderate candle — body ratio={body_r:.2f}")

    def _check_oi(self, oc) -> CheckResult:
        w = self.WEIGHTS["oi_confirmation"]
        if oc is None:
            return CheckResult("OI confirmation", False, 0, w, "No data")

        df   = oc["df"]
        spot = oc["spot_price"]

        # Call OI concentrated above spot = resistance = bearish for calls
        # Put OI concentrated below spot = support = bullish for puts
        calls_above = df[df["strike"] > spot]["ce_oi"].sum()
        puts_below  = df[df["strike"] < spot]["pe_oi"].sum()

        # OI change — net new put writing (bullish) or call writing (bearish)
        net_put_write  = df[df["strike"] < spot]["pe_chg_oi"].sum()
        net_call_write = df[df["strike"] > spot]["ce_chg_oi"].sum()

        dominant = "put_write" if net_put_write > net_call_write else "call_write"
        ratio = calls_above / (puts_below + 1)

        if dominant == "put_write" and ratio < 1.5:
            return CheckResult("OI confirmation", True, w, w,
                               f"Put writing dominant — bullish support building")
        if dominant == "call_write" and ratio > 1.5:
            return CheckResult("OI confirmation", True, w, w,
                               f"Call writing dominant — bearish resistance building")
        return CheckResult("OI confirmation", False, w * 0.3, w,
                           f"Mixed OI — no clear smart money direction")

    def _check_pcr(self, oc) -> CheckResult:
        w = self.WEIGHTS["pcr_confirmation"]
        if oc is None:
            return CheckResult("PCR", False, 0, w, "No data")
        pcr = oc["pcr"]

        # PCR > 1.2 = heavy put writing = bullish
        # PCR < 0.8 = heavy call writing = bearish
        # 0.8–1.2 = neutral range
        if pcr >= 1.2:
            return CheckResult("PCR", True, w, w,
                               f"PCR={pcr} — bullish (put writers dominant)")
        if pcr <= 0.8:
            return CheckResult("PCR", True, w, w,
                               f"PCR={pcr} — bearish (call writers dominant)")
        return CheckResult("PCR", False, w * 0.2, w,
                           f"PCR={pcr} — neutral zone (0.8–1.2)")

    def _check_volatility(self, vix) -> CheckResult:
        w = self.WEIGHTS["volatility_favorable"]
        if vix is None:
            return CheckResult("Volatility (VIX)", False, 0, w, "VIX unavailable")

        # For far OTM buyers: LOW VIX is ideal (cheap premium)
        # VIX < 13 = excellent, 13-17 = good, 17-22 = caution, >22 = avoid
        if vix < 13:
            return CheckResult("Volatility (VIX)", True, w, w,
                               f"VIX={vix:.1f} — excellent, cheap premium")
        if vix <= 17:
            return CheckResult("Volatility (VIX)", True, w * 0.8, w,
                               f"VIX={vix:.1f} — acceptable")
        if vix <= 22:
            return CheckResult("Volatility (VIX)", False, w * 0.3, w,
                               f"VIX={vix:.1f} — elevated, premium expensive")
        return CheckResult("Volatility (VIX)", False, 0, w,
                           f"VIX={vix:.1f} — HIGH, avoid far OTM buys")

    def _check_liquidity(self, oc, spot) -> CheckResult:
        w = self.WEIGHTS["liquidity"]
        if oc is None or spot is None:
            return CheckResult("Liquidity", False, 0, w, "No data")

        df  = oc["df"]
        atm = oc["atm_strike"]

        # Check OTM strike 2–3% away
        target_pct = 0.02
        target_strike_up = round(spot * (1 + target_pct) / 50) * 50
        target_strike_dn = round(spot * (1 - target_pct) / 50) * 50

        otm_up = df[df["strike"] == target_strike_up]
        otm_dn = df[df["strike"] == target_strike_dn]

        ce_oi = otm_up.iloc[0]["ce_oi"] if not otm_up.empty else 0
        pe_oi = otm_dn.iloc[0]["pe_oi"] if not otm_dn.empty else 0
        max_oi = max(ce_oi, pe_oi)

        if max_oi >= MIN_OI:
            return CheckResult("Liquidity", True, w, w,
                               f"OTM OI={max_oi:,.0f} — liquid")
        if max_oi >= MIN_OI * 0.5:
            return CheckResult("Liquidity", True, w * 0.5, w,
                               f"OTM OI={max_oi:,.0f} — thin but tradeable")
        return CheckResult("Liquidity", False, 0, w,
                           f"OTM OI={max_oi:,.0f} — too illiquid")

    def _check_bid_ask(self, oc, spot) -> CheckResult:
        w = self.WEIGHTS["bid_ask"]
        if oc is None or spot is None:
            return CheckResult("Bid-ask spread", False, 0, w, "No data")

        df = oc["df"]
        target_pct = 0.02
        target_strike = round(spot * (1 + target_pct) / 50) * 50
        row = df[df["strike"] == target_strike]

        if row.empty:
            return CheckResult("Bid-ask spread", False, w * 0.5, w,
                               "Strike not in chain")

        ltp = row.iloc[0]["ce_ltp"]
        vol = row.iloc[0]["ce_vol"]

        # Proxy: if volume > MIN_VOLUME and LTP > MIN_PREMIUM, spread is OK
        if ltp >= MIN_OPTION_PREMIUM and vol >= MIN_VOLUME:
            return CheckResult("Bid-ask spread", True, w, w,
                               f"LTP={ltp}, vol={vol:,.0f} — spread acceptable")
        return CheckResult("Bid-ask spread", False, w * 0.3, w,
                           f"LTP={ltp}, vol={vol:,.0f} — wide spread risk")

    def _check_rr(self, oc, spot, direction, vix) -> CheckResult:
        w = self.WEIGHTS["risk_reward"]
        if oc is None or spot is None:
            return CheckResult("Risk-reward >1:3", False, 0, w, "Cannot calculate")

        # For far OTM: if VIX is low and trend is strong, 1:3 is achievable.
        # Rough proxy: if option price is 10–100 and there's a 2%+ move potential.
        df = oc["df"]
        target_pct = 0.02 if direction == "BULLISH" else -0.02
        target_strike = round(spot * (1 + target_pct) / 50) * 50
        col_ltp = "ce_ltp" if direction == "BULLISH" else "pe_ltp"
        row = df[df["strike"] == target_strike]

        if row.empty:
            return CheckResult("Risk-reward >1:3", False, 0, w,
                               "Target strike not in chain")

        ltp = row.iloc[0][col_ltp]
        if ltp <= 0:
            return CheckResult("Risk-reward >1:3", False, 0, w,
                               f"LTP={ltp} — zero premium")

        # If premium < 80 and VIX < 18, a 2x move (RR ~1:2) is plausible
        # If premium < 50 and VIX < 15, 3x is achievable → pass
        if ltp <= 50 and (vix or 99) < 15:
            return CheckResult("Risk-reward >1:3", True, w, w,
                               f"LTP={ltp}, VIX={vix} — RR >1:3 achievable")
        if ltp <= 100 and (vix or 99) < 18:
            return CheckResult("Risk-reward >1:3", True, w * 0.7, w,
                               f"LTP={ltp}, VIX={vix} — RR ~1:2 achievable")
        return CheckResult("Risk-reward >1:3", False, 0, w,
                           f"LTP={ltp}, VIX={vix} — premium too high for RR >1:3")

    # ---------------------------------------------------------------- #
    #  HELPERS
    # ---------------------------------------------------------------- #

    def _determine_direction(self, checks: List[CheckResult]) -> str:
        """Infer BULLISH / BEARISH from check details."""
        bull_signals = sum(1 for c in checks
                           if c.passed and "bull" in c.detail.lower())
        bear_signals = sum(1 for c in checks
                           if c.passed and "bear" in c.detail.lower())
        if bull_signals > bear_signals:
            return "BULLISH"
        if bear_signals > bull_signals:
            return "BEARISH"
        return "NEUTRAL"

    def _populate_trade_levels(self, card: SignalCard, oc: dict,
                                direction: str, vix: float) -> None:
        """
        Select the best far-OTM strike and compute entry/SL/targets.
        For far OTM options:
          - Entry: current LTP
          - SL: 40% below entry (options can decay fast)
          - T1: 60% above entry
          - T2: 120% above entry
          - T3: 200% above entry
        """
        spot = oc["spot_price"]
        df   = oc["df"]
        expiry = oc["expiry"]

        # Distance: 1.5–3% OTM (sweet spot for asymmetric return)
        if direction == "BULLISH":
            lo = spot * (1 + MIN_OTM_DISTANCE_PCT / 100)
            hi = spot * (1 + MAX_OTM_DISTANCE_PCT / 100)
            candidates = df[(df["strike"] >= lo) & (df["strike"] <= hi)].copy()
            candidates = candidates[
                (candidates["ce_ltp"] >= MIN_OPTION_PREMIUM) &
                (candidates["ce_ltp"] <= MAX_OPTION_PREMIUM) &
                (candidates["ce_oi"]  >= MIN_OI) &
                (candidates["ce_vol"] >= MIN_VOLUME)
            ].sort_values("ce_oi", ascending=False)
            opt_type = "CE"
            ltp_col  = "ce_ltp"
        else:
            lo = spot * (1 - MAX_OTM_DISTANCE_PCT / 100)
            hi = spot * (1 - MIN_OTM_DISTANCE_PCT / 100)
            candidates = df[(df["strike"] >= lo) & (df["strike"] <= hi)].copy()
            candidates = candidates[
                (candidates["pe_ltp"] >= MIN_OPTION_PREMIUM) &
                (candidates["pe_ltp"] <= MAX_OPTION_PREMIUM) &
                (candidates["pe_oi"]  >= MIN_OI) &
                (candidates["pe_vol"] >= MIN_VOLUME)
            ].sort_values("pe_oi", ascending=False)
            opt_type = "PE"
            ltp_col  = "pe_ltp"

        if candidates.empty:
            card.reasoning = "No suitable OTM strike found within filters."
            return

        best = candidates.iloc[0]
        ltp  = best[ltp_col]
        strike = int(best["strike"])

        entry = round(ltp, 2)
        sl    = round(entry * 0.40, 2)   # 40% below entry
        t1    = round(entry * 1.60, 2)   # 60% gain
        t2    = round(entry * 2.20, 2)   # 120% gain
        t3    = round(entry * 3.00, 2)   # 200% gain

        rr = f"1 : {round((t1 - entry) / (entry - sl), 1)}"

        card.strike      = strike
        card.option_type = opt_type
        card.expiry      = expiry
        card.ltp         = ltp
        card.entry       = entry
        card.stop_loss   = sl
        card.target1     = t1
        card.target2     = t2
        card.target3     = t3
        card.risk_reward = rr
        card.confidence  = _confidence_label(card.confluence_score)
        card.reasoning   = _build_reasoning(card, oc, direction)


def _confidence_label(score: float) -> str:
    if score >= 92:  return "Very High (92+)"
    if score >= 85:  return "High (85–91)"
    if score >= 80:  return "Moderate-High (80–84)"
    return "Below threshold"


def _build_reasoning(card: SignalCard, oc: dict, direction: str) -> str:
    passed = [c for c in card.checks if c.passed]
    failed = [c for c in card.checks if not c.passed]
    p_names = ", ".join(c.name for c in passed[:4])
    f_names = ", ".join(c.name for c in failed[:3]) if failed else "none"
    return (
        f"{direction} setup on NIFTY. "
        f"Key factors: {p_names}. "
        f"Weak factors: {f_names}. "
        f"Spot={card.spot:.0f}, PCR={card.pcr}, VIX={card.vix:.1f}, "
        f"Max Pain={card.max_pain}."
    )
