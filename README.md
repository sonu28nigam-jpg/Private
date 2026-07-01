# Intraday Stock Screener — Personal Dashboard

A personal-use intraday screener: fetches live/historical data, computes
technical indicators (VWAP, RSI, EMA cross, volume spike), scores news
sentiment, combines both into a ranked list, and gives you one-click
broker deep links.

**This is a personal engineering tool, not financial advice.** Scores are
algorithmic estimates — backtest before trusting them with real money.

---

## 1. Setup

```bash
pip install -r requirements.txt
python -c "import nltk; nltk.download('vader_lexicon')"   # one-time, for sentiment
```

## 2. Configure

Open `config.py` and edit:
- `STOCK_LIST` — your 100 stocks (NSE symbols, no suffix needed — the app
  adds `.NS` automatically for yfinance).
- `TECH_WEIGHT` / `NEWS_WEIGHT` — scoring weights (default 60/40 per the
  original blueprint).
- `KITE_API_KEY` — optional. Leave blank to get a plain "open stock in
  Kite" link. Add your [Kite Connect](https://developers.kite.trade)
  api_key (paid, ~Rs 500/month) for pre-filled one-click basket orders.

## 3. Run

```bash
streamlit run dashboard.py
```

Opens in your browser at `http://localhost:8501`. Click "Run Screener Now"
in the sidebar to fetch fresh data and re-rank.

You can also run pieces standalone for testing:

```bash
python data_fetcher.py    # test live data fetch for one stock
python indicators.py      # test technical scoring on synthetic data
python sentiment.py       # test news sentiment for one stock
python scorer.py          # run the full pipeline, print ranked table
```

---

## How it works

```
data_fetcher.py   -> pulls OHLCV candles (yfinance) + NIFTY trend
indicators.py     -> VWAP, RSI, EMA9/21 cross, volume spike -> tech_score (0-100)
                   -> ATR -> Entry/Stop-Loss/Target (trade_levels())
sentiment.py      -> Google News RSS + VADER sentiment -> news_score (0-100)
scorer.py         -> final_score = tech*0.6 + news*0.4, market-trend filter, sort
                   -> decide_call(): BUY / SHORT / NO_CALL based on CALL_THRESHOLD
trade_log.py      -> SQLite log of every call issued + outcome tracking
dashboard.py       -> Streamlit: Screener tab (call cards) + Trade Log & Performance tab
auto_logger.py     -> standalone script for background 15-min runs (Task Scheduler)
```

**Market trend filter:** if NIFTY 50 is trending down (bearish) for the
day, the list flips to ascending order — weakest stocks bubble to the top
as short-sell candidates, per the original design.

### How Entry / Stop-Loss / Target are calculated

This is a plain formula, not a prediction:

- **Entry** = current price
- **Risk per share** = ATR (14-period Average True Range) × `ATR_MULTIPLIER` (default 1.5)
  — ATR measures how much the stock typically moves, so the stop isn't a random
  fixed % but scales with each stock's actual volatility.
- **Stop-Loss** = Entry − Risk (for BUY) or Entry + Risk (for SHORT)
- **Target** = Entry + (Risk × `RISK_REWARD`) (for BUY) or Entry − (Risk × `RISK_REWARD`)
  — default `RISK_REWARD = 2.0`, i.e. a 1:2 risk-reward setup.
- **Call decision**: a stock only gets a BUY call if `final_score >= CALL_THRESHOLD`
  (default 65), a SHORT call if `final_score <= 100 - CALL_THRESHOLD` (i.e. ≤ 35),
  otherwise it's `NO_CALL` — the score isn't strong enough either way, and the app
  deliberately shows no entry/SL/target rather than guessing.

All four numbers (`ATR_MULTIPLIER`, `RISK_REWARD`, `CALL_THRESHOLD`) are in `config.py`
— tune them based on your backtesting, not gut feeling.

---

## The feedback loop: does the system actually learn?

Every BUY/SHORT call the screener generates is automatically saved to
`trade_log.db` (a local SQLite file). On the **"Trade Log & Performance"**
tab in the dashboard, you mark what actually happened to each open call:

- **Hit Target** — enter the actual exit price
- **Hit Stop-Loss** — enter the actual exit price
- **Manually Closed** — you exited early for your own reasons, enter the price

The app then computes, automatically:
- **Points captured** — actual profit/loss per share (entry vs. your exit)
- **Target miss-by** — how far your exit landed from the original target
  (negative = fell short, positive = beat the target)
- **Overall win rate** and **average points per trade**
- **Win rate broken down by indicator condition** (e.g. does
  `above_vwap=True` actually correlate with wins in your history, or not?)

**Honest limitation:** this is not a black-box "AI that learns by itself."
It's a transparent scoreboard. The app does not automatically rewrite its
own weights — you look at the condition win-rate table and decide whether
to raise/lower a weight in `config.py` (`TECH_POINTS`). That's intentional:
letting a system silently re-tune itself on a small, noisy sample (which
is what daily trades are) is a fast way to overfit to recent randomness.
Don't act on any condition's win rate until you have at least ~20-30
closed trades for it — smaller samples are just noise.

## Getting a call every 15 minutes

Two ways, depending on whether you want the dashboard open or not:

**Option A — dashboard open in browser:**
Tick "Auto-refresh every 15 min" in the sidebar. It re-runs the screener
and logs new calls automatically while the tab stays open. Requires
`streamlit-autorefresh` (already in `requirements.txt`).

**Option B — true background runs, dashboard closed (Windows Task Scheduler):**
Use `auto_logger.py`, a standalone script that runs one screener pass and
logs calls to the same `trade_log.db` the dashboard reads — no browser
needed.

