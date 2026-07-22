import streamlit as st
import pandas as pd
from datetime import datetime, date

from data_fetcher import is_market_open, fetch_candles
from scorer import run_screener
from indicators import technical_score
import trade_log
import ai_learner

st.set_page_config(page_title="AI Pro Intraday Terminal", page_icon="⚡", layout="wide")

try:
    from streamlit_autorefresh import st_autorefresh
    HAS_AUTOREFRESH = True
except ImportError:
    HAS_AUTOREFRESH = False

CUSTOM_CSS = """
<style>
    .stApp { background-color: #0B0E14; }
    .call-card {
        border-radius: 12px; padding: 18px; margin-bottom: 14px;
        background: #141822; border: 1px solid #1F2633;
    }
    .call-card.buy { border-left: 5px solid #00E699; }
    .call-card.short { border-left: 5px solid #FF5252; }
    .prob-badge-green {
        background: rgba(0,230,153,0.15); color: #00E699;
        padding: 6px 14px; border-radius: 6px; font-weight: bold; font-size: 0.95em; border: 1px solid #00E699;
    }
    .prob-badge-yellow {
        background: rgba(255,193,7,0.15); color: #FFC107;
        padding: 6px 14px; border-radius: 6px; font-weight: bold; font-size: 0.95em; border: 1px solid #FFC107;
    }
    .prob-badge-red {
        background: rgba(255,82,82,0.15); color: #FF5252;
        padding: 6px 14px; border-radius: 6px; font-weight: bold; font-size: 0.95em; border: 1px solid #FF5252;
    }
    .auto-sl-badge {
        background: rgba(0, 191, 255, 0.15); color: #00BFFF;
        padding: 4px 10px; border-radius: 6px; font-weight: bold; font-size: 0.85em; border: 1px solid #00BFFF;
        display: inline-block; margin-top: 5px;
    }
    .time-badge {
        background: rgba(255,255,255,0.08); color: #8B949E;
        padding: 5px 10px; border-radius: 6px; font-size: 0.85em;
    }
    .ai-box {
        background: #1A202C; border: 1px dashed #30363D; border-radius: 8px;
        padding: 10px 14px; margin-top: 10px; font-size: 0.9em; color: #E6EDF3;
    }
    .ai-learning-card {
        background: #0D1117; border: 1px solid #238636; border-radius: 10px;
        padding: 16px; margin-bottom: 20px; color: #E6EDF3;
    }
    .summary-box {
        background: #141822; border: 1px solid #2A3447; border-radius: 12px;
        padding: 20px; margin-top: 20px; margin-bottom: 20px;
    }
    .status-banner-open {
        background: #142820; border: 1px solid #00E699; color: #00E699;
        padding: 12px; border-radius: 10px; text-align: center; font-weight: bold; font-size: 1em;
    }
    .status-banner-closed {
        background: #1F2633; border: 1px solid #FF5252; color: #FF5252;
        padding: 12px; border-radius: 10px; text-align: center; font-weight: bold; font-size: 1em;
    }
    .pnl-green { color: #00E699; font-weight: bold; font-size: 1.25em; }
    .pnl-red { color: #FF5252; font-weight: bold; font-size: 1.25em; }
    .filter-card {
        background: #141822; border: 1px solid #1F2633; border-radius: 10px;
        padding: 14px; margin-bottom: 15px;
    }
</style>
"""

def format_dt(iso_str):
    if not iso_str: return "-"
    try:
        dt = datetime.fromisoformat(str(iso_str))
        return dt.strftime("%d-%b-%Y %I:%M %p")
    except Exception:
        return iso_str

