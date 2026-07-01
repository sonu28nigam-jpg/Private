"""
Technical analysis layer.

All functions take a pandas DataFrame with columns
Open, High, Low, Close, Volume (indexed by datetime) and return
plain floats/bools. No external TA library dependency (keeps
setup simple) — everything is implemented directly with pandas.
"""

import pandas as pd
import numpy as np

from config import TECH_POINTS


def calc_vwap(df: pd.DataFrame) -> pd.Series:
    typical_price = (df["High"] + df["Low"] + df["Close"]) / 3
    vwap = (typical_price * df["Volume"]).cumsum() / df["Volume"].cumsum()
    return vwap


def calc_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    delta = df["Close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calc_ema(df: pd.DataFrame, span: int) -> pd.Series:
    return df["Close"].ewm(span=span, adjust=False).mean()


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Average True Range — measures recent volatility. Used to size
    stop-loss/target distance so they scale with how much the
    stock is actually moving, instead of a fixed % for everything.
    """
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(window=period, min_periods=period).mean()
    return atr


def volume_spike(df: pd.DataFrame, lookback: int = 20, multiplier: float = 2.0) -> bool:
    if len(df) < lookback + 1:
        return False
    avg_vol = df["Volume"].iloc[-(lookback + 1):-1].mean()
    current_vol = df["Volume"].iloc[-1]
    if avg_vol == 0 or np.isnan(avg_vol):
        return False
    return bool(current_vol >= multiplier * avg_vol)


def technical_score(df: pd.DataFrame) -> dict:
    """
    Computes a 0-100 technical score for one stock's candle data,
    plus a breakdown of which conditions fired (useful for the
    dashboard / debugging / backtesting).
    """
    if df.empty or len(df) < 25:
        return {"score": 0, "breakdown": {}, "reason": "insufficient_data"}

    score = 0
    breakdown = {}

    # --- VWAP condition ---
    vwap = calc_vwap(df)
    price = df["Close"].iloc[-1]
    above_vwap = bool(price > vwap.iloc[-1])
    if above_vwap:
        score += TECH_POINTS["vwap"]
    breakdown["above_vwap"] = above_vwap

    # --- RSI condition (sweet spot 40-60, and rising) ---
    rsi = calc_rsi(df)
    rsi_last = rsi.iloc[-1]
    rsi_prev = rsi.iloc[-2] if len(rsi) > 1 else rsi_last
    rsi_ok = bool(pd.notna(rsi_last) and 40 <= rsi_last <= 60 and rsi_last >= rsi_prev)
    if rsi_ok:
        score += TECH_POINTS["rsi"]
    breakdown["rsi"] = None if pd.isna(rsi_last) else round(float(rsi_last), 2)
    breakdown["rsi_in_sweet_spot"] = rsi_ok

    # --- Volume spike ---
    vol_spike = volume_spike(df)
    if vol_spike:
        score += TECH_POINTS["volume_spike"]
    breakdown["volume_spike"] = vol_spike

    # --- EMA 9/21 cross (bullish = EMA9 > EMA21) ---
    ema9 = calc_ema(df, 9)
    ema21 = calc_ema(df, 21)
    bullish_cross = bool(ema9.iloc[-1] > ema21.iloc[-1])
    if bullish_cross:
        score += TECH_POINTS["ema_cross"]
    breakdown["ema9_gt_ema21"] = bullish_cross

    return {"score": score, "breakdown": breakdown, "reason": "ok"}


def trade_levels(df: pd.DataFrame, direction: str = "BUY",
                  atr_multiplier: float = 1.5, risk_reward: float = 2.0) -> dict:
    """
    Converts the current price + volatility into a concrete
    Entry / Stop-Loss / Target, using an ATR-based formula:

        BUY:   entry = last close
               stop_loss = entry - (ATR * atr_multiplier)
               target    = entry + (risk * risk_reward)

        SHORT: entry = last close
               stop_loss = entry + (ATR * atr_multiplier)
               target    = entry - (risk * risk_reward)

    This is a formula, not a prediction — it just converts "how
    much this stock typically moves" (ATR) into a consistent
    risk-managed entry/exit plan. atr_multiplier and risk_reward
    are yours to tune in config.py.
    """
    if df.empty or len(df) < 20:
        return {"entry": None, "stop_loss": None, "target": None,
                "risk_per_share": None, "reason": "insufficient_data"}

    atr = calc_atr(df).iloc[-1]
    entry = float(df["Close"].iloc[-1])

    if pd.isna(atr) or atr <= 0:
        return {"entry": round(entry, 2), "stop_loss": None, "target": None,
                "risk_per_share": None, "reason": "atr_unavailable"}

    atr = float(atr)
    risk = atr * atr_multiplier

    if direction == "BUY":
        stop_loss = entry - risk
        target = entry + (risk * risk_reward)
    else:  # SHORT
        stop_loss = entry + risk
        target = entry - (risk * risk_reward)

    return {
        "entry": round(entry, 2),
        "stop_loss": round(stop_loss, 2),
        "target": round(target, 2),
        "risk_per_share": round(risk, 2),
        "risk_reward": risk_reward,
        "reason": "ok",
    }


if __name__ == "__main__":
    # Quick sanity check with synthetic data
    idx = pd.date_range("2026-06-30 09:15", periods=50, freq="5min")
    rng = np.random.default_rng(42)
    close = 100 + np.cumsum(rng.normal(0, 0.5, 50))
    df = pd.DataFrame({
        "Open": close + rng.normal(0, 0.1, 50),
        "High": close + abs(rng.normal(0, 0.3, 50)),
        "Low": close - abs(rng.normal(0, 0.3, 50)),
        "Close": close,
        "Volume": rng.integers(1000, 5000, 50),
    }, index=idx)
    result = technical_score(df)
    print(result)
    print(trade_levels(df, direction="BUY"))
    print(trade_levels(df, direction="SHORT"))