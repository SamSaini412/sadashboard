"""Extract every input the Python model needs from the original Excel workbooks.

Usage:  python scripts/extract_from_excel.py <SA_Macro_Enabled.xlsm> <Questionnaire.xlsx>

Writes CSV/JSON files into ./data (returns, beta windows, valuation inputs, scoring key,
client mapping, market inputs) and ./tests/excel_reference.json (cached Excel results that the
parity tests compare against).  Re-run it if the workbook inputs change.
"""
import json, re, sys
from pathlib import Path
import openpyxl
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
STOCK_SHEETS = ["TCS", "INDRAMEDCO", "Lupin", "Waaree", "ITC", "Power Grid", "ONGC", "Axis Bank"]


def r10(x):
    return None if x is None else round(float(x), 10)


def main(macro_path, quest_path):
    wf = openpyxl.load_workbook(macro_path, keep_vba=True)           # formulas
    wv = openpyxl.load_workbook(macro_path, data_only=True)          # cached values
    ref = {}

    # ---------------------------------------------------------------- daily returns
    sd = wv["SD and Correlation"]
    names = [str(sd.cell(3, c).value).strip() for c in range(3, 11)]
    rows = []
    for r in range(34, 1522):
        d = sd.cell(r, 2).value
        vals = [sd.cell(r, c).value for c in range(3, 11)]
        if d is None or all(v is None for v in vals):
            continue
        rows.append([d.date().isoformat()] + vals)
    pd.DataFrame(rows, columns=["date"] + names).to_csv(DATA / "returns.csv", index=False)

    # ---------------------------------------------------------------- CAGR inputs
    cagr = {}
    for c in range(3, 11):
        f = wf["SD and Correlation"].cell(6, c).value
        m = re.match(r"=\(([\d.]+)/([\d.]+)\)\^\(1/(\d+)\)-1", f)
        cagr[names[c - 3]] = dict(end=float(m[1]), start=float(m[2]), years=int(m[3]))

    # ---------------------------------------------------------------- classification inputs
    ds, dsv = wf["Data Sheet for Classification"], wv["Data Sheet for Classification"]
    cls = {}
    for r in range(3, 11):
        nm = ds.cell(r, 2).value.strip()
        dy = ds.cell(r, 3).value
        if isinstance(dy, str):
            a, b = re.match(r"=([\d.]+)/([\d.]+)", dy).groups()
            dps, price = float(a), float(b)
        else:
            dps, price = 0.0, None
        m = re.match(r"=\(([\d.]+)/([\d.]+)\)\^\(1/(\d+)\)-1", ds.cell(r, 4).value)
        beta_cell = ds.cell(r, 6).value
        cls[nm] = dict(dividend_per_share=dps, price_for_yield=price,
                       ebitda_end=float(m[1]), ebitda_start=float(m[2]), ebitda_years=int(m[3]),
                       beta_override=None if isinstance(beta_cell, str) else float(beta_cell))
    ref["classification"] = {ds.cell(r, 2).value.strip(): dict(
        dividend_yield=dsv.cell(r, 3).value, ebitda_growth=dsv.cell(r, 4).value,
        sd=dsv.cell(r, 5).value, beta=dsv.cell(r, 6).value) for r in range(3, 11)}

    # ---------------------------------------------------------------- Nifty beta window (TCS sheet)
    t = wv["TCS"]
    nifty = [(t.cell(r, 2).value.date().isoformat(), t.cell(r, 3).value) for r in range(44, 292)]
    pd.DataFrame(nifty, columns=["date", "Nifty"]).to_csv(DATA / "nifty_window.csv", index=False)

    # ---------------------------------------------------------------- client mapping
    cm = wv["Client Mapping"]
    mapping = {}
    for r in range(3, 8):
        cats = [x.strip() for x in str(cm.cell(r, 3).value).split(",")]
        mapping[cm.cell(r, 2).value.strip()] = dict(categories=cats, max_sd=float(cm.cell(r, 4).value))
    (DATA / "client_mapping.json").write_text(json.dumps(mapping, indent=2))

    # ---------------------------------------------------------------- portfolio classification (reference)
    pc = wv["Portfolio Classification"]
    ref["portfolios"] = [dict(id=pc.cell(r, 2).value, stocks=[pc.cell(r, c).value for c in (3, 4, 5)],
                              div_yield=pc.cell(r, 6).value, growth=pc.cell(r, 7).value,
                              sd=pc.cell(r, 8).value, beta=pc.cell(r, 9).value,
                              category=pc.cell(r, 10).value) for r in range(3, 59)]

    # ---------------------------------------------------------------- engine reference (Aggressive run)
    oe = wv["Optimization Engine"]
    ref["engine_results"] = [dict(id=oe.cell(r, 1).value, stocks=[oe.cell(r, c).value for c in (2, 3, 4)],
                                  weights=[oe.cell(r, c).value for c in (5, 6, 7)],
                                  ret=oe.cell(r, 8).value, sd=oe.cell(r, 9).value, utility=oe.cell(r, 10).value)
                             for r in range(19, 44) if oe.cell(r, 1).value]
    ref["engine_inputs"] = dict(A=oe["K13"].value, max_sd=oe["B3"].value, profile=oe["B2"].value)
    ref["best"] = dict(id=oe["B5"].value, weights=[oe.cell(r, 3).value for r in (9, 10, 11)],
                       ret=oe["K9"].value, sd=oe["K11"].value, utility=oe["K14"].value)
    ref["sd_corr"] = dict(
        sd_yearly={n: sd.cell(5, c).value for n, c in zip(names, range(3, 11))},
        cagr={n: sd.cell(6, c).value for n, c in zip(names, range(3, 11))},
        corr=[[sd.cell(r, c).value for c in range(3, 11)] for r in range(10, 18)],
        cov=[[sd.cell(r, c).value for c in range(3, 11)] for r in range(21, 29)])
    ra = openpyxl.load_workbook(Path(macro_path).with_name(
        [p.name for p in Path(macro_path).parent.glob("*Portfolio_Presentation*")][0]), data_only=True)["Risk Adjusted Portfolio Perform"]
    ref["performance"] = dict(sharpe=ra["C6"].value, beta=ra["C14"].value, treynor=ra["C15"].value,
                              alpha=ra["C24"].value, rf=ra["C4"].value, rm=ra["C21"].value)

    # ---------------------------------------------------------------- valuation inputs
    val, ref["valuation"] = {}, {}
    for nm in STOCK_SHEETS:
        w, v, f = wf[nm], wv[nm], wf[nm]
        peers = {}
        # beta window: find the 'Nifty' header row and 'Beta' row
        hdr = next(r for r in range(36, 50) if v.cell(r, 2).value == "Nifty")
        beta_row = next(r for r in range(280, 296) if v.cell(r, 2).value == "Beta")
        cols = [c for c in range(5, 16) if v.cell(hdr, c).value not in (None, "")]
        recs = []
        for r in range(hdr + 1, beta_row):
            d, n = v.cell(r, 2).value, v.cell(r, 3).value
            if d is None or n is None:
                continue
            recs.append([d.date().isoformat(), n] + [v.cell(r, c).value for c in cols])
        pcols = ["date", "Nifty"] + [str(v.cell(hdr, c).value).strip() for c in cols]
        pd.DataFrame(recs, columns=pcols).to_csv(DATA / "beta_peers" / f"{nm.replace(' ', '_')}.csv", index=False)

        if nm == "Axis Bank":
            val[nm] = dict(
                method="RI", as_of="01/11/2026", price=v["C21"].value, shares=v["C18"].value,
                opening_bv=v["C3"].value, pat0=v["C4"].value,
                pat_growth=r10(v["D4"].value / v["C4"].value - 1),
                payout=v["C5"].value, terminal_growth=v["C14"].value, years=[v.cell(2, c).value for c in range(3, 8)],
                wacc=dict(rf=v["D34"].value, rm=v["D35"].value, beta_mode="peers", beta_fixed=None))
            ref["valuation"][nm] = dict(value=v["C19"].value, ke=v["D37"].value, beta=v["D36"].value)
            continue

        last = max(c for c in range(3, 12) if isinstance(v.cell(1, c).value, (int, float)) or c == 3)
        ncol = max(c for c in range(4, 12) if v.cell(1, c).value is not None)   # last forecast col
        cc = list(range(3, ncol + 1))                                           # C..last
        rev = [v.cell(3, c).value for c in cc]; cfo = [v.cell(4, c).value for c in cc]
        cap = [v.cell(5, c).value for c in cc]; itr = [v.cell(6, c).value for c in cc]
        tax = [v.cell(7, c).value for c in cc]
        label20 = v["B20"].value
        asof = re.search(r"(\d\d/\d\d/\d{4})", label20)
        # which EV-bridge sign did the workbook use?  (C16 formula text)
        c16 = f["C16"].value
        sign = 1 if re.search(r"\+C15-C14", c16.replace(" ", "")) else -1
        # terminal value formula and final-year PV formula (quirk detection)
        tv_cell = next(f.cell(9, c) for c in cc if f.cell(9, c).value)
        tv_uses_g = "(1+" in str(tv_cell.value)
        last_pv = str(f.cell(10, ncol).value)
        final_has_fcff = "SUM(" in last_pv
        debt33, kd_cell = v["C33"].value, v["C36"].value
        val[nm] = dict(
            method="DCF", as_of=asof.group(1) if asof else None, price=v["C20"].value,
            shares=v["C17"].value, debt=v["C14"].value, cash=v["C15"].value,
            years=[v.cell(2, c).value for c in cc],
            revenue0=rev[0], growth=[r10(rev[i] / rev[i - 1] - 1) for i in range(1, len(rev))],
            cfo_margin=r10(cfo[0] / rev[0]), capex0=cap[0],
            capex_pct=[r10(cap[i] / rev[i]) for i in range(1, len(rev))],
            interest_ratio=r10(itr[0] / rev[0]), tax=tax, terminal_growth=v["C11"].value,
            wacc=dict(debt=debt33, equity_mv=v["G33"].value, rf=v["F36"].value, rm=v["F37"].value,
                      kd_pretax=kd_cell, interest0=itr[0], tax=v["C37"].value,
                      beta_mode="fixed" if not isinstance(f["F38"].value, str) else "peers",
                      beta_fixed=v["F38"].value if not isinstance(f["F38"].value, str) else None),
            workbook=dict(net_debt_sign=sign, tv_uses_growth=tv_uses_g, final_fcff_in_pv=final_has_fcff))
        ref["valuation"][nm] = dict(value=v["C18"].value, wacc=v["C12"].value, firm=v["C13"].value,
                                    ev=v["C16"].value, ke=v["F39"].value, beta=v["F38"].value,
                                    fcff=[v.cell(8, c).value for c in cc])
    (DATA / "valuation_inputs.json").write_text(json.dumps(val, indent=2, default=str))

    # market-level inputs
    market = dict(universe=names, cagr=cagr, classification=cls,
                  rf=wv["ITC"]["F36"].value, rm_jensen=wv["ONGC"]["F37"].value, trading_days=252)
    (DATA / "market_inputs.json").write_text(json.dumps(market, indent=2))

    # ---------------------------------------------------------------- questionnaire
    q = openpyxl.load_workbook(quest_path, data_only=True)
    key = pd.DataFrame([[c.value for c in row] for row in q["Scoring Key"].iter_rows(min_row=2, max_col=5)],
                       columns=["q", "letter", "answer", "score", "section"]).dropna(subset=["q"])
    key["q"] = key["q"].astype(int)
    key.to_csv(DATA / "scoring_key.csv", index=False)
    qi = q["Questionnaire Input"]
    qs = pd.DataFrame([[qi.cell(r, c).value for c in (1, 2, 3)] for r in range(5, 17)], columns=["q", "section", "text"])
    qs.to_csv(DATA / "questions.csv", index=False)
    ref["questionnaire"] = dict(answers=[qi.cell(r, 4).value for r in range(5, 17)], rc=qi["H2"].value, rt=qi["H3"].value,
                                total=qi["H4"].value, profile=qi["H5"].value, rpi=qi["H17"].value, A=qi["H21"].value,
                                cap_band=qi["H6"].value, tol_band=qi["H7"].value)
    (ROOT / "tests" / "excel_reference.json").write_text(json.dumps(ref, indent=1, default=str))
    print("done:", sorted(p.name for p in DATA.iterdir()))


if __name__ == "__main__":
    main(*sys.argv[1:3])
