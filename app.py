"""Security Analysis — Risk-based portfolio dashboard (Streamlit).
Python port of: SA_Macro_Enabled.xlsm (+VBA Solver macro), the Deutsche Bank risk questionnaire workbook,
and the Portfolio Presentation workbook.   Run:  streamlit run app.py
"""
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from sa import SAModel, optimizer, risk_profile, valuation
from sa.portfolios import UNIVERSE_ORDER

st.set_page_config(page_title="Security Analysis Dashboard", page_icon="📈", layout="wide")

# Fixed categorical colour per stock (colour follows the entity) — validated reference palette
PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
STOCK_COLOR = dict(zip(UNIVERSE_ORDER, PALETTE))
INK2 = "#52514e"
PROFILES = list(risk_profile.PROFILE_BANDS)
PROFILE_NAMES = [n for _, _, n in risk_profile.PROFILE_BANDS]

def x100(df, cols):
    """Scale fractional columns to percent points for display (Streamlit's '%' format does not scale)."""
    df = df.copy()
    for c in cols:
        df[c] = df[c] * 100
    return df


pct = lambda x, d=2: "–" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{d}%}"


@st.cache_resource
def get_model() -> SAModel:
    return SAModel()


@st.cache_data(show_spinner=False)
def run_reco(profile: str, A: float, max_sd: float):
    return get_model().recommend(profile, A, max_sd)


@st.cache_data(show_spinner=False)
def val_summary():
    return valuation.summary_table()


M = get_model()
questions, key = risk_profile.load_questionnaire()

# ------------------------------------------------------------------ session defaults (worked example in the report)
DEFAULT_ANS = {**{q: "C" for q in range(1, 7)}, **{q: "A" for q in range(7, 13)}}
for q, a in DEFAULT_ANS.items():
    st.session_state.setdefault(f"q{q}", a)


def answer_label(q: int, letter: str) -> str:
    row = key[(key.q == q) & (key.letter == letter)].iloc[0]
    return f"{letter} — {row.answer}  ({row.score} pts)"


# ------------------------------------------------------------------ sidebar: client context
with st.sidebar:
    st.title("Client context")
    with st.expander("Risk-aversion calibration (A)", expanded=False):
        st.caption("Illustrative project calibration — not part of the Deutsche Bank tool.")
        a_min = st.number_input("A minimum", 0.0, 20.0, 1.0, 0.1)
        a_max = st.number_input("A maximum", 0.0, 50.0, 2.0, 0.1)
        gamma = st.number_input("Gamma (curvature)", 0.1, 10.0, 1.0, 0.1)
        w_c = st.slider("Weight on Risk Capacity", 0.0, 1.0, 0.5, 0.05, help="Tolerance weight = 1 − this.")
    cal = risk_profile.Calibration(a_min, a_max, gamma, w_c, 1 - w_c)
    answers = {q: st.session_state[f"q{q}"] for q in range(1, 13)}
    risk = risk_profile.score_questionnaire(answers, cal)

    manual = st.toggle("Manual override (skip questionnaire)", value=False)
    if manual:
        profile = st.selectbox("Risk profile", PROFILE_NAMES, index=3)
        A = st.number_input("Risk aversion A", 0.0, 50.0, float(round(risk.risk_aversion or 1.357, 3)), 0.05)
        max_sd = st.number_input("Maximum SD (ceiling)", 0.05, 1.0, float(M.mapping[profile]["max_sd"]), 0.005, format="%.3f")
    else:
        profile, A = risk.profile, risk.risk_aversion
        max_sd = M.mapping[profile]["max_sd"]
        st.metric("Risk profile", profile)
        c1, c2 = st.columns(2)
        c1.metric("Risk aversion A", f"{A:.3f}")
        c2.metric("Max SD", pct(max_sd, 1))
    cats = ", ".join(M.mapping[profile]["categories"])
    st.caption(f"Eligible categories: {cats}")
    st.divider()
    st.caption("Expected return = historical CAGR; risk = annualised SD of daily returns (252 days). "
               "Data: 20 Oct 2020 – 19 Oct 2026.")

