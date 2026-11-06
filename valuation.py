"""Equity valuation — port of the per-stock sheets.

Seven non-financials: FCFF DCF (WACC discounting, perpetual-growth terminal value).
Axis Bank: Residual Income (discounted at cost of equity).

Two modes
  * corrected=False (default) reproduces the Excel workbook exactly, including its formula quirks.
  * corrected=True applies the mechanical fixes listed in CORRECTIONS (see Model Notes tab).
"""
from __future__ import annotations
import json
from copy import deepcopy
from pathlib import Path
import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parents[1] / "data"

# What "corrected" changes, per stock (descriptions shown in the dashboard).
CORRECTIONS = {
    "Lupin": dict(net_debt_sign=1,
                  note="EV bridge: equity = EV − debt + cash (workbook added debt and subtracted cash)."),
    "Power Grid": dict(net_debt_sign=1, tv_uses_growth=True, wacc_debt="debt", kd_from_interest=True,
                       note="EV bridge sign; terminal value × (1+g); WACC uses borrowings (workbook used cash "
                            "as 'debt' and cash ÷ debt as cost of debt)."),
    "ONGC": dict(net_debt_sign=1, final_fcff_in_pv=True, beta="peers",
                 note="EV bridge sign; final-year FCFF now discounted; beta = peer average (workbook hard-codes 0.07)."),
}


def load_inputs() -> dict:
    return json.loads((DATA / "valuation_inputs.json").read_text())


def peer_betas(stock: str) -> pd.Series:
    """OLS slope of each peer's daily return on Nifty over the workbook window."""
    df = pd.read_csv(DATA / "beta_peers" / f"{stock.replace(' ', '_')}.csv", parse_dates=["date"]).set_index("date")
    out = {}
    var_full = df["Nifty"].var()          # Excel: VAR.S over the whole Nifty column
    for c in df.columns[1:]:
        j = df[["Nifty", c]].dropna()     # Excel: COVARIANCE.S drops incomplete pairs
        out[c] = j.cov().iloc[0, 1] / var_full
    return pd.Series(out)


def _effective_cfg(stock: str, corrected: bool) -> dict:
    cfg = deepcopy(load_inputs()[stock])
    wb = cfg.get("workbook", {})
    if corrected and stock in CORRECTIONS:
        fx = CORRECTIONS[stock]
        for k in ("net_debt_sign", "tv_uses_growth", "final_fcff_in_pv"):
            if k in fx:
                wb[k] = fx[k]
        if fx.get("wacc_debt") == "debt":
            cfg["wacc"]["debt"] = cfg["debt"]
        if fx.get("kd_from_interest"):
            cfg["wacc"]["kd_pretax"] = cfg["wacc"]["interest0"] / cfg["wacc"]["debt"]
        if fx.get("beta") == "peers":
            cfg["wacc"]["beta_mode"], cfg["wacc"]["beta_fixed"] = "peers", None
    cfg["workbook"] = wb
    return cfg


def cost_of_equity(stock: str, cfg: dict) -> tuple[float, float]:
    w = cfg["wacc"]
    beta = w["beta_fixed"] if w["beta_mode"] == "fixed" else float(peer_betas(stock).mean())
    return w["rf"] + beta * (w["rm"] - w["rf"]), beta


def wacc_dcf(stock: str, cfg: dict) -> dict:
    w = cfg["wacc"]
    ke, beta = cost_of_equity(stock, cfg)
    d, e = w["debt"], w["equity_mv"]
    kd_post = w["kd_pretax"] * (1 - w["tax"])
    wacc = kd_post * d / (d + e) + ke * e / (d + e)
    return dict(wacc=wacc, ke=ke, beta=beta, kd_pretax=w["kd_pretax"], kd_post=kd_post, debt_weight=d / (d + e))


def value_stock(stock: str, corrected: bool = False, wacc: float | None = None, g: float | None = None) -> dict:
    """Intrinsic value per share for one stock. `wacc` / `g` override the model values (for sensitivities)."""
    cfg = _effective_cfg(stock, corrected)
    return _value_ri(stock, cfg, corrected, wacc, g) if cfg["method"] == "RI" else _value_dcf(stock, cfg, wacc, g)


