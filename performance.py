"""Risk-adjusted performance: Sharpe, Treynor, Jensen's alpha (port of the Portfolio Presentation workbook)."""
from __future__ import annotations
import numpy as np


def portfolio_beta(weights, betas) -> float:
    return float(np.dot(weights, betas))


def sharpe(rp: float, rf: float, sd: float) -> float:
    return (rp - rf) / sd


def treynor(rp: float, rf: float, beta_p: float) -> float:
    return (rp - rf) / beta_p


def jensen_alpha(rp: float, rf: float, rm: float, beta_p: float) -> float:
    return rp - (rf + beta_p * (rm - rf))


def summary(weights, mu, cov, betas, rf: float, rm: float) -> dict:
    w = np.asarray(weights, float)
    rp = float(w @ np.asarray(mu, float))
    sd = float(np.sqrt(w @ np.asarray(cov, float) @ w))
    b = portfolio_beta(w, betas)
    return dict(expected_return=rp, sd=sd, beta=b, sharpe=sharpe(rp, rf, sd),
                treynor=treynor(rp, rf, b), alpha=jensen_alpha(rp, rf, rm, b))
