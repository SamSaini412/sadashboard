"""Historical risk/return statistics: annualised SD, CAGR, correlation, covariance, betas."""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parents[1] / "data"
TRADING_DAYS = 252


def load_returns() -> pd.DataFrame:
    return pd.read_csv(DATA / "returns.csv", parse_dates=["date"]).set_index("date")


def load_market_inputs() -> dict:
    return json.loads((DATA / "market_inputs.json").read_text())


def annual_sd(returns: pd.DataFrame) -> pd.Series:
    return returns.std(ddof=1) * np.sqrt(TRADING_DAYS)


def cagr(inputs: dict) -> pd.Series:
    return pd.Series({k: (v["end"] / v["start"]) ** (1 / v["years"]) - 1 for k, v in inputs.items()})


def correlation(returns: pd.DataFrame) -> pd.DataFrame:
    """Pairwise-complete correlation (Waaree has a shorter history, as in the workbook)."""
    return returns.corr()


def covariance(returns: pd.DataFrame) -> pd.DataFrame:
    sd = annual_sd(returns)
    return correlation(returns) * np.outer(sd, sd)


def beta_vs_nifty(returns: pd.DataFrame, overrides: dict | None = None) -> pd.Series:
    """Single-index beta over the workbook's 1-year window (Apr-2022..Mar-2023), cov.s/var.s on matched dates."""
    nifty = pd.read_csv(DATA / "nifty_window.csv", parse_dates=["date"]).set_index("date")["Nifty"]
    out = {}
    for s in returns.columns:
        j = pd.concat([nifty, returns[s]], axis=1, join="inner").dropna()
        # Excel: COVARIANCE.S on matched pairs / VAR.S on the full Nifty window
        out[s] = j.cov().iloc[0, 1] / nifty.var() if len(j) > 30 else np.nan
    out = pd.Series(out)
    for k, v in (overrides or {}).items():
        out[k] = v
    return out