st.title("Security Analysis — risk-based portfolio dashboard")
st.caption("Matches investors to a three-stock portfolio from an 8-stock NSE universe: questionnaire → risk profile → "
           "eligible categories → utility-maximising weights.")

tabs = st.tabs(["1 · Investor profile", "2 · Recommendation", "3 · Portfolio universe", "4 · Market risk & return",
                "5 · Valuation", "6 · Profile comparison", "7 · Model notes"])

# ================================================================== 1. questionnaire
with tabs[0]:
    up = st.file_uploader("Import answers from the Excel questionnaire (optional)", type=["xlsx"],
                          help="Reads 'Questionnaire Input'!D5:D16 from the workbook.")
    if up is not None and st.session_state.get("_imported") != up.file_id:
        import openpyxl
        ws = openpyxl.load_workbook(up, data_only=True)["Questionnaire Input"]
        for i, r in enumerate(range(5, 17), start=1):
            v = ws.cell(r, 4).value
            if v in set(key[key.q == i].letter):
                st.session_state[f"q{i}"] = v
        st.session_state["_imported"] = up.file_id
        st.rerun()

    left, right = st.columns([3, 2], gap="large")
    with left:
        for sec in ["Risk Capacity", "Risk Tolerance"]:
            st.subheader(sec + (" (Q1–6, max 24)" if sec == "Risk Capacity" else " (Q7–12, max 21)"))
            for r in questions[questions.section == sec].itertuples():
                letters = list(key[key.q == r.q].letter)
                st.selectbox(f"Q{r.q}. {r.text}", letters, key=f"q{r.q}",
                             format_func=lambda L, q=r.q: answer_label(q, L))
    with right:
        st.subheader("Result")
        if manual:
            st.info("Manual override is on — questionnaire result is shown but not used.")
        c1, c2 = st.columns(2)
        c1.metric("Risk Capacity", f"{risk.capacity} / 24", risk.capacity_band, delta_color="off")
        c2.metric("Risk Tolerance", f"{risk.tolerance} / 21", risk.tolerance_band, delta_color="off")
        c1.metric("Total score", f"{risk.total} / 45")
        c2.metric("Overall profile", risk.profile)
        c1.metric("Risk Preference Index", f"{risk.rpi:.3f}")
        c2.metric("Risk aversion A", f"{risk.risk_aversion:.3f}")
        # score on the 5–45 band scale
        fig = go.Figure()
        for lo, hi, nm in risk_profile.PROFILE_BANDS:
            fig.add_trace(go.Bar(y=["Score"], x=[hi - lo + 1], base=[lo], orientation="h", name=nm, text=[nm.replace("Very ", "V. ")], textposition="inside", insidetextanchor="middle",
                                 marker_color=["#cfe0f7", "#9fc3ee", "#6fa5e4", "#3f87da", "#2a5ea8"][PROFILE_NAMES.index(nm)], textfont_color=("#0b0b0b" if PROFILE_NAMES.index(nm) < 3 else "#ffffff"),
                                 marker_line=dict(color="#fcfcfb", width=2), hovertemplate=f"{nm}: {lo}–{hi}<extra></extra>"))
        fig.add_vline(x=risk.total + 0.5, line_width=3, line_color="#0b0b0b", annotation_text=f"Score {risk.total}")
        fig.update_layout(barmode="stack", height=130, margin=dict(l=0, r=0, t=30, b=0), showlegend=False, uniformtext=dict(minsize=9, mode="hide"),
                          xaxis=dict(range=[5, 46], title=None), yaxis=dict(visible=False))
        st.plotly_chart(fig, width="stretch")
        st.dataframe(pd.DataFrame({"Question": [f"Q{q}" for q in risk.item_scores], "Answer": [answers[q] for q in risk.item_scores],
                                   "Score": list(risk.item_scores.values())}), hide_index=True, height=250)
        st.caption("RPI = w_c × RC/24 + w_t × RT/21;  A = A_min + (A_max − A_min) × (1 − RPI)^γ.  "
                   "Questionnaire is a project-level suitability check, not a regulated assessment.")

