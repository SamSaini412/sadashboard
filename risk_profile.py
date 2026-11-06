"""Investor risk profiling — port of the Deutsche-Bank-style questionnaire workbook.

Risk Capacity (Q1-Q6, max 24) + Risk Tolerance (Q7-Q12, max 21) -> total score (5-45) -> profile.
Risk Preference Index and the project-specific risk-aversion parameter A:
    RPI = w_c * RC/24 + w_t * RT/21
    A   = A_min + (A_max - A_min) * (1 - RPI) ** gamma
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import pandas as pd

DATA = Path(__file__).resolve().parents[1] / "data"
MAX_CAPACITY, MAX_TOLERANCE = 24, 21

PROFILE_BANDS = [(5, 11, "Very Conservative"), (12, 19, "Conservative"), (20, 28, "Moderate"),
                 (29, 36, "Aggressive"), (37, 45, "Very Aggressive")]
CAPACITY_BANDS = [(2, 9, "Low"), (10, 17, "Medium"), (18, 24, "High")]
TOLERANCE_BANDS = [(3, 7, "Conservative"), (8, 14, "Moderate"), (15, 21, "Aggressive")]


def load_questionnaire() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (questions, scoring_key)."""
    return pd.read_csv(DATA / "questions.csv"), pd.read_csv(DATA / "scoring_key.csv")


def _band(value: int, bands) -> str:
    for lo, hi, name in bands:
        if lo <= value <= hi:
            return name
    return "Outside scoring range"


@dataclass
class Calibration:
    """Illustrative calibration of A (the workbook uses A_min=1, A_max=2, gamma=1, 50:50 weights)."""
    a_min: float = 1.0
    a_max: float = 2.0
    gamma: float = 1.0
    w_capacity: float = 0.5
    w_tolerance: float = 0.5


@dataclass
class RiskResult:
    answers: dict
    item_scores: dict = field(default_factory=dict)
    capacity: int | None = None
    tolerance: int | None = None
    total: int | None = None
    profile: str | None = None
    capacity_band: str | None = None
    tolerance_band: str | None = None
    rpi: float | None = None
    risk_aversion: float | None = None
    complete: bool = False


def score_questionnaire(answers: dict[int, str | None], calibration: Calibration | None = None) -> RiskResult:
    """Score a {question_no: letter} dict. Unanswered questions -> incomplete result (no profile)."""
    cal = calibration or Calibration()
    _, key = load_questionnaire()
    lookup = {(int(r.q), r.letter): int(r.score) for r in key.itertuples()}
    res = RiskResult(answers=dict(answers))
    for q in range(1, 13):
        letter = answers.get(q)
        if letter in (None, ""):
            continue
        if (q, letter) not in lookup:
            raise ValueError(f"Q{q}: '{letter}' is not a valid answer")
        res.item_scores[q] = lookup[(q, letter)]
    res.complete = len(res.item_scores) == 12
    if all(q in res.item_scores for q in range(1, 7)):
        res.capacity = sum(res.item_scores[q] for q in range(1, 7))
        res.capacity_band = _band(res.capacity, CAPACITY_BANDS)
    if all(q in res.item_scores for q in range(7, 13)):
        res.tolerance = sum(res.item_scores[q] for q in range(7, 13))
        res.tolerance_band = _band(res.tolerance, TOLERANCE_BANDS)
    if res.complete:
        res.total = res.capacity + res.tolerance
        res.profile = _band(res.total, PROFILE_BANDS)
        res.rpi = (cal.w_capacity * res.capacity / MAX_CAPACITY + cal.w_tolerance * res.tolerance / MAX_TOLERANCE)
        res.risk_aversion = risk_aversion(res.rpi, cal)
    return res


def risk_aversion(rpi: float, cal: Calibration | None = None) -> float:
    cal = cal or Calibration()
    return cal.a_min + (cal.a_max - cal.a_min) * (1 - rpi) ** cal.gamma


def representative_A(profile: str, cal: Calibration | None = None) -> float:
    """Illustrative A for a profile band: RPI taken as the normalised band mid-point score.
    Used only for the side-by-side profile comparison; the real A comes from a client's answers."""
    cal = cal or Calibration()
    lo, hi = next((lo, hi) for lo, hi, n in PROFILE_BANDS if n == profile)
    rpi = ((lo + hi) / 2 - 5) / 40
    return risk_aversion(rpi, cal)