def calculate_dynamic_win_prob(sym, call_type, entry, target, sl, init_score, df_curr):
    if df_curr.empty or len(df_curr) < 20:
        return init_score, "📊 Market data syncing...", sl, target

    curr_price = float(df_curr["Close"].iloc[-1])
    tech = technical_score(df_curr)
    curr_tech_score = tech["score"]

    if call_type == "BUY":
        total_dist = target - entry
        curr_dist = curr_price - entry
    else:
        total_dist = entry - target
        curr_dist = entry - curr_price

    progress_pct = (curr_dist / total_dist * 100) if total_dist != 0 else 0
    dynamic_prob = round(0.4 * curr_tech_score + 0.6 * max(10, min(95, init_score + (progress_pct * 0.35))), 1)
    dynamic_prob = max(5.0, min(98.0, dynamic_prob))

    advice = []
    suggested_sl = sl
    suggested_target = target

    # 🤖 AI Trailing SL Logic
    if progress_pct >= 50:
        suggested_sl = round(entry + (curr_dist * 0.4), 2) if call_type == "BUY" else round(entry - (curr_dist * 0.4), 2)
        advice.append(f"🟢 **Auto Trailing SL Active:** Risk-Free Trade! SL updated to ₹{suggested_sl}")
    
    if dynamic_prob >= 88:
        suggested_target = round(target + (total_dist * 0.25), 2) if call_type == "BUY" else round(target - (total_dist * 0.25), 2)
        advice.append(f"🔥 **Strong Momentum:** Target extend karke ₹{suggested_target} kar sakte ho!")
    elif dynamic_prob < 45:
        advice.append("⚠️ **Reversal Risk:** Early exit consider karo ya SL strictly follow karo!")
    else:
        advice.append("⚡ **Position On Track:** Setup stable hai, target-SL ke sath hold karein.")

    return dynamic_prob, " | ".join(advice), suggested_sl, suggested_target