# ================================================================== 2. recommendation
rec = run_reco(profile, float(A), float(max_sd))
with tabs[1]:
    st.subheader(f"Recommended portfolio — {profile} investor")
    if rec.best is None:
        st.error("No feasible portfolio under this SD ceiling. Raise the ceiling or change the profile.")
    else:
        b = rec.best
        perf = M.performance_of(b)
        k = st.columns(4)
        k[0].metric("Best portfolio", f"#{int(b['id'])}", b["category"], delta_color="off")
        k[1].metric("Expected return", pct(b["expected_return"]))
        k[2].metric("Portfolio SD", pct(b["sd"]), f"ceiling {pct(max_sd, 1)}" + (" · binding" if b["sd_binding"] else ""), delta_color="off")
        k[3].metric("Utility  U = E(R) − A/2·σ²", f"{b['utility']:.4f}")
        k = st.columns(4)
        k[0].metric("Sharpe ratio", f"{perf['sharpe']:.3f}", help=f"Rf = {pct(M.rf)}")
        k[1].metric("Portfolio beta", f"{perf['beta']:.3f}")
        k[2].metric("Treynor ratio", f"{perf['treynor']:.4f}")
        k[3].metric("Jensen's alpha", pct(perf["alpha"]), help=f"Rm = {pct(M.rm, 1)} (workbook input)")

        c1, c2 = st.columns([2, 3], gap="large")
        with c1:
            names, w = perf["names"], perf["weights"]
            fig = go.Figure(go.Pie(labels=names, values=w, hole=0.55, sort=False, marker=dict(colors=[STOCK_COLOR[n] for n in names],
                           line=dict(color="#fcfcfb", width=2)), texttemplate="%{label}<br>%{percent:.2%}", textposition="outside"))
            fig.update_layout(title="Optimised weights", height=360, showlegend=False, margin=dict(t=50, b=10, l=10, r=10),
                              annotations=[dict(text=f"#{int(b['id'])}", x=0.5, y=0.5, showarrow=False, font_size=22)])
            st.plotly_chart(fig, width="stretch")
        with c2:
            sel = [b["stock_1"], b["stock_2"], b["stock_3"]]
            cl = optimizer.sample_feasible(M.mu[sel].values, M.cov.loc[sel, sel].values, A, max_sd)
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=cl[~cl.feasible].sd, y=cl[~cl.feasible].ret, mode="markers", name="Breaches SD ceiling",
                                     marker=dict(size=5, color="#c3c2b7"), hoverinfo="skip"))
            f = cl[cl.feasible]
            fig.add_trace(go.Scatter(x=f.sd, y=f.ret, mode="markers", name="Feasible weights", marker=dict(size=5, color="#9fc3ee"),
                                     customdata=f.utility, hovertemplate="SD %{x:.2%}<br>Return %{y:.2%}<br>U %{customdata:.4f}<extra></extra>"))
            fig.add_vline(x=max_sd, line_dash="dash", line_color=INK2, annotation_text=f"SD ceiling {pct(max_sd, 1)}")
            fig.add_trace(go.Scatter(x=[b["sd"]], y=[b["expected_return"]], mode="markers", name="Optimum",
                                     marker=dict(size=14, color="#eb6834", line=dict(color="#fcfcfb", width=2))))
            fig.update_layout(title=f"Portfolio #{int(b['id'])}: 4,000 random weight mixes vs optimum", height=360,
                              xaxis=dict(title="Standard deviation", tickformat=".0%"), yaxis=dict(title="Expected return", tickformat=".0%"),
                              legend=dict(orientation="h", y=-0.25), margin=dict(t=50))
            st.plotly_chart(fig, width="stretch")

        st.markdown(f"**All {len(rec.results)} feasible portfolios ranked by utility** "
                    f"({len(rec.eligible)} eligible · {len(rec.failures)} infeasible under the ceiling)")
        show = rec.results.copy()
        show["Holdings"] = show.apply(lambda r: f"{r.stock_1} {r.w_1:.1%} · {r.stock_2} {r.w_2:.1%} · {r.stock_3} {r.w_3:.1%}", axis=1)
        show = show[["rank", "id", "category", "Holdings", "expected_return", "sd", "utility", "sd_binding"]]
        st.dataframe(x100(show, ["expected_return", "sd"]), hide_index=True, width="stretch", column_config={
            "rank": "Rank", "id": "Portfolio", "category": "Category", "expected_return": st.column_config.NumberColumn("Exp. return", format="%.2f%%"),
            "sd": st.column_config.NumberColumn("SD", format="%.2f%%"), "utility": st.column_config.NumberColumn("Utility", format="%.4f"),
            "sd_binding": "SD binding"})
        if not rec.failures.empty:
            with st.expander("Infeasible portfolios (dropped — the macro counted these as 'failed')"):
                st.dataframe(rec.failures, hide_index=True, width="stretch")
        st.download_button("Download results (CSV)", rec.results.to_csv(index=False), f"optimised_{profile.replace(' ', '_')}.csv", "text/csv")
        if "Waaree" in sel:
            st.warning("The top portfolios lean on Waaree's 58% historical CAGR (3-year history). Expected returns are historical CAGRs, "
                       "not forecasts — Sharpe, Treynor and alpha describe the model's inputs, not realised performance.")