1. Open **Task Scheduler** → Create Task
2. **Trigger:** Daily, repeat every 15 minutes, active only during market
   hours (9:15 AM – 3:30 PM)
3. **Action:** Start a program
   - Program: `C:\path\to\trading_app\venv\Scripts\python.exe`
   - Arguments: `auto_logger.py`
   - Start in: `C:\path\to\trading_app`
4. Open the dashboard any time afterward — every call logged in the
   background will already be there under "Trade Log & Performance."

---

## Known limitations (read before trusting this with money)

0. **Market-hours awareness:** the app checks NSE hours (Mon-Fri,
   9:15 AM - 3:30 PM IST) and shows a clear banner + skips call-logging
   outside them. But `yfinance` itself doesn't know or care that the
   market is closed — it'll still hand back the last available candle
   (e.g. yesterday's closing data) if you force a run. Outside market
   hours, treat everything shown as "what the formula would have said
   off stale data," not a live signal.

1. **Data source is `yfinance`**, which is free but not tick-accurate and
   can lag by 15+ minutes for NSE data, and occasionally rate-limits or
   goes down. For real intraday trading, swap `data_fetcher.py` to use
   Dhan API / Angel One SmartAPI / Fyers WebSocket instead — the rest of
   the app (indicators, scorer, dashboard) doesn't need to change, since
   it only depends on getting a DataFrame with Open/High/Low/Close/Volume.

2. **News sentiment uses VADER**, a rule-based sentiment model — it reads
   headline tone, not financial magnitude. It won't reliably tell "₹500 cr
   order" (very positive) apart from "opened new office" (mildly positive)
   the way a purpose-built financial LLM prompt would. If you want that,
   replace `sentiment.py`'s `score_headline()` with a call to an LLM API
   (e.g. GPT-4o-mini) with a finance-specific prompt.

3. **No backtesting engine included.** Before using this for real trades,
   test your scoring logic against 3-6 months of historical data to see
   whether high-scored stocks actually moved favorably. Watch out for:
   - **Look-ahead bias** — don't let the backtest use information that
     wouldn't have been available at decision time.
   - **Overfitting** — don't tune weights/thresholds so precisely to past
     data that they stop generalizing to new days.

4. **Zerodha deep link** requires a paid Kite Connect subscription for the
   pre-filled basket order. Without it, the TRADE button just opens the
   stock's page in Kite so you still have to click Buy/Sell yourself —
   still saves you from typing the symbol.

5. **No SEBI registration needed** since this is for personal use only.
   If you ever put this on the Play Store or charge money for it, you'd
   need a clear disclaimer that it's an educational tool, not registered
   financial advice.

---

## UI/UX

The dashboard now has a dark trading-terminal look:
- Color-coded call cards (green left-border = BUY, red = SHORT, grey = NO_CALL)
- A summary strip at the top: market status, NIFTY trend, count of BUY/SHORT/NO_CALL
- **Candlestick charts** per stock (Plotly) with Entry/Stop-Loss/Target drawn as
  horizontal lines directly on the chart — toggle on/off in the sidebar
  ("Show candlestick charts") if you want faster loads on mobile data
- Performance tab now shows a horizontal bar chart of win-rate by indicator
  condition instead of a plain table

Theme lives in `.streamlit/config.toml` — change `primaryColor`,
`backgroundColor`, etc. there if you want a different look, or edit the
`CUSTOM_CSS` block at the top of `dashboard.py` for the call-card styling.

## Deploying to Streamlit Cloud (access from your phone, anywhere)

1. **Push this folder to a GitHub repo** (make it **Private**). Easiest
   way without learning git: on GitHub, "New repository" → "uploading an
   existing file" → drag-drop all the files here → "Commit changes."
   The included `.gitignore` keeps `venv/`, `__pycache__/`, `trade_log.db`,
   and local secrets out of the repo.

2. **If you have a Kite Connect api_key, don't hardcode it in `config.py`
   for this step** — `config.py` already reads it from Streamlit's secure
   "Secrets" panel first (`st.secrets`), falling back to a blank local
   value. You'll set the real key in Streamlit Cloud's UI, not in code.

3. Go to **[share.streamlit.io](https://share.streamlit.io)**, sign in
   with GitHub, click **"New app"**, pick your repo, and set the main
   file to `dashboard.py`. Deploy.

4. (Optional) In the deployed app's **Settings → Secrets**, add:
   ```toml
   KITE_API_KEY = "your_actual_key_here"
   ```

5. You'll get a URL like `yourapp.streamlit.app` — open that on your
   phone's browser, bookmark it, done.

**Two things to know about the free tier:**
- **The filesystem resets on redeploys/restarts.** `trade_log.db` (your
  trade history) can get wiped when the app sleeps and restarts after
  inactivity. For a personal tool this is usually fine short-term, but
  if you want your trade history to survive long-term, you'd need to
  swap SQLite for a hosted database (e.g. a free tier of Supabase/Postgres)
  — not required to get started, just something to know.
- **`auto_logger.py` won't run on Streamlit Cloud** — it's designed for
  Windows Task Scheduler on your own PC. On Cloud, use the in-dashboard
  "Auto-refresh every 15 min" checkbox instead (works only while the
  page is open in a browser tab, phone or desktop).

---



- [ ] Swap `data_fetcher.py` to your broker's live WebSocket for real
      tick data instead of yfinance polling.
- [ ] Add a `backtest.py` that replays historical days through
      `scorer.py`'s logic and reports a real success rate.
- [ ] Add `streamlit-autorefresh` for hands-free periodic re-scoring
      during market hours instead of manual "Run Screener Now" clicks.
- [ ] Log every session's rankings to SQLite so you can review "what did
      the app say vs. what actually happened" at day's end.