def _value_dcf(stock, cfg, wacc_ovr, g_ovr):
    wb = cfg["workbook"]
    wc = wacc_dcf(stock, cfg)
    W = wc["wacc"] if wacc_ovr is None else wacc_ovr
    g = cfg["terminal_growth"] if g_ovr is None else g_ovr
    n = len(cfg["growth"])
    rev = [cfg["revenue0"]]
    for gr in cfg["growth"]:
        rev.append(rev[-1] * (1 + gr))
    rev = np.array(rev)
    cfo = rev * cfg["cfo_margin"]
    capex = np.concatenate([[cfg["capex0"]], rev[1:] * np.array(cfg["capex_pct"])])
    interest = rev * cfg["interest_ratio"]
    tax = np.array(cfg["tax"])
    fcff = cfo - capex + interest * (1 - tax)
    tv = fcff[-1] * ((1 + g) if wb["tv_uses_growth"] else 1.0) / (W - g)
    t = np.arange(0, n + 1)
    pv = np.zeros(n + 1)
    pv[1:] = fcff[1:] / (1 + W) ** t[1:]                       # year 0 (base year) is not discounted/valued
    last = (fcff[-1] + tv) if wb["final_fcff_in_pv"] else tv
    pv[-1] = last / (1 + W) ** n
    firm = pv[1:].sum()
    equity = firm + wb["net_debt_sign"] * (cfg["cash"] - cfg["debt"])
    value = equity / cfg["shares"]
    table = pd.DataFrame(dict(Year=cfg["years"], Revenue=rev, CFO=cfo, CAPEX=capex, Interest=interest, Tax=tax,
                              FCFF=fcff, **{"PV": pv}))
    return dict(stock=stock, method="DCF", value=value, price=cfg["price"], upside=value / cfg["price"] - 1,
                wacc=W, g=g, ke=wc["ke"], beta=wc["beta"], debt_weight=wc["debt_weight"], enterprise_value=firm,
                terminal_value=tv, equity_value=equity, table=table, as_of=cfg["as_of"], shares=cfg["shares"])


def _value_ri(stock, cfg, corrected, ke_ovr, g_ovr):
    w = cfg["wacc"]
    ke_model, beta = cost_of_equity(stock, cfg)
    ke = ke_model if ke_ovr is None else ke_ovr
    g = cfg["terminal_growth"] if g_ovr is None else g_ovr
    n = len(cfg["years"]) - 1
    pat = [cfg["pat0"] * (1 + cfg["pat_growth"]) ** i for i in range(n + 1)]
    div = [p * cfg["payout"] for p in pat]
    opening, closing = [cfg["opening_bv"]], []
    for i in range(n + 1):
        closing.append(opening[i] + pat[i] - div[i])
        if i < n:
            opening.append(closing[i])
    charge = [ke * o for o in opening]
    ri = [p - c for p, c in zip(pat, charge)]
    tv = ri[-1] * (1 + g) / (ke - g)
    pv = [0.0] + [ri[i] / (1 + ke) ** i for i in range(1, n)] + [(ri[n] + tv) / (1 + ke) ** n]
    total_pv = sum(pv)
    # workbook quirk: C17 = SUM(C14:C16) also adds the terminal-growth *rate* (≈ ₹0.06) to the value
    value_total = total_pv + closing[0] + (0 if corrected else g)
    value = value_total / cfg["shares"]
    table = pd.DataFrame(dict(Year=cfg["years"], **{"Opening BV": opening, "PAT": pat, "Dividend": div,
                              "Closing BV": closing, "Equity charge": charge, "Residual income": ri, "PV": pv}))
    return dict(stock=stock, method="Residual Income", value=value, price=cfg["price"], upside=value / cfg["price"] - 1,
                wacc=ke, g=g, ke=ke, beta=beta, debt_weight=0.0, enterprise_value=total_pv, terminal_value=tv,
                equity_value=value_total, table=table, as_of=cfg["as_of"], shares=cfg["shares"])


def sensitivity(stock: str, corrected: bool = False, d_wacc=(-0.01, -0.005, 0, 0.005, 0.01),
                d_g=(-0.005, -0.0025, 0, 0.0025, 0.005)) -> pd.DataFrame:
    base = value_stock(stock, corrected)
    rows = {}
    for dg in d_g:
        rows[base["g"] + dg] = [value_stock(stock, corrected, wacc=base["wacc"] + dw, g=base["g"] + dg)["value"]
                                for dw in d_wacc]
    return pd.DataFrame(rows, index=[base["wacc"] + dw for dw in d_wacc]).T


def summary_table() -> pd.DataFrame:
    rows = []
    for s in load_inputs():
        a, b = value_stock(s), value_stock(s, corrected=True)
        rows.append({"Stock": s, "Method": a["method"], "Discount rate": a["wacc"], "Terminal g": a["g"],
                     "Market price": a["price"], "Intrinsic (workbook)": a["value"], "Upside (workbook)": a["upside"],
                     "Intrinsic (corrected)": b["value"], "Upside (corrected)": b["upside"],
                     "Changed?": s in CORRECTIONS, "Correction note": CORRECTIONS.get(s, {}).get("note", "")})
    return pd.DataFrame(rows)
