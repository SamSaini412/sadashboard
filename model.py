"""High-level facade that wires data, statistics, classification, optimisation and performance together."""
from __future__ import annotations
import json
from dataclasses import dataclass
import numpy as np
import pandas as pd
from . import market, portfolios, optimizer, performance, risk_profile
from .market import DATA


@dataclass
class Recommendation:
    profile: str
    A: float
    max_sd: float
    eligible: pd.DataFrame
    results: pd.DataFrame
    failures: pd.DataFrame

    @property
    def best(self):
        return None if self.results.empty else self.results.iloc[0]


class SAModel:
    def __init__(self):
        inp = market.load_market_inputs()
        self.inputs = inp
        self.returns = market.load_returns()
        self.universe = list(self.returns.columns)
        self.rf = inp["rf"]
        self.rm = inp["rm_jensen"]
        self.mapping = json.loads((DATA / "client_mapping.json").read_text())
        # per-stock statistics
        self.sd_daily = self.returns.std(ddof=1)
        self.sd = market.annual_sd(self.returns)
        self.mu = market.cagr(inp["cagr"])[self.universe]            # expected return proxy = historical CAGR
        self.corr = market.correlation(self.returns)
        self.cov = market.covariance(self.returns)
        overrides = {k: v["beta_override"] for k, v in inp["classification"].items() if v["beta_override"] is not None}
        self.beta = market.beta_vs_nifty(self.returns, overrides)
        self.stock_inputs = portfolios.classification_inputs(inp, self.sd, self.beta)
        self.portfolios = portfolios.build_portfolios(self.stock_inputs, self.cov)

    # ------------------------------------------------------------------ views
    def stock_table(self) -> pd.DataFrame:
        t = pd.DataFrame({"CAGR": self.mu, "Annualised SD": self.sd, "Beta (vs Nifty)": self.beta,
                          "Dividend yield": self.stock_inputs["dividend_yield"],
                          "EBITDA growth": self.stock_inputs["ebitda_growth"]})
        t["Return / risk"] = t["CAGR"] / t["Annualised SD"]
        return t.loc[portfolios.UNIVERSE_ORDER]

    def category_counts(self) -> pd.Series:
        return self.portfolios["category"].value_counts()

    # ------------------------------------------------------------------ engine
    def recommend(self, profile: str, A: float, max_sd: float | None = None) -> Recommendation:
        max_sd = self.mapping[profile]["max_sd"] if max_sd is None else max_sd
        elig = portfolios.eligible(self.portfolios, profile, self.mapping)
        res, bad = optimizer.optimise_all(elig, self.mu, self.cov, A, max_sd)
        return Recommendation(profile, A, max_sd, elig, res, bad)

    def performance_of(self, row) -> dict:
        names = [row["stock_1"], row["stock_2"], row["stock_3"]]
        w = [row["w_1"], row["w_2"], row["w_3"]]
        out = performance.summary(w, self.mu[names].values, self.cov.loc[names, names].values,
                                  self.beta[names].values, self.rf, self.rm)
        out["names"], out["weights"] = names, w
        return out