# ================================================================== 3. universe
with tabs[2]:
    st.subheader("56 three-stock portfolios and their categories")
    cc = M.category_counts().reindex(["Dividend Yield", "Growth Equity", "Defensive Equity", "Flexi Cap"])
    c1, c2 = st.columns([1, 3], gap="large")
    with c1:
        fig = go.Figure(go.Bar(x=cc.index, y=cc.values, marker=dict(color="#2a78d6", cornerradius=4), text=cc.values, textposition="outside"))
        fig.update_layout(height=300, margin=dict(t=20, b=0), yaxis=dict(visible=False), xaxis=dict(title=None))
        st.plotly_chart(fig, width="stretch")
        st.caption("Rule: top-14 dividend yield → Dividend Yield; else top-14 growth → Growth Equity; else lowest-14 SD → Defensive; else Flexi Cap.")
    with c2:
        mp = pd.DataFrame({"Profile": k, "Eligible categories": ", ".join(v["categories"]), "Max SD": v["max_sd"]} for k, v in M.mapping.items())
        st.dataframe(x100(mp, ["Max SD"]), hide_index=True, width="stretch", column_config={"Max SD": st.column_config.NumberColumn(format="%.1f%%")} )
    f1, f2 = st.columns(2)
    catf = f1.multiselect("Category", cc.index.tolist(), default=cc.index.tolist())
    stockf = f2.multiselect("Contains stock", UNIVERSE_ORDER)
    P = M.portfolios.copy()
    P["Eligible for current profile"] = P.category.isin(M.mapping[profile]["categories"])
    P = P[P.category.isin(catf)]
    for s in stockf:
        P = P[(P.stock_1 == s) | (P.stock_2 == s) | (P.stock_3 == s)]
    st.dataframe(x100(P, ["div_yield", "growth", "sd"]), hide_index=True, width="stretch", column_config={
        "id": "Portfolio", "div_yield": st.column_config.NumberColumn("Dividend yield", format="%.2f%%"),
        "growth": st.column_config.NumberColumn("Growth score", format="%.2f%%"), "sd": st.column_config.NumberColumn("SD (equal-wt)", format="%.2f%%"),
        "beta": st.column_config.NumberColumn("Beta", format="%.3f")})

