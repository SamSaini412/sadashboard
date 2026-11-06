"""Three-stock portfolio universe (8C3 = 56), classification into 4 categories, client eligibility."""
from __future__ import annotations
from itertools import combinations
import numpy as np
import pandas as pd

UNIVERSE_ORDER = ["TCS", "INDRAMEDCO", "Lupin", "Waaree", "ITC", "Power Grid", "ONGC", "Axis Bank"]
TOP_N = 14  # ranking cut-off used by the workbook's category rule


def classification_inputs(mkt_inputs: dict, sd_annual: pd.Series, betas: pd.Series) -> pd.DataFrame:
    rows = {}
    for name, c in mkt_inputs["classification"].items():
        dy = c["dividend_per_share"] / c["price_for_yield"] if c["price_for_yield"] else 0.0
        g = (c["ebitda_end"] / c["ebitda_start"]) ** (1 / c["ebitda_years"]) - 1
        rows[name] = dict(dividend_yield=dy, ebitda_growth=g, sd=sd_annual[name], beta=betas[name])
    return pd.DataFrame(rows).T


def build_portfolios(stock_inputs: pd.DataFrame, cov: pd.DataFrame, order=UNIVERSE_ORDER) -> pd.DataFrame:
    recs = []
    for i, combo in enumerate(combinations(order, 3), start=1):
        w = np.full(3, 1 / 3)
        sub = cov.loc[list(combo), list(combo)].values
        recs.append(dict(
            id=1000 + i, stock_1=combo[0], stock_2=combo[1], stock_3=combo[2],
            div_yield=stock_inputs.loc[list(combo), "dividend_yield"].mean(),
            growth=stock_inputs.loc[list(combo), "ebitda_growth"].mean(),
            sd=float(np.sqrt(w @ sub @ w)),                       # equal-weight portfolio SD
            beta=stock_inputs.loc[list(combo), "beta"].mean()))
    df = pd.DataFrame(recs)
    return categorise(df)


def categorise(df: pd.DataFrame, top_n: int = TOP_N) -> pd.DataFrame:
    """Sequential rule from the workbook: top-N dividend yield -> Dividend Yield; else top-N growth ->
    Growth Equity; else lowest-N SD -> Defensive Equity; else Flexi Cap."""
    div_cut = df["div_yield"].nlargest(top_n).iloc[-1]
    gr_cut = df["growth"].nlargest(top_n).iloc[-1]
    sd_cut = df["sd"].nsmallest(top_n).iloc[-1]
    def rule(r):
        if r.div_yield >= div_cut: return "Dividend Yield"
        if r.growth >= gr_cut: return "Growth Equity"
        if r.sd <= sd_cut: return "Defensive Equity"
        return "Flexi Cap"
    out = df.copy()
    out["category"] = [rule(r) for r in out.itertuples()]
    return out


def eligible(portfolios: pd.DataFrame, profile: str, mapping: dict) -> pd.DataFrame:
    cats = mapping[profile]["categories"]
    return portfolios[portfolios["category"].isin(cats)].reset_index(drop=True)
