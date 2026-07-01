"""
Presentation Layer — Streamlit dashboard (advanced UI/UX).

Run with:
    streamlit run dashboard.py

Tabs:
1. Screener — ranked call cards (BUY/SHORT/NO_CALL), candlestick charts,
   Entry/SL/Target. Every BUY/SHORT call is auto-logged to trade_log.db.
2. Trade Log & Performance — mark call outcomes, see win-rate stats and
   which indicator conditions actually work, with charts.
"""

import urllib.parse
from datetime import datetime

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from config import (
    STOCK_LIST, KITE_API_KEY, DEFAULT_ORDER_QTY, DEFAULT_PRODUCT,
    AUTO_REFRESH_MINUTES,
)
from scorer import run_screener
from data_fetcher import is_market_open, fetch_candles
import trade_log

st.set_page_config(
    page_title="Intraday Screener",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

try:
    from streamlit_autorefresh import st_autorefresh
    HAS_AUTOREFRESH = True
except ImportError:
    HAS_AUTOREFRESH = False


# ---------------------------------------------------------------
# Styling
# ---------------------------------------------------------------
CUSTOM_CSS = """
<style>
    .stApp { background-color: #0E1117; }

    .call-card {
        border-radius: 14px;
        padding: 18px 20px;
        margin-bottom: 14px;
        border: 1px solid #262B34;
        background: linear-gradient(180deg, #161B22 0%, #12161C 100%);
    }
    .call-card.buy { border-left: 4px solid #00D68F; }
    .call-card.short { border-left: 4px solid #FF4D4D; }
    .call-card.nocall { border-left: 4px solid #6B7280; opacity: 0.85; }

    .badge {
        display: inline-block;
        padding: 3px 12px;
        border-radius: 999px;
        font-weight: 700;
        font-size: 0.78em;
        letter-spacing: 0.03em;
    }
    .badge-buy { background: rgba(0,214,143,0.15); color: #00D68F; }
    .badge-short { background: rgba(255,77,77,0.15); color: #FF4D4D; }
    .badge-nocall { background: rgba(107,114,128,0.2); color: #9CA3AF; }

    .symbol-title { font-size: 1.35em; font-weight: 800; color: #E6EDF3; margin: 0; }
    .rank-tag {
        color: #6B7280; font-size: 0.85em; font-weight: 600;
        margin-right: 6px;
    }
    .metric-box {
        background: #0E1117;
        border: 1px solid #262B34;
        border-radius: 10px;
        padding: 10px 14px;
        text-align: center;
    }
    .metric-label { color: #6B7280; font-size: 0.72em; text-transform: uppercase; letter-spacing: 0.05em; }
    .metric-value { color: #E6EDF3; font-size: 1.15em; font-weight: 700; margin-top: 2px; }
    .metric-value.green { color: #00D68F; }
    .metric-value.red { color: #FF4D4D; }

    .score-pill {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 8px;
        font-size: 0.82em;
        font-weight: 600;
        background: #0E1117;
        border: 1px solid #262B34;
        color: #9CA3AF;
        margin-right: 6px;
    }

    .summary-strip {
        display: flex; gap: 12px; margin-bottom: 22px; flex-wrap: wrap;
    }
    .summary-item {
        flex: 1; min-width: 140px;
        background: #161B22; border: 1px solid #262B34; border-radius: 12px;
        padding: 14px 16px;
    }
    .summary-item .label { color: #6B7280; font-size: 0.75em; text-transform: uppercase; }
    .summary-item .value { color: #E6EDF3; font-size: 1.4em; font-weight: 800; margin-top: 4px; }

    div[data-testid="stExpander"] { border: none; }
    hr { border-color: #262B34; }
</style>
"""


def inject_css():
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def build_trade_link(symbol: str, transaction_type: str = "BUY") -> str:
    if KITE_API_KEY:
        basket = [{
            "variety": "regular",
            "tradingsymbol": symbol,
            "exchange": "NSE",
            "transaction_type": transaction_type,
            "order_type": "MARKET",
            "quantity": DEFAULT_ORDER_QTY,
            "product": DEFAULT_PRODUCT,
        }]
        data = urllib.parse.quote(str(basket).replace("'", '"'))
        return f"https://kite.zerodha.com/connect/basket?api_key={KITE_API_KEY}&data={data}"
    return f"https://kite.zerodha.com/dashboard#/stocks/{symbol}"


def render_candlestick(symbol: str, entry=None, stop_loss=None, target=None):
    """Renders a candlestick chart with entry/SL/target lines overlaid."""
    df = fetch_candles(symbol, interval="15m", period="5d")
    if df.empty:
        st.caption("Chart unavailable (no data returned for this symbol right now).")
        return

    fig = go.Figure(data=[go.Candlestick(
        x=df.index, open=df["Open"], high=df["High"],
        low=df["Low"], close=df["Close"],
        increasing_line_color="#00D68F", decreasing_line_color="#FF4D4D",
        name=symbol,
    )])

    if entry is not None:
        fig.add_hline(y=entry, line_dash="dot", line_color="#9CA3AF",
                       annotation_text="Entry", annotation_position="right")
    if stop_loss is not None:
        fig.add_hline(y=stop_loss, line_dash="dot", line_color="#FF4D4D",
                       annotation_text="Stop-Loss", annotation_position="right")
    if target is not None:
        fig.add_hline(y=target, line_dash="dot", line_color="#00D68F",
                       annotation_text="Target", annotation_position="right")

    fig.update_layout(
        height=320,
        margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor="#0E1117",
        plot_bgcolor="#0E1117",
        font=dict(color="#9CA3AF"),
        xaxis=dict(gridcolor="#262B34", rangeslider_visible=False),
        yaxis=dict(gridcolor="#262B34"),
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def render_summary_strip(df: pd.DataFrame, market_open: bool):
    buy_count = int((df["call"] == "BUY").sum())
    short_count = int((df["call"] == "SHORT").sum())
    no_call_count = int((df["call"] == "NO_CALL").sum())
    market_trend = df["market_trend"].iloc[0]
    trend_emoji = {"bullish": "🟢", "bearish": "🔴", "flat": "⚪"}.get(market_trend, "⚪")
    status_emoji = "🟢 OPEN" if market_open else "🔴 CLOSED"

    st.markdown(f"""
    <div class="summary-strip">
        <div class="summary-item"><div class="label">Market</div><div class="value">{status_emoji}</div></div>
        <div class="summary-item"><div class="label">NIFTY Trend</div><div class="value">{trend_emoji} {market_trend.title()}</div></div>
        <div class="summary-item"><div class="label">Buy Calls</div><div class="value" style="color:#00D68F">{buy_count}</div></div>
        <div class="summary-item"><div class="label">Short Calls</div><div class="value" style="color:#FF4D4D">{short_count}</div></div>
        <div class="summary-item"><div class="label">No Call</div><div class="value" style="color:#9CA3AF">{no_call_count}</div></div>
        <div class="summary-item"><div class="label">Last Updated</div><div class="value" style="font-size:0.95em">{datetime.now().strftime('%I:%M %p')}</div></div>
    </div>
    """, unsafe_allow_html=True)


def render_screener_tab():
    market_open = is_market_open()

    if not market_open:
        st.warning(
            "🕐 **NSE market is currently closed** (Mon-Fri, 9:15 AM - 3:30 PM IST). "
            "Data shown is the last available candle, not live. Calls won't be "
            "auto-logged outside market hours."
        )

    with st.sidebar:
        st.header("⚙️ Settings")
        use_news = st.checkbox("Include news sentiment", value=True)
        top_n = st.slider("Show top N stocks", 5, len(STOCK_LIST), 15)
        show_charts = st.checkbox("Show candlestick charts", value=True)
        run_btn = st.button("🔄 Run Screener Now", type="primary", use_container_width=True)

        if HAS_AUTOREFRESH:
            auto_on = st.checkbox(f"Auto-refresh every {AUTO_REFRESH_MINUTES} min", value=False)
            if auto_on:
                st_autorefresh(interval=AUTO_REFRESH_MINUTES * 60 * 1000, key="auto_refresh")
        else:
            st.caption("Install `streamlit-autorefresh` for in-browser auto-refresh.")
            auto_on = False

    if "results" not in st.session_state:
        st.session_state.results = None

    if run_btn or auto_on or st.session_state.results is None:
        with st.spinner("Fetching data, computing indicators, scoring news..."):
            st.session_state.results = run_screener(use_news=use_news)
            if market_open:
                saved = trade_log.log_calls_bulk(st.session_state.results)
                if saved:
                    st.toast(f"Logged {saved} new call(s)")
            else:
                st.toast("Market closed — calls shown but not logged.")

    df = st.session_state.results

    if df is None or df.empty:
        st.warning(
            "No data returned. Run this on a machine with normal internet access "
            "to Yahoo Finance, or swap in your broker's live data API."
        )
        return

    if "call" not in df.columns:
        st.error("Stale cached results — click 'Run Screener Now' to refresh.")
        st.session_state.results = None
        return

    render_summary_strip(df, market_open)

    if df["market_trend"].iloc[0] == "bearish":
        st.info("Market is bearish — sorted ascending (weakest stocks on top, for short candidates).")

    display_df = df.head(top_n).copy()

    for _, row in display_df.iterrows():
        call = row["call"]
        css_class = {"BUY": "buy", "SHORT": "short", "NO_CALL": "nocall"}[call]
        badge_class = {"BUY": "badge-buy", "SHORT": "badge-short", "NO_CALL": "badge-nocall"}[call]
        badge_text = {"BUY": "🟢 BUY CALL", "SHORT": "🔴 SHORT CALL", "NO_CALL": "⚪ NO CALL"}[call]

        st.markdown(f'<div class="call-card {css_class}">', unsafe_allow_html=True)

        top_cols = st.columns([5, 2])
        with top_cols[0]:
            st.markdown(
                f'<span class="rank-tag">#{row["rank"]}</span>'
                f'<span class="symbol-title">{row["symbol"]}</span>',
                unsafe_allow_html=True,
            )
            st.markdown(
                f'<span class="score-pill">Tech {row["tech_score"]}</span>'
                f'<span class="score-pill">News {row["news_score"]}</span>'
                f'<span class="score-pill">Final {row["final_score"]}</span>',
                unsafe_allow_html=True,
            )
        with top_cols[1]:
            st.markdown(
                f'<div style="text-align:right"><span class="badge {badge_class}">{badge_text}</span></div>',
                unsafe_allow_html=True,
            )

        if call == "NO_CALL":
            st.caption(
                f"Score not strong enough (needs ≥65 BUY / ≤35 SHORT). "
                f"Last price ₹{row['last_price']}. Sitting out is a valid call."
            )
        else:
            m1, m2, m3, m4 = st.columns(4)
            for col, label, val, cls in [
                (m1, "Entry", row["entry"], ""),
                (m2, "Stop-Loss", row["stop_loss"], "red"),
                (m3, "Target", row["target"], "green"),
                (m4, "Risk/Share", row["risk_per_share"], ""),
            ]:
                col.markdown(f"""
                <div class="metric-box">
                    <div class="metric-label">{label}</div>
                    <div class="metric-value {cls}">₹{val}</div>
                </div>
                """, unsafe_allow_html=True)

            st.write("")
            link_cols = st.columns([1, 3])
            trade_type = "BUY" if call == "BUY" else "SELL"
            buy_link = build_trade_link(row["symbol"], trade_type)
            link_cols[0].link_button(f"📲 {trade_type} on Kite", buy_link, use_container_width=True)

            if show_charts:
                render_candlestick(row["symbol"], row["entry"], row["stop_loss"], row["target"])

        with st.expander("Why this call?"):
            st.json(row["breakdown"])
            if row["headlines"]:
                st.write("Recent headlines:")
                for h, s in row["headlines"]:
                    st.write(f"- ({s:+.2f}) {h}")
            else:
                st.write("No recent headlines found / news skipped.")

        st.markdown('</div>', unsafe_allow_html=True)

    if not KITE_API_KEY:
        st.caption("ℹ️ No Kite api_key configured — trade buttons open the stock's Kite page instead of pre-filling an order.")


def render_trade_log_tab():
    st.subheader("📒 Open Calls")
    open_calls = trade_log.get_open_calls()

    if not open_calls:
        st.info("No open calls yet. Run the screener to generate some.")
    else:
        for c in open_calls:
            with st.container(border=True):
                cols = st.columns([2, 2, 2, 2, 2])
                cols[0].markdown(f"**{c['symbol']}** ({c['call_type']})")
                cols[1].markdown(f"Entry: ₹{c['entry']}")
                cols[2].markdown(f"SL: ₹{c['stop_loss']}")
                cols[3].markdown(f"Target: ₹{c['target']}")
                cols[4].markdown(f"{c['issued_at'][:16].replace('T', ' ')}")

                form_cols = st.columns([2, 2, 2])
                status = form_cols[0].selectbox(
                    "Outcome", ["Still Open", "Hit Target", "Hit Stop-Loss", "Manually Closed"],
                    key=f"status_{c['id']}",
                )
                exit_price = None
                if status != "Still Open":
                    exit_price = form_cols[1].number_input(
                        "Actual exit price", min_value=0.0, step=0.05, key=f"exit_{c['id']}"
                    )
                if form_cols[2].button("Save outcome", key=f"save_{c['id']}"):
                    if status == "Still Open":
                        st.warning("Nothing to save — still open.")
                    else:
                        status_map = {
                            "Hit Target": "HIT_TARGET",
                            "Hit Stop-Loss": "HIT_SL",
                            "Manually Closed": "MANUAL_CLOSE",
                        }
                        trade_log.record_outcome(c["id"], status_map[status], exit_price=exit_price)
                        st.success("Saved.")
                        st.rerun()

    st.divider()
    st.subheader("📈 Performance")

    stats = trade_log.performance_summary()
    if stats.get("total_closed", 0) == 0:
        st.info("No closed trades yet — mark outcomes above to build performance stats.")
        return

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Closed trades", stats["total_closed"])
    m2.metric("Win rate", f"{stats['win_rate_pct']}%")
    m3.metric("Wins / Losses", f"{stats['wins']} / {stats['losses']}")
    m4.metric("Avg points/trade", stats["avg_points_per_trade"])

    st.markdown("**Win rate by indicator condition:**")
    cond_df = pd.DataFrame([
        {"condition": k, "win_rate_%": v["win_rate"], "sample_size": v["sample_size"]}
        for k, v in stats["condition_win_rates"].items()
    ]).sort_values("win_rate_%", ascending=False)

    fig = go.Figure(go.Bar(
        x=cond_df["win_rate_%"], y=cond_df["condition"], orientation="h",
        marker_color=["#00D68F" if v >= 50 else "#FF4D4D" for v in cond_df["win_rate_%"]],
        text=cond_df["sample_size"].apply(lambda n: f"n={n}"),
        textposition="outside",
    ))
    fig.update_layout(
        height=280, margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor="#0E1117", plot_bgcolor="#0E1117",
        font=dict(color="#9CA3AF"),
        xaxis=dict(title="Win Rate %", gridcolor="#262B34", range=[0, 100]),
        yaxis=dict(gridcolor="#262B34"),
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    st.caption(
        "Don't act on any condition's win rate until you have at least ~20-30 "
        "closed trades for it — smaller samples are just noise."
    )

    st.subheader("📜 Full History")
    all_calls = trade_log.get_all_calls()
    hist_df = pd.DataFrame(all_calls)
    if not hist_df.empty:
        cols_to_show = ["symbol", "call_type", "issued_at", "entry", "stop_loss",
                         "target", "status", "exit_price", "points_captured", "target_miss_by"]
        st.dataframe(hist_df[cols_to_show], use_container_width=True, hide_index=True)


def main():
    inject_css()
    st.title("📊 Intraday Stock Screener")
    st.caption(
        "Personal-use tool only. Not SEBI-registered investment advice. "
        "Entry/Stop-Loss/Target come from a fixed ATR-based formula — not a prediction. "
        "Backtest before trusting these with real money."
    )

    tab1, tab2 = st.tabs(["📊 Screener", "📒 Trade Log & Performance"])
    with tab1:
        render_screener_tab()
    with tab2:
        render_trade_log_tab()


if __name__ == "__main__":
    main()