# ================================================================== 4. market
with tabs[3]:
    st.subheader("Historical risk & return of the universe")
    st_ = M.stock_table()
    c1, c2 = st.columns([3, 2], gap="large")
    with c1:
        st.dataframe(x100(st_, ["CAGR", "Annualised SD", "Dividend yield", "EBITDA growth"]), width="stretch", column_config={
            **{c: st.column_config.NumberColumn(format="%.2f%%") for c in ["CAGR", "Annualised SD", "Dividend yield", "EBITDA growth"]},
            "Beta (vs Nifty)": st.column_config.NumberColumn(format="%.3f"), "Return / risk": st.column_config.NumberColumn(format="%.2f")})
        st.caption("Beta: single-index regression on Nifty over Apr-2022–Mar-2023 (workbook window); Waaree's 0.93 is a hard-coded input.")
    with c2:
        fig = go.Figure()
        for s in st_.index:
            fig.add_trace(go.Scatter(x=[st_.loc[s, "Annualised SD"]], y=[st_.loc[s, "CAGR"]], mode="markers+text", text=[s], name=s,
                                     textposition="top center", marker=dict(size=13, color=STOCK_COLOR[s], line=dict(color="#fcfcfb", width=2))))
        fig.update_layout(height=340, showlegend=False, xaxis=dict(title="Annualised SD", tickformat=".0%"),
                          yaxis=dict(title="CAGR", tickformat=".0%"), margin=dict(t=20))
        st.plotly_chart(fig, width="stretch")
    c1, c2 = st.columns(2, gap="large")
    with c1:
        order = UNIVERSE_ORDER
        cm = M.corr.loc[order, order]
        fig = px.imshow(cm, text_auto=".2f", color_continuous_scale=["#fcfcfb", "#2a78d6"], zmin=0, zmax=1, aspect="auto")
        fig.update_layout(title="Correlation matrix (daily returns)", height=420, margin=dict(t=50), coloraxis_showscale=False)
        st.plotly_chart(fig, width="stretch")
    with c2:
        sel = st.multiselect("Stocks", UNIVERSE_ORDER, default=UNIVERSE_ORDER, key="ms_cum")
        cum = (1 + M.returns[sel].fillna(0)).cumprod() * 100
        cum = cum.where(M.returns[sel].ffill().notna())            # blank before a stock's first price
        fig = go.Figure()
        for s in sel:
            fig.add_trace(go.Scatter(x=cum.index, y=cum[s], name=s, mode="lines", line=dict(width=2, color=STOCK_COLOR[s])))
        fig.update_layout(title="Growth of 100 (compounded daily returns)", height=420, yaxis=dict(type="log", title=None),
                          legend=dict(orientation="h", y=-0.15), margin=dict(t=50), hovermode="x unified")
        st.plotly_chart(fig, width="stretch")
    with st.expander("Covariance matrix (annualised)"):
        st.dataframe(M.cov.loc[order, order].style.format("{:.4f}"), width="stretch")

# ================================================================== 5. valuation
with tabs[4]:
    st.subheader("Intrinsic value vs market price")
    vs = val_summary()
    st.caption("“Workbook” reproduces the Excel sheets exactly. “Corrected” applies the mechanical fixes listed in the "
               "Model notes tab (EV bridge sign, ONGC final-year PV, Power Grid terminal value & WACC debt, ONGC beta). "
               "Valuation is a screen only — it does not feed the optimiser.")
    fig = go.Figure()
    fig.add_trace(go.Bar(x=vs.Stock, y=vs["Upside (workbook)"], name="Workbook", marker=dict(color="#2a78d6", cornerradius=4)))
    fig.add_trace(go.Bar(x=vs.Stock, y=vs["Upside (corrected)"], name="Corrected", marker=dict(color="#eb6834", cornerradius=4)))
    fig.update_layout(barmode="group", height=320, yaxis=dict(title="Upside / (downside) vs price", tickformat=".0%"), legend=dict(orientation="h", y=1.12),
                      margin=dict(t=30))
    st.plotly_chart(fig, width="stretch")
    st.dataframe(x100(vs.drop(columns=["Changed?"]), ["Discount rate", "Terminal g", "Upside (workbook)", "Upside (corrected)"]), hide_index=True, width="stretch", column_config={
        **{c: st.column_config.NumberColumn(format="%.2f%%") for c in ["Discount rate", "Terminal g", "Upside (workbook)", "Upside (corrected)"]},
        **{c: st.column_config.NumberColumn(format="₹%.2f") for c in ["Market price", "Intrinsic (workbook)", "Intrinsic (corrected)"]}})
    st.divider()
    c1, c2 = st.columns([1, 1])
    stock = c1.selectbox("Stock detail", list(valuation.load_inputs()))
    mode = c2.radio("Mode", ["Workbook", "Corrected"], horizontal=True)
    corrected = mode == "Corrected"
    v = valuation.value_stock(stock, corrected)
    k = st.columns(5)
    k[0].metric("Intrinsic value / share", f"₹{v['value']:,.2f}")
    k[1].metric("Market price", f"₹{v['price']:,.2f}", f"as on {v['as_of']}", delta_color="off")
    k[2].metric("Upside / (downside)", pct(v["upside"]))
    k[3].metric("Discount rate" + (" (Ke)" if v["method"] != "DCF" else " (WACC)"), pct(v["wacc"]))
    k[4].metric("Terminal growth", pct(v["g"]))
    st.caption(f"Method: {v['method']} · beta {v['beta']:.3f} · cost of equity {pct(v['ke'])}" + (f" · debt weight {pct(v['debt_weight'])}" if v["method"] == "DCF" else ""))
    tb = v["table"].copy()
    st.dataframe(tb.style.format({c: "{:,.1f}" for c in tb.columns if c not in ("Year", "Tax")} | {"Tax": "{:.0%}"} if "Tax" in tb else {c: "{:,.1f}" for c in tb.columns if c != "Year"}),
                 hide_index=True, width="stretch")
    st.markdown("**Sensitivity — intrinsic value per share** (rows: terminal growth, columns: discount rate)")
    sens = valuation.sensitivity(stock, corrected)
    sens.index = [f"g {i:.2%}" for i in sens.index]
    sens.columns = [f"{c:.2%}" for c in sens.columns]
    st.dataframe(sens.style.format("₹{:,.0f}").background_gradient(cmap="Blues", axis=None), width="stretch")

