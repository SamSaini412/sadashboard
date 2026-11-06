"""Parity tests: Python results vs the cached values stored in the original Excel workbooks.
Run:  python -m pytest -q tests   (or: python tests/test_parity.py)"""
import json, sys
from pathlib import Path
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sa import SAModel, risk_profile, valuation, performance  # noqa: E402

REF = json.loads((ROOT / "tests" / "excel_reference.json").read_text())
M = SAModel()


def test_market_statistics():
    for s, v in REF["sd_corr"]["sd_yearly"].items():
        assert M.sd[s] == pytest.approx(v, rel=1e-9)
    for s, v in REF["sd_corr"]["cagr"].items():
        assert M.mu[s] == pytest.approx(v, rel=1e-9)


def test_correlation_and_covariance_match_workbook():
    names = list(REF["sd_corr"]["sd_yearly"])            # workbook column order
    xc = np.array(REF["sd_corr"]["cov"], float)
    pc = M.cov.loc[names, names].values
    diff = np.abs(xc - pc)
    # one known harmless asymmetry in the workbook (ITC row / INDRAMEDCO col mis-reference, cell H14)
    i, j = names.index("ITC"), names.index("INDRAMEDCO")
    diff[i, j] = 0
    assert diff.max() < 1e-9


def test_betas_vs_nifty():
    for s, v in REF["classification"].items():
        assert M.beta[s] == pytest.approx(v["beta"], rel=1e-9)


def test_classification_matches_workbook():
    P = M.portfolios.set_index("id")
    for r in REF["portfolios"]:
        p = P.loc[r["id"]]
        assert [p.stock_1, p.stock_2, p.stock_3] == [s.strip() for s in r["stocks"]]
        assert p.div_yield == pytest.approx(r["div_yield"], rel=1e-9)
        assert p.growth == pytest.approx(r["growth"], rel=1e-9)
        assert p.sd == pytest.approx(r["sd"], rel=1e-8)
        assert p.beta == pytest.approx(r["beta"], rel=1e-9)
        assert p.category == r["category"], r["id"]


def test_questionnaire():
    q = REF["questionnaire"]
    ans = {i + 1: a for i, a in enumerate(q["answers"])}
    r = risk_profile.score_questionnaire(ans)
    assert (r.capacity, r.tolerance, r.total, r.profile) == (q["rc"], q["rt"], q["total"], q["profile"])
    assert (r.capacity_band, r.tolerance_band) == (q["cap_band"], q["tol_band"])
    assert r.rpi == pytest.approx(q["rpi"]) and r.risk_aversion == pytest.approx(q["A"])


def test_every_possible_profile_boundary():
    for total, name in [(5, "Very Conservative"), (11, "Very Conservative"), (12, "Conservative"), (19, "Conservative"),
                        (20, "Moderate"), (28, "Moderate"), (29, "Aggressive"), (36, "Aggressive"),
                        (37, "Very Aggressive"), (45, "Very Aggressive")]:
        assert risk_profile._band(total, risk_profile.PROFILE_BANDS) == name


def test_solver_results_match_excel_macro():
    rec = M.recommend("Aggressive", REF["engine_inputs"]["A"], REF["engine_inputs"]["max_sd"])
    got = rec.results.set_index("id")
    assert len(rec.results) == len(REF["engine_results"]) == 25          # same feasible set as the macro
    for r in REF["engine_results"]:
        g = got.loc[r["id"]]
        assert g.utility == pytest.approx(r["utility"], abs=2e-6), r["id"]
        assert g.expected_return == pytest.approx(r["ret"], abs=2e-5), r["id"]
        assert [g.w_1, g.w_2, g.w_3] == pytest.approx(r["weights"], abs=2e-3), r["id"]
    assert int(rec.best["id"]) == REF["best"]["id"] == 1015


def test_performance_metrics():
    rec = M.recommend("Aggressive", REF["engine_inputs"]["A"], REF["engine_inputs"]["max_sd"])
    p = M.performance_of(rec.best)
    ref = REF["performance"]
    assert M.rf == pytest.approx(ref["rf"]) and M.rm == pytest.approx(ref["rm"])
    assert p["beta"] == pytest.approx(ref["beta"], abs=1e-3)
    assert p["sharpe"] == pytest.approx(ref["sharpe"], abs=1e-4)
    assert p["treynor"] == pytest.approx(ref["treynor"], abs=1e-4)
    assert p["alpha"] == pytest.approx(ref["alpha"], abs=1e-4)


@pytest.mark.parametrize("stock", list(REF["valuation"]))
def test_valuation_matches_workbook(stock):
    ref, got = REF["valuation"][stock], valuation.value_stock(stock)
    assert got["value"] == pytest.approx(ref["value"], rel=1e-9)
    if "wacc" in ref:
        assert got["wacc"] == pytest.approx(ref["wacc"], rel=1e-9)
        assert got["ke"] == pytest.approx(ref["ke"], rel=1e-9)
        assert got["beta"] == pytest.approx(ref["beta"], rel=1e-9)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
