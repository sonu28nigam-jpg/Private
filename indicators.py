import pandas as pd
import numpy as np

def calc_vwap(df: pd.DataFrame) -> pd.Series:
    """Calculates Intraday VWAP reset daily at 09:15 AM."""
    typical_price = (df["High"] + df["Low"] + df["Close"]) / 3
    tp_v = typical_price * df["Volume"]
    
    df_temp = df.copy()
    df_temp['Date'] = df_temp.index.date
    
    cum_tp_v = tp_v.groupby(df_temp['Date']).cumsum()
    cum_vol = df_temp['Volume'].groupby(df_temp['Date']).cumsum()
    
    return cum_tp_v / cum_vol.replace(0, np.nan)

def calc_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    delta = df["Close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def calc_ema(df: pd.DataFrame, span: int) -> pd.Series:
    return df["Close"].ewm(span=span, adjust=False).mean()

def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.rolling(window=period, min_periods=period).mean()

def calc_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculates Average Directional Index (ADX) for Trend Strength."""
    high, low, close = df["High"], df["Low"], df["Close"]
    plus_dm = high.diff()
    minus_dm = low.diff().abs()
    
    plus_dm = np.where((plus_dm > minus_dm) & (plus_dm > 0), plus_dm, 0.0)
    minus_dm = np.where((minus_dm > plus_dm) & (minus_dm > 0), minus_dm, 0.0)
    
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    
    plus_di = 100 * (pd.Series(plus_dm, index=df.index).rolling(period).mean() / atr)
    minus_di = 100 * (pd.Series(minus_dm, index=df.index).rolling(period).mean() / atr)
    
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, np.nan)) * 100
    adx = dx.rolling(period).mean()
    return adx.fillna(0)

def classify_strategy(direction, bull_vwap, bear_vwap, vol_score, adx_score, bull_ema, bear_ema, nifty_aligned):
    """
    🤖 AUTO-DETECTS the basis a call was generated on — feeds directly into
    trade_log's `strategy` column so the dashboard shows it automatically,
    with no manual selection needed.

    Uses the SAME sub-scores technical_score() already calculates, so this
    is not a guess bolted on after the fact — it reflects what actually
    drove the score.

    Priority (most specific / strongest signal first):
      1. BREAKOUT  — price stretched far from VWAP AND a volume spike confirms it
      2. MOMENTUM  — strong trend strength (ADX) with expanding EMA momentum
      3. REVERSAL  — stock moving counter to the broader NIFTY trend
      4. SCREENER_DEFAULT — none of the above stood out; matched on general score
    """
    vwap_component = bull_vwap if direction == "BUY" else bear_vwap
    ema_component = bull_ema if direction == "BUY" else bear_ema

    if vwap_component >= 25 and vol_score >= 12:
        return "BREAKOUT"

    if adx_score >= 10 and ema_component >= 15:
        return "MOMENTUM"

    if not nifty_aligned:
        return "REVERSAL"

    return "SCREENER_DEFAULT"


def technical_score(df: pd.DataFrame, nifty_trend: int = 0) -> dict:
    """
    Graduated Scoring System (Max 100 Confidence Points).
    nifty_trend: +1 (Bullish), -1 (Bearish), 0 (Neutral)
    """
    if df.empty or len(df) < 50:
        return {"score": 0, "direction": "NO_CALL", "strategy": "SCREENER_DEFAULT", "breakdown": {}, "reason": "insufficient_data"}

    vwap = calc_vwap(df).iloc[-1]
    price = df["Close"].iloc[-1]
    rsi = calc_rsi(df).iloc[-1]
    ema9 = calc_ema(df, 9)
    ema21 = calc_ema(df, 21)
    ema50 = calc_ema(df, 50)
    adx = calc_adx(df).iloc[-1]
    
    vol_curr = df["Volume"].iloc[-1]
    vol_prev = df["Volume"].iloc[-2]
    vol_avg20 = df["Volume"].iloc[-21:-1].mean()

    # --- 1. GRADUATED VWAP SCORING (Max 25 pts) ---
    vwap_pct_diff = ((price - vwap) / vwap) * 100
    bull_vwap, bear_vwap = 0, 0
    if vwap_pct_diff > 0.4: bull_vwap = 25
    elif 0 < vwap_pct_diff <= 0.4: bull_vwap = 15
    elif -0.4 <= vwap_pct_diff < 0: bear_vwap = 15
    elif vwap_pct_diff < -0.4: bear_vwap = 25

    # --- 2. ENHANCED VOLUME SPIKE (Max 20 pts) ---
    vol_score = 0
    if vol_curr > (1.3 * vol_avg20) and vol_curr > vol_prev:
        vol_score = 20
    elif vol_curr > (1.3 * vol_avg20):
        vol_score = 12

    # --- 3. STRICT RSI SEPARATION (Max 15 pts) ---
    bull_rsi, bear_rsi = 0, 0
    if pd.notna(rsi):
        if 55 <= rsi <= 75: bull_rsi = 15
        elif 50 <= rsi < 55: bull_rsi = 7
        elif 25 <= rsi <= 45: bear_rsi = 15
        elif 45 < rsi <= 50: bear_rsi = 7

    # --- 4. EMA CROSSOVER & MOMENTUM DISTANCE (Max 15 pts) ---
    e9_curr, e21_curr = ema9.iloc[-1], ema21.iloc[-1]
    e9_prev, e21_prev = ema9.iloc[-2], ema21.iloc[-2]
    curr_diff = e9_curr - e21_curr
    prev_diff = e9_prev - e21_prev
    
    bull_ema, bear_ema = 0, 0
    if curr_diff > 0:
        bull_ema = 15 if curr_diff > prev_diff else 10  # Momentum expanding
    elif curr_diff < 0:
        bear_ema = 15 if abs(curr_diff) > abs(prev_diff) else 10

    # --- 5. EMA 50 TREND & SLOPE (Max 15 pts) ---
    e50_curr = ema50.iloc[-1]
    e50_prev5 = ema50.iloc[-6] if len(ema50) >= 6 else e50_curr
    bull_trend, bear_trend = 0, 0
    
    if price > e50_curr:
        bull_trend = 15 if e50_curr > e50_prev5 else 10  # Upward slope
    elif price < e50_curr:
        bear_trend = 15 if e50_curr < e50_prev5 else 10  # Downward slope

    # --- 6. ADX TREND STRENGTH (Max 10 pts) ---
    adx_score = 10 if adx >= 25 else (5 if adx >= 20 else 0)

    # --- CALCULATE TOTAL SCORES ---
    total_bull = bull_vwap + vol_score + bull_rsi + bull_ema + bull_trend + adx_score
    total_bear = bear_vwap + vol_score + bear_rsi + bear_ema + bear_trend + adx_score

    # --- 7. MARKET TREND (NIFTY ALIGNMENT) PENALTY / BONUS ---
    if nifty_trend == 1:
        total_bull += 5
        total_bear -= 10
    elif nifty_trend == -1:
        total_bear += 5
        total_bull -= 10

    total_bull = max(0, min(100, total_bull))
    total_bear = max(0, min(100, total_bear))

    if total_bull >= total_bear and total_bull > 0:
        final_score = total_bull
        direction = "BUY"
    else:
        final_score = total_bear
        direction = "SHORT"

    nifty_aligned = (direction == "BUY" and nifty_trend == 1) or (direction == "SHORT" and nifty_trend == -1)

    breakdown = {
        "vwap": "STRONG" if vwap_pct_diff > 0.4 else ("WEAK" if vwap_pct_diff > 0 else "BEARISH"),
        "rsi": round(float(rsi), 1) if pd.notna(rsi) else 50,
        "adx": round(float(adx), 1),
        "vol_spike": vol_score > 0,
        "nifty_aligned": nifty_aligned,
        "direction": direction
    }

    strategy = classify_strategy(
        direction=direction,
        bull_vwap=bull_vwap, bear_vwap=bear_vwap,
        vol_score=vol_score,
        adx_score=adx_score,
        bull_ema=bull_ema, bear_ema=bear_ema,
        nifty_aligned=nifty_aligned,
    )
    breakdown["strategy"] = strategy

    return {"score": final_score, "direction": direction, "strategy": strategy, "breakdown": breakdown, "reason": "ok"}

def trade_levels(df: pd.DataFrame, direction: str = "BUY", risk_reward: float = 2.0) -> dict:
    """Dynamic ATR-based SL & Target depending on Volatility %."""
    if df.empty or len(df) < 20:
        return {"entry": None, "stop_loss": None, "target": None, "reason": "insufficient_data"}

    atr = calc_atr(df).iloc[-1]
    entry = float(df["Close"].iloc[-1])

    if pd.isna(atr) or atr <= 0 or entry <= 0:
        return {"entry": round(entry, 2), "stop_loss": None, "target": None, "reason": "atr_unavailable"}

    atr_pct = (atr / entry) * 100

    # Dynamic ATR Multiplier logic based on volatility
    if atr_pct < 0.8:
        atr_multiplier = 1.0  # Low volatility
    elif atr_pct >= 2.0:
        atr_multiplier = 2.0  # High volatility
    else:
        atr_multiplier = 1.5  # Standard volatility

    risk = float(atr) * atr_multiplier
    if direction == "BUY":
        stop_loss = entry - risk
        target = entry + (risk * risk_reward)
    else:
        stop_loss = entry + risk
        target = entry - (risk * risk_reward)

    return {
        "entry": round(entry, 2),
        "stop_loss": round(stop_loss, 2),
        "target": round(target, 2),
        "risk_per_share": round(risk, 2),
        "atr_pct": round(atr_pct, 2),
        "reason": "ok",
    }