# ================================================================== 6. profile comparison
with tabs[5]:
    st.subheader("Side-by-side: optimal portfolio for each risk profile")
    st.caption("The report's sections 9.2/9.3 (Moderate, Conservative) were left open — this fills them. "
               "Each profile needs an A; defaults below are the band mid-point score pushed through the A formula. Edit them freely.")
    base = pd.DataFrame({"Profile": PROFILE_NAMES, "A": [round(risk_profile.representative_A(p, cal), 3) for p in PROFILE_NAMES]})
    edited = st.data_editor(base, hide_index=True, disabled=["Profile"], column_config={"A": st.column_config.NumberColumn(min_value=0.0, step=0.05)})
    rows, wrows = [], []
    for r in edited.itertuples():
        rr = run_reco(r.Profile, float(r.A), M.mapping[r.Profile]["max_sd"])
        if rr.best is None:
            rows.append({"Profile": r.Profile, "A": r.A, "Max SD": M.mapping[r.Profile]["max_sd"], "Portfolio": None}); continue
        b = rr.best; p = M.performance_of(b)
        rows.append({"Profile": r.Profile, "A": r.A, "Max SD": M.mapping[r.Profile]["max_sd"], "Portfolio": int(b["id"]), "Category": b["category"],
                     "Holdings": f"{b.stock_1} {b.w_1:.1%} · {b.stock_2} {b.w_2:.1%} · {b.stock_3} {b.w_3:.1%}",
                     "Exp. return": b.expected_return, "SD": b.sd, "Utility": b.utility, "Sharpe": p["sharpe"], "Beta": p["beta"]})
        for n, w in zip(p["names"], p["weights"]):
            wrows.append({"Profile": r.Profile, "Stock": n, "Weight": w})
    cmp_df = pd.DataFrame(rows)
    st.dataframe(x100(cmp_df, [c for c in ["Max SD", "Exp. return", "SD"] if c in cmp_df]), hide_index=True, width="stretch", column_config={
        "Max SD": st.column_config.NumberColumn(format="%.1f%%"), "Exp. return": st.column_config.NumberColumn(format="%.2f%%"),
        "SD": st.column_config.NumberColumn(format="%.2f%%"), "Utility": st.column_config.NumberColumn(format="%.4f"),
        "Sharpe": st.column_config.NumberColumn(format="%.3f"), "Beta": st.column_config.NumberColumn(format="%.3f")})
    if wrows:
        W = pd.DataFrame(wrows)
        fig = px.bar(W, x="Profile", y="Weight", color="Stock", color_discrete_map=STOCK_COLOR, category_orders={"Profile": PROFILE_NAMES})
        fig.update_traces(marker_line=dict(color="#fcfcfb", width=2))
        fig.update_layout(height=360, yaxis=dict(tickformat=".0%", title=None), xaxis=dict(title=None), legend=dict(orientation="h", y=-0.15))
        st.plotly_chart(fig, width="stretch")

