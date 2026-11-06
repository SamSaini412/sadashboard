"""Utility-maximising optimiser — Python replacement for the Excel Solver macro (OptimiseAllPortfolios).

For each eligible three-stock portfolio:
    maximise   U = E(Rp) - (A/2) * sigma_p^2
    subject to sum(w) = 1,  w >= 0,  sigma_p <= max_sd
The problem is a concave objective over a convex set, so a local solver finds the global optimum.
Acceptance tests mirror the macro: weights sum to 1 (+-0.001), no negative weights, SD <= ceiling + 0.0001.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from scipy.optimize import minimize

TOL = 1e-4


def _solve(mu, cov, A, max_sd, x0):
    n = len(mu)
    cons = [{"type": "eq", "fun": lambda w: w.sum() - 1.0}]
    if max_sd is not None:
        cons.append({"type": "ineq", "fun": lambda w: max_sd ** 2 - w @ cov @ w})
    return minimize(lambda w: -(mu @ w - A / 2 * w @ cov @ w), x0, method="SLSQP",
                    bounds=[(0, 1)] * n, constraints=cons,
                    options={"maxiter": 1000, "ftol": 1e-13})


def min_variance(cov):
    n = len(cov)
    r = minimize(lambda w: w @ cov @ w, np.full(n, 1 / n), method="SLSQP", bounds=[(0, 1)] * n,
                 constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1}], options={"ftol": 1e-14, "maxiter": 500})
    return r.x


def optimise_portfolio(mu, cov, A: float, max_sd: float | None):
    """Return dict(weights, ret, sd, utility, binding) or dict(failed=reason)."""
    mu, cov = np.asarray(mu, float), np.asarray(cov, float)
    n = len(mu)
    wmin = min_variance(cov)
    min_sd = float(np.sqrt(wmin @ cov @ wmin))
    if max_sd is not None and min_sd > max_sd + TOL:
        return dict(failed=f"Infeasible: lowest achievable SD {min_sd:.2%} exceeds ceiling {max_sd:.2%}")
    starts = [np.full(n, 1 / n), wmin] + [np.eye(n)[i] * 0.8 + 0.1 for i in range(n)]
    best = None
    for x0 in starts:
        r = _solve(mu, cov, A, max_sd, x0)
        w = np.clip(r.x, 0, None); w = w / w.sum()
        sd = float(np.sqrt(w @ cov @ w))
        if max_sd is not None and sd > max_sd + TOL:
            continue
        u = float(mu @ w - A / 2 * w @ cov @ w)
        if best is None or u > best["utility"]:
            best = dict(weights=w, ret=float(mu @ w), sd=sd, utility=u,
                        binding=bool(max_sd is not None and sd >= max_sd - TOL))
    return best or dict(failed="Solver did not converge to a feasible solution")


def optimise_all(eligible: pd.DataFrame, mu: pd.Series, cov: pd.DataFrame, A: float, max_sd: float):
    """Optimise every eligible portfolio; return (results_df sorted by utility, failures_df)."""
    ok, bad = [], []
    for r in eligible.itertuples():
        names = [r.stock_1, r.stock_2, r.stock_3]
        res = optimise_portfolio(mu[names].values, cov.loc[names, names].values, A, max_sd)
        if "failed" in res:
            bad.append(dict(id=r.id, stock_1=names[0], stock_2=names[1], stock_3=names[2],
                            category=r.category, reason=res["failed"]))
            continue
        w = res["weights"]
        ok.append(dict(id=r.id, stock_1=names[0], stock_2=names[1], stock_3=names[2], category=r.category,
                       w_1=w[0], w_2=w[1], w_3=w[2], expected_return=res["ret"], sd=res["sd"],
                       utility=res["utility"], sd_binding=res["binding"]))
    res_df = pd.DataFrame(ok)
    if not res_df.empty:
        res_df = res_df.sort_values("utility", ascending=False).reset_index(drop=True)
        res_df.insert(0, "rank", np.arange(1, len(res_df) + 1))
    return res_df, pd.DataFrame(bad)


def sample_feasible(mu, cov, A, max_sd, n=4000, seed=7):
    """Random long-only weight vectors (for the risk/return cloud chart)."""
    rng = np.random.default_rng(seed)
    w = rng.dirichlet(np.ones(len(mu)), size=n)
    ret = w @ mu
    var = np.einsum("ij,jk,ik->i", w, cov, w)
    sd = np.sqrt(var)
    return pd.DataFrame(dict(ret=ret, sd=sd, utility=ret - A / 2 * var, feasible=sd <= max_sd + TOL))