def main():
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
    st.title("⚡ AI Pro Intraday Terminal & Self-Learning Engine")

    market_active = is_market_open()
    now_str = datetime.now().strftime("%d-%b-%Y %I:%M:%S %p")
    
    if market_active:
        st.markdown(f'<div class="status-banner-open">🟢 MARKET IS LIVE ({now_str}) — Auto Scanning & Live PnL Active</div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="status-banner-closed">🔴 MARKET IS CLOSED ({now_str}) — Showing Saved Signals & History</div>', unsafe_allow_html=True)
    
    st.write("")

    tab1, tab2, tab3 = st.tabs([
        "🔥 Live Signals", 
        "⏱️ Active Positions & Live PnL", 
        "📜 Closed History & AI Learning Diagnostics"
    ])

    # ------------------ TAB 1: SCREENER & SIGNALS ------------------
    with tab1:
        c_head1, c_head2 = st.columns([4, 1])
        c_head1.subheader("🎯 Institutional Momentum Calls")
        
        if HAS_AUTOREFRESH:
            st_autorefresh(interval=1 * 60 * 1000, key="screener_live_refresh")

        if c_head2.button("🔄 Force Scan Now", type="primary") or "results" not in st.session_state:
            with st.spinner("Scanning market live with NIFTY Filter & ADX..."):
                st.session_state.results = run_screener()

        df = st.session_state.get("results")

        if df is None or df.empty:
            all_past = trade_log.get_all_calls()
            if all_past:
                df = pd.DataFrame(all_past)

        if df is not None and not df.empty:
            col_key = "confidence_score" if "confidence_score" in df.columns else "final_score"
            if col_key in df.columns:
                df = df.sort_values(by=[col_key], ascending=[False]).reset_index(drop=True)

            rank = 1
            has_calls = False
            for _, row in df.iterrows():
                call = row.get("call", row.get("call_type", "NO_CALL"))
                if call == "NO_CALL": continue

                has_calls = True
                cls = "buy" if call == "BUY" else "short"
                st.markdown(f'<div class="call-card {cls}">', unsafe_allow_html=True)
                
                c1, c2, c3 = st.columns([3, 2, 2])
                c1.markdown(f"### #{rank} {row['symbol']} ({call})")
                score = row.get('confidence_score', row.get('final_score', 0))
                c2.markdown(f"<span class='prob-badge-green'>⚡ Confidence: {score}%</span>", unsafe_allow_html=True)
                
                call_time = format_dt(row.get("issued_at")) if row.get("issued_at") else now_str
                c3.markdown(f"<span class='time-badge'>⏰ Time: {call_time}</span>", unsafe_allow_html=True)

                m1, m2, m3 = st.columns(3)
                m1.markdown(f"**Entry:** ₹{row['entry']}")
                m2.markdown(f"**SL:** ₹{row['stop_loss']}")
                m3.markdown(f"**Target:** ₹{row['target']}")

                st.write("")

                # 🏷️ Strategy tag comes AUTOMATICALLY from the screener's own
                # decision logic (scorer.py) — no manual selection needed.
                # scorer.py should set row['strategy'] to whatever basis
                # (BREAKOUT / MOMENTUM / REVERSAL / etc.) triggered this call.
                strategy_tag = row.get("strategy", "SCREENER_DEFAULT")

                tag_col1, tag_col2 = st.columns([2, 2])
                with tag_col1:
                    st.markdown(f"**🏷️ Call Basis (Auto-Detected):** `{strategy_tag}`")
                with tag_col2:
                    sizing_mode = st.radio(
                        "Sizing Mode",
                        ["Capital-based", "Risk-based (₹ risk fixed)"],
                        key=f"sizing_{row['symbol']}_{rank}",
                        horizontal=True
                    )

                act_col1, act_col2 = st.columns([2, 2])
                risk_amt_input = None
                with act_col1:
                    if sizing_mode == "Capital-based":
                        trade_amt = st.number_input(f"Amount for {row['symbol']} (₹)", min_value=1000.0, value=150000.0, step=5000.0, key=f"amt_{row['symbol']}_{rank}")
                    else:
                        trade_amt = st.number_input(f"Capital Reference for {row['symbol']} (₹)", min_value=1000.0, value=150000.0, step=5000.0, key=f"amt_{row['symbol']}_{rank}")
                        risk_amt_input = st.number_input(f"Max ₹ Risk for {row['symbol']}", min_value=100.0, value=2000.0, step=100.0, key=f"risk_{row['symbol']}_{rank}")
                        preview_qty = trade_log.calculate_quantity_by_risk(risk_amt_input, row['entry'], row['stop_loss'])
                        st.caption(f"📐 Risk-based quantity preview: **{preview_qty} shares** (risking ~₹{risk_amt_input:,.0f})")
                with act_col2:
                    st.write("")
                    st.write("")
                    if st.button(f"🚀 Log Paper Trade", key=f"exec_{row['symbol']}_{rank}"):
                        # 🛑 NEW: daily loss-limit circuit breaker check before logging
                        loss_check = trade_log.check_daily_loss_limit(max_loss_amount=10000)
                        if not loss_check["can_trade"]:
                            st.error(f"🛑 Daily loss limit hit (₹{loss_check['current_pnl']:,.2f} / limit ₹{loss_check['limit']:,.2f}). New trades blocked for today.")
                        else:
                            trade_log.log_call(
                                row.to_dict(),
                                allocated_amount=trade_amt,
                                is_paper=1,
                                strategy=strategy_tag,
                                risk_amount=risk_amt_input
                            )
                            st.toast(f"✅ Trade logged for {row['symbol']} [{strategy_tag}]!")
                            st.rerun()

                st.markdown("</div>", unsafe_allow_html=True)
                rank += 1

            if not has_calls:
                st.info("ℹ️ Is scan me koi active call match nahi hui.")
        else:
            st.warning("⚠️ No active signals found. Click **Force Scan Now** above.")

    # ------------------ TAB 2: ACTIVE POSITIONS ------------------
    with tab2:
        top_col1, top_col2 = st.columns([3, 1])
        top_col1.subheader("⏱️ Active Positions & Real-Time Dynamic Win %")
        
        with top_col2:
            if st.button("🗑️ Delete ALL Active Positions", type="secondary"):
                trade_log.delete_all_calls(scope="OPEN")
                st.toast("🗑️ All active positions cleared!")
                st.rerun()

        # 💰 NEW: Investment / capital deployed snapshot
        inv = trade_log.get_investment_summary()
        inv_col1, inv_col2, inv_col3, inv_col4 = st.columns(4)
        inv_col1.metric("💰 Currently Deployed", f"₹{inv['currently_deployed']:,.0f}", f"{inv['open_positions_count']} open")
        inv_col2.metric("📦 Total Invested (All-Time)", f"₹{inv['total_invested_all_time']:,.0f}", f"{inv['total_trades']} trades")
        inv_col3.metric("✅ Closed Capital Used", f"₹{inv['closed_capital']:,.0f}", f"{inv['closed_positions_count']} closed")
        inv_col4.metric("⏱️ Avg Holding Time", f"{trade_log.avg_holding_time_minutes():.0f} min")

        # 🛑 NEW: Daily loss-limit circuit breaker banner
        daily_check = trade_log.check_daily_loss_limit(max_loss_amount=10000)
        if not daily_check["can_trade"]:
            st.error(f"🛑 **Daily Loss Limit Breached!** Today's realized PnL: ₹{daily_check['current_pnl']:,.2f} (Limit: ₹{daily_check['limit']:,.2f}). Consider pausing new trades.")
        else:
            st.caption(f"🟢 Today's realized PnL: ₹{daily_check['current_pnl']:,.2f} (Daily loss limit: ₹{daily_check['limit']:,.2f})")

        open_positions = trade_log.get_open_calls()

        if open_positions:
            total_unrealized_pnl = 0.0
            
            for rank_idx, trade in enumerate(open_positions, 1):
                tid = trade["id"]
                sym = trade["symbol"]
                call_type = trade["call_type"]
                entry = float(trade["entry"])
                target = float(trade["target"])
                sl = float(trade["stop_loss"])
                init_score = float(trade.get("confidence_score") or trade.get("final_score") or 75.0)
                
                amt = float(trade.get("allocated_amount") or 50000.0)
                qty = max(1, int(amt / entry))

                df_curr = fetch_candles(sym, interval="5m", period="1d")
                if not df_curr.empty:
                    curr_price = float(df_curr["Close"].iloc[-1])
                    high_price = float(df_curr["High"].iloc[-1])
                    low_price = float(df_curr["Low"].iloc[-1])
                else:
                    curr_price, high_price, low_price = entry, entry, entry

                live_win_prob, ai_advice, trail_sl, extended_target = calculate_dynamic_win_prob(
                    sym, call_type, entry, target, sl, init_score, df_curr
                )

                # 🤖 AUTOMATIC STOP LOSS TRAILING TRIGGER
                auto_sl_updated = False
                if call_type == "BUY" and trail_sl > sl:
                    trade_log.update_stop_loss(tid, trail_sl)
                    sl = trail_sl
                    auto_sl_updated = True
                elif call_type == "SHORT" and trail_sl < sl:
                    trade_log.update_stop_loss(tid, trail_sl)
                    sl = trail_sl
                    auto_sl_updated = True

                hit_target = (call_type == "BUY" and high_price >= target) or (call_type == "SHORT" and low_price <= target)
                hit_sl = (call_type == "BUY" and low_price <= sl) or (call_type == "SHORT" and high_price >= sl)

                if hit_target:
                    pnl = (target - entry) * qty if call_type == "BUY" else (entry - target) * qty
                    pnl_p = (pnl / amt) * 100
                    trade_log.record_outcome(tid, "HIT_TARGET", exit_price=target, root_cause="🎯 Target Hit!", pnl=pnl, pnl_pct=pnl_p)
                    st.toast(f"🎯 {sym} Hit Target!")
                    st.rerun()

                elif hit_sl:
                    pnl = (sl - entry) * qty if call_type == "BUY" else (entry - sl) * qty
                    pnl_p = (pnl / amt) * 100
                    trade_log.record_outcome(tid, "HIT_SL", exit_price=sl, root_cause="🔴 Stop Loss Hit!", pnl=pnl, pnl_pct=pnl_p)
                    st.toast(f"🔴 {sym} Hit Stop Loss!")
                    st.rerun()

                live_pnl = (curr_price - entry) * qty if call_type == "BUY" else (entry - curr_price) * qty
                live_pnl_pct = (live_pnl / amt) * 100 if amt > 0 else 0.0
                total_unrealized_pnl += live_pnl

                cls = "buy" if call_type == "BUY" else "short"
                pnl_class = "pnl-green" if live_pnl >= 0 else "pnl-red"
                pnl_symbol = "+" if live_pnl >= 0 else ""

                badge_cls = "prob-badge-green" if live_win_prob >= 75 else ("prob-badge-yellow" if live_win_prob >= 50 else "prob-badge-red")

                st.markdown(f'<div class="call-card {cls}">', unsafe_allow_html=True)
                
                col_a, col_b, col_c = st.columns([3, 2, 2])
                top_tag = "🆕 " if rank_idx == 1 else ""
                col_a.markdown(f"### #{rank_idx} {top_tag}{sym} ({call_type}) — Qty: **{qty:,} Shares**")
                
                col_b.markdown(f"<span class='{badge_cls}'>🎯 Dynamic Win Prob: {live_win_prob}%</span>", unsafe_allow_html=True)
                col_c.markdown(f"**Live PnL:** <span class='{pnl_class}'>{pnl_symbol}₹{live_pnl:.2f} ({pnl_symbol}{live_pnl_pct:.2f}%)</span>", unsafe_allow_html=True)

                st.write("")
                p1, p2, p3, p4 = st.columns(4)
                p1.markdown(f"**Entry:** ₹{entry:.2f}")
                p2.markdown(f"**Live Price:** ₹{curr_price:.2f}")
                
                if auto_sl_updated or (call_type == "BUY" and sl > float(trade["stop_loss"])) or (call_type == "SHORT" and sl < float(trade["stop_loss"])):
                    p3.markdown(f"**SL:** ₹{sl:.2f} <br><span class='auto-sl-badge'>🤖 Auto-Trailed (Protected)</span>", unsafe_allow_html=True)
                else:
                    p3.markdown(f"**SL:** ₹{sl:.2f}")
                    
                p4.markdown(f"**Target:** ₹{target:.2f}")

                st.markdown(f'<div class="ai-box">🤖 <b>AI Pro Guidance:</b> {ai_advice}</div>', unsafe_allow_html=True)

                st.write("")
                btn_col1, btn_col2, btn_col3 = st.columns([2, 2, 2])
                
                with btn_col1:
                    with st.popover("✏️ Edit Amount"):
                        new_amount = st.number_input("New Amount (₹)", min_value=1000.0, value=amt, step=5000.0, key=f"edit_amt_{tid}")
                        if st.button("Save New Amount", key=f"save_amt_{tid}"):
                            trade_log.update_call_amount(tid, new_amount, entry)
                            st.toast(f"Updated amount for {sym} to ₹{new_amount:,.0f}!")
                            st.rerun()

                with btn_col2:
                    if st.button(f"🔴 Square Off ({sym})", key=f"sq_{tid}"):
                        trade_log.record_outcome(tid, "MANUAL_EXIT", exit_price=curr_price, root_cause="User Manual Exit", pnl=live_pnl, pnl_pct=live_pnl_pct)
                        st.toast(f"Position squared off for {sym} at ₹{curr_price:.2f}")
                        st.rerun()

                with btn_col3:
                    if st.button(f"🗑️ Delete Call", key=f"del_{tid}"):
                        trade_log.delete_call(tid)
                        st.toast(f"🗑️ Deleted {sym} call!")
                        st.rerun()

                st.markdown("</div>", unsafe_allow_html=True)

            st.write("---")
            pnl_tot_class = "pnl-green" if total_unrealized_pnl >= 0 else "pnl-red"
            st.markdown(f"### 📊 Total Open Portfolio Live PnL: <span class='{pnl_tot_class}'>₹{total_unrealized_pnl:,.2f}</span>", unsafe_allow_html=True)

        else:
            st.info("ℹ️ Koi bhi active position open nahi hai.")

    # ------------------ TAB 3: CLOSED HISTORY & AI DIAGNOSTICS ------------------
    with tab3:
        top_h1, top_h2 = st.columns([3, 1])
        top_h1.subheader("📜 Closed Trades & AI Self-Learning Diagnostics")
        
        with top_h2:
            if st.button("💾 Backup to CSV", type="secondary"):
                backup_path = trade_log.export_backup_csv()
                if backup_path:
                    st.toast(f"💾 Backup saved: {backup_path}")
                else:
                    st.toast("⚠️ Backup failed — check logs.")
            if st.button("🗑️ Clear ENTIRE History Log", type="secondary"):
                trade_log.delete_all_calls(scope="CLOSED")
                st.toast("🗑️ Closed trades history cleared!")
                st.rerun()

        # 🧠 AI LEARNING ENGINE DIAGNOSTIC SECTION
        learn_data = ai_learner.analyze_and_learn()

        # 🤖 NEW: adaptive confidence threshold, derived from recent closed trades
        adaptive = trade_log.get_adaptive_confidence_threshold(lookback=20, base_threshold=70.0)
        adaptive_line = (
            f"Recent win rate ({adaptive['sample_size']} trades): <b>{adaptive['recent_win_rate']}%</b> "
            f"→ Suggested min. confidence score: <b>{adaptive['suggested_threshold']}%</b>"
            if adaptive["sample_size"] > 0 else "Not enough closed trades yet to suggest a threshold."
        )

        st.markdown(f"""
        <div class="ai-learning-card">
            <h4>🧠 AI Self-Learning Engine Status: ACTIVE</h4>
            <p><b>Today's AI Learning Insight:</b> {learn_data['insight']}</p>
            <p>🎯 <b>Detected SL Hunting/Fakeouts:</b> {learn_data['fakeouts']} trades | <b>Active SL Buffer Multiplier:</b> {learn_data['sl_buffer_multiplier']}x</p>
            <p>🎚️ <b>Adaptive Confidence Threshold:</b> {adaptive_line}</p>
        </div>
        """, unsafe_allow_html=True)

        # ------------------ NEW: EQUITY CURVE, DRAWDOWN, STRATEGY & TIME ANALYTICS ------------------
        st.subheader("📈 Equity Curve & Risk Analytics")

        curve_data = trade_log.equity_curve()
        dd_stats = trade_log.drawdown_stats()

        ec_col1, ec_col2 = st.columns([3, 1])
        with ec_col1:
            if curve_data:
                df_curve = pd.DataFrame(curve_data)
                df_curve["exit_at"] = pd.to_datetime(df_curve["exit_at"], errors="coerce")
                df_curve = df_curve.dropna(subset=["exit_at"]).set_index("exit_at")
                st.line_chart(df_curve["cumulative_pnl"])
            else:
                st.info("ℹ️ Abhi tak koi closed trade nahi hai equity curve dikhane ke liye.")
        with ec_col2:
            st.metric("📉 Max Drawdown", f"₹{dd_stats['max_drawdown']:,.2f}", f"-{dd_stats['max_drawdown_pct']}%")
            st.metric("🏔️ Peak Equity", f"₹{dd_stats['peak_equity']:,.2f}")

        st.write("")
        strat_col, time_col = st.columns(2)

        with strat_col:
            st.markdown("**🏷️ Strategy-wise Performance**")
            strat_perf = trade_log.strategy_performance()
            if strat_perf:
                st.dataframe(pd.DataFrame(strat_perf), use_container_width=True, hide_index=True)
            else:
                st.caption("Koi strategy-tagged closed trade nahi mila.")

        with time_col:
            st.markdown("**⏰ Time-of-Day Performance**")
            tod_perf = trade_log.time_of_day_performance()
            if tod_perf:
                st.dataframe(pd.DataFrame(tod_perf), use_container_width=True, hide_index=True)
            else:
                st.caption("Koi time-of-day data nahi mila.")

        st.write("")
        st.markdown("**🎯 Detailed Outcome Breakdown (All Closed Trades)**")
        outcome = trade_log.outcome_breakdown()
        if outcome["total"] > 0:
            o1, o2, o3, o4 = st.columns(4)
            o1.metric("🎯 Target Hit", outcome["target_hit"], f"{outcome['target_hit_pct']}%")
            o2.metric("🔴 Legit SL Hit", outcome["sl_hit_legit"], f"{outcome['sl_hit_legit_pct']}%")
            o3.metric("⚠️ Fakeout / SL Hunted", outcome["sl_hit_fakeout"], f"{outcome['sl_hit_fakeout_pct']}%")
            o4.metric("✋ Manual Exit", outcome["manual_exit"], f"{outcome['manual_exit_pct']}%")
            if outcome["sl_hit_fakeout"] > 0:
                st.caption(f"⚠️ {outcome['sl_hit_fakeout']} out of {outcome['total']} trades ({outcome['sl_hit_fakeout_pct']}%) were SL-hunted fakeouts — target was hit later. Consider widening SL or using the AI trailing-SL buffer.")
        else:
            st.caption("Abhi koi closed trade nahi hai outcome breakdown dikhane ke liye.")

        st.write("---")

        # 📅 NEW: DATE FILTER CONTROLS FOR HISTORY & PERFORMANCE
        st.markdown('<div class="filter-card">', unsafe_allow_html=True)
        col_f1, col_f2, col_f3 = st.columns([2, 2, 2])
        filter_mode = col_f1.selectbox("📅 Filter History By Date:", ["All Time", "Single Date", "Date Range"], key="hist_filter_mode")
        
        start_date_val = None
        end_date_val = None

        if filter_mode == "Single Date":
            start_date_val = col_f2.date_input("Select Date", date.today(), key="hist_single_date")
        elif filter_mode == "Date Range":
            start_date_val = col_f2.date_input("From Date", date.today(), key="hist_start_date")
            end_date_val = col_f3.date_input("To Date", date.today(), key="hist_end_date")
        st.markdown('</div>', unsafe_allow_html=True)

        st.subheader("📋 Detailed Trade Outcome & Post-Exit Monitor")
        
        # Sync post-exit data for all closed trades first
        all_closed = trade_log.get_closed_calls()
        if all_closed:
            for ct in all_closed:
                cid = ct["id"]
                csym = ct["symbol"]
                target = float(ct["target"])
                entry = float(ct["entry"])
                call_type = ct["call_type"]
                qty = int(ct.get("quantity") or 1)
                amt = float(ct.get("allocated_amount") or 50000.0)
                exit_price = float(ct.get("exit_price") or ct["entry"])
                prev_max = float(ct.get("max_post_exit_price") or exit_price)
                prev_min = float(ct.get("min_post_exit_price") or exit_price)

                df_post = fetch_candles(csym, interval="5m", period="1d")
                if not df_post.empty:
                    curr_max = max(prev_max, float(df_post["High"].max()))
                    curr_min = min(prev_min, float(df_post["Low"].min()))
                    
                    post_status = "STABLE"
                    new_pnl = None
                    new_pnl_pct = None

                    if ct["status"] in ["HIT_SL", "MANUAL_EXIT"]:
                        is_target_hit_later = (call_type == "BUY" and curr_max >= target) or (call_type == "SHORT" and curr_min <= target)
                        if is_target_hit_later:
                            post_status = "⚠️ FAKEOUT / SL HUNTED (Hit Target Later)"
                            fakeout_pnl = (target - entry) * qty if call_type == "BUY" else (entry - target) * qty
                            new_pnl = round(fakeout_pnl, 2)
                            new_pnl_pct = round((fakeout_pnl / amt) * 100, 2) if amt > 0 else 0.0
                        else:
                            post_status = "🔴 Legitimate SL Hit"
                    elif ct["status"] == "HIT_TARGET":
                        post_status = "🎯 Target Hit Successfully"

                    trade_log.update_post_exit_tracking(cid, curr_max, curr_min, post_status, new_pnl, new_pnl_pct)

        # Fetch filtered data based on user selection
        if filter_mode == "Single Date" and start_date_val:
            raw_data = trade_log.get_calls_by_date(start_date_val)
            closed_trades = [t for t in raw_data if t.get("status") != "OPEN"]
        elif filter_mode == "Date Range" and start_date_val and end_date_val:
            raw_data = trade_log.get_calls_by_date_range(start_date_val, end_date_val)
            closed_trades = [t for t in raw_data if t.get("status") != "OPEN"]
        else:
            closed_trades = trade_log.get_closed_calls()

        if closed_trades:
            df_history = pd.DataFrame(closed_trades)

            show_cols = [
                "id", "symbol", "call_type", "strategy", "entry", "exit_price",
                "target", "stop_loss", "pnl", "pnl_pct", "status",
                "max_post_exit_price", "post_exit_status", "root_cause", "issued_at"
            ]
            existing_show = [c for c in show_cols if c in df_history.columns]
            
            df_display = df_history[existing_show].rename(columns={
                "max_post_exit_price": "Post-Exit Max Price",
                "post_exit_status": "Post-Exit AI Diagnosis",
                "pnl": "PnL (₹)",
                "pnl_pct": "PnL (%)"
            })
            
            st.dataframe(df_display, use_container_width=True)

            # Performance Summary filtered by Selected Date
            stats = trade_log.performance_summary(
                start_date=start_date_val if filter_mode != "All Time" else None,
                end_date=end_date_val if filter_mode == "Date Range" else (start_date_val if filter_mode == "Single Date" else None)
            )

            tot_prof = stats.get('total_profit', 0.0)
            tot_loss = stats.get('total_loss', 0.0)
            net_pnl = stats.get('net_pnl', 0.0)
            expectancy = stats.get('expectancy', 0.0)
            profit_factor = stats.get('profit_factor')
            pf_display = f"{profit_factor}x" if profit_factor is not None else "N/A"

            net_color = "#00E699" if net_pnl >= 0 else "#FF5252"
            net_sign = "+" if net_pnl >= 0 else ""
            exp_color = "#00E699" if expectancy >= 0 else "#FF5252"

            st.markdown(f"""
            <div class="summary-box">
                <h3 style="margin-top:0; color:#E6EDF3;">📊 <b>History Performance Summary ({filter_mode})</b></h3>
                <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 15px;">
                    <div>
                        <span style="color:#8B949E; font-weight:bold;">Total Trades:</span> 
                        <b style="color:#ffffff; font-size:1.1em;">{stats.get('total_closed', 0)}</b>
                    </div>
                    <div>
                        <span style="color:#8B949E; font-weight:bold;">Win Rate:</span> 
                        <b style="color:#00E699; font-size:1.1em;">{stats.get('win_rate_pct', 0)}%</b>
                    </div>
                    <div>
                        🟢 <b style="font-size:1.15em;">TOTAL PROFIT:</b> 
                        <span style="color:#00E699; font-size:1.35em; font-weight:bold;">+₹{tot_prof:,.2f}</span>
                    </div>
                    <div>
                        🔴 <b style="font-size:1.15em;">TOTAL LOSS:</b> 
                        <span style="color:#FF5252; font-size:1.35em; font-weight:bold;">₹{tot_loss:,.2f}</span>
                    </div>
                    <div>
                        ⚡ <b style="font-size:1.15em;">OVERALL PROFIT / LOSS:</b> 
                        <span style="color:{net_color}; font-size:1.4em; font-weight:bold;">{net_sign}₹{net_pnl:,.2f}</span>
                    </div>
                    <div>
                        🧮 <b style="font-size:1.15em;">EXPECTANCY / TRADE:</b> 
                        <span style="color:{exp_color}; font-size:1.35em; font-weight:bold;">₹{expectancy:,.2f}</span>
                    </div>
                    <div>
                        ⚖️ <b style="font-size:1.15em;">PROFIT FACTOR:</b> 
                        <span style="color:#E6EDF3; font-size:1.35em; font-weight:bold;">{pf_display}</span>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            st.write("")
            del_id = st.number_input("Delete History Record by ID", min_value=1, step=1, key="del_hist_id")
            if st.button("🗑️ Remove Selected Record From History"):
                trade_log.delete_call(del_id)
                st.toast(f"Record #{del_id} deleted!")
                st.rerun()
        else:
            st.info(f"ℹ️ Is selected filter ({filter_mode}) me koi closed trade history nahi mili.")

if __name__ == "__main__":
    main()