# ================================================================== 7. notes
with tabs[6]:
    st.subheader("How the Excel model maps to this app")
    st.markdown("""
| Excel | Python |
|---|---|
| Questionnaire workbook (Scoring Key, Input, A model) | `sa/risk_profile.py` · tab 1 |
| `SD and Correlation`, `Data Sheet for Classification` | `sa/market.py` · tab 4 |
| `Portfolios`, `Portfolio Classification`, `Client Mapping` | `sa/portfolios.py` · tab 3 |
| `Optimization Engine` + VBA `OptimiseAllPortfolios` (Solver, GRG) | `sa/optimizer.py` (SciPy SLSQP) · tab 2 |
| VBA 30-second `CheckForNewSubmission` monitor | not needed — Streamlit recalculates on every input change |
| Portfolio Presentation (Sharpe / Treynor / Jensen) | `sa/performance.py` · tab 2 |
| Stock sheets (DCF / Residual Income) | `sa/valuation.py` · tab 5 |

`tests/test_parity.py` checks the Python output against the cached Excel values: statistics, betas, all 56 classifications,
questionnaire scores, the 25 Solver results (same feasible set as the macro), Sharpe/Treynor/Alpha and all 8 valuations.
""")
    st.subheader("Workbook issues found while porting")
    st.caption("The app reproduces the workbook by default. None of these change the optimisation result for the Aggressive profile "
               "except where marked; the valuation items change the valuation screen only.")
    issues = pd.DataFrame([
        ("High", "Valuation", "Lupin, Power Grid, ONGC: EV bridge adds debt and subtracts cash (equity = EV + debt − cash). Should be EV − debt + cash. Drives most of Power Grid (+124%) and ONGC (+364%) 'upside'."),
        ("High", "Valuation", "ONGC: beta hard-coded at 0.07 (peer average in the same sheet is 0.70); Rm 13.5% vs 10.3% in the other sheets; final-year FCFF is never discounted (only the terminal value is)."),
        ("High", "Valuation", "Power Grid: 'Total debt' for WACC is actually cash (₹9,138 cr), pre-tax cost of debt = cash ÷ debt, and terminal value omits ×(1+g)."),
        ("Medium", "Eligibility", "Client Mapping text for Moderate is 'Dividend Yield , Flexi Cap…' (stray space) so the Excel SEARCH test silently drops Dividend Yield portfolios for Moderate. The app uses the intended list from the report."),
        ("Medium", "Data", "Waaree and ITC balance-sheet inputs equal TCS's (debt ₹2,399.36 cr / cash ₹7,247.03 cr; ITC cash 7,247.03) — likely copy-paste, please verify."),
        ("Medium", "Beta / alpha", "Betas use a 1-year window (Apr-2022 – Mar-2023) and Waaree's 0.93 is hard-coded; Jensen's Rm (13.5%) is taken from the ONGC sheet while the other sheets use 10.3%."),
        ("Low", "Questionnaire", "Grand Total uses COUNT on letter answers (always 0), so partial answers still total. The app requires all 12 answers."),
        ("Low", "Correlation", "Cell H14 references Lupin–ITC instead of INDRAMEDCO–ITC; the matrix is slightly asymmetric but no portfolio reads the affected cell."),
        ("Low", "Valuation", "Axis Bank total value adds the terminal-growth rate (0.06) to the sum — ₹0.0002/share."),
        ("Info", "Method", "Expected return = historical CAGR (Waaree: 3-year window, 58%), so every top Aggressive portfolio contains Waaree — a concentration in one input, as the report notes."),
    ], columns=["Severity", "Area", "Finding"])
    st.dataframe(issues, hide_index=True, width="stretch", column_config={"Finding": st.column_config.TextColumn(width="large")})
    st.markdown("**Refreshing the data:** edit the workbook, then run `python scripts/extract_from_excel.py <macro.xlsm> <questionnaire.xlsx>` "
                "to regenerate `data/` and `tests/excel_reference.json`, then `pytest`.")
