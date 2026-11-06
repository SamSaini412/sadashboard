# Security Analysis — Streamlit dashboard

Python port of the three Excel workbooks (SA macro workbook + VBA Solver macro, Deutsche Bank risk questionnaire,
portfolio presentation).

    pip install -r requirements.txt
    streamlit run app.py
    python -m pytest -q tests        # parity tests against the Excel values

Layout: `app.py` (UI) · `sa/` (model: risk_profile, market, portfolios, optimizer, performance, valuation) ·
`data/` (inputs extracted from Excel) · `scripts/extract_from_excel.py` (refresh data) · `tests/`.

To deploy free: push this folder to GitHub and create an app on Streamlit Community Cloud pointing at `app.py`.
