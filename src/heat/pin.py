"""People in need from the HNRP mirror's public export (ocha-dap.github.io/ds-hnrp-mirror/data/).

Rules (docs/DESIGN.md):
- Current plan year = the latest year with at least MIN_HNRPS released HNRPs that carry a PiN.
- Country plans = HNRPs, flash appeals and single-country "Other" plans flagged GHO. Regional
  response plans are excluded (multi-country, no consistent admin split).
- The national PiN of each country plan is the official figure (plans.json `in_need`).
- Its admin split comes from the best available source, in order:
    1. JIAF admin PiN for the plan year (pin/{ISO3}_{YEAR}.json, final_pin else preliminary_pin),
    2. HAPI intersectoral admin PiN for the plan year (needs/{ISO3}_{YEAR}.json),
    3. the same two sources for the previous year (shares only),
    4. none: the PiN is spread like the population over the whole country.
  Admin shares are rescaled so they sum to the official national PiN.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from dataclasses import dataclass
from functools import cache

import pandas as pd

logger = logging.getLogger(__name__)

BASE_URL = "https://ocha-dap.github.io/ds-hnrp-mirror/data"
HNRP = "Humanitarian needs and response plan"
COUNTRY_PLAN_TYPES = {HNRP, "Humanitarian response plan", "Flash appeal", "Other"}
MIN_HNRPS = 5


@cache
def _get(path: str):
    with urllib.request.urlopen(f"{BASE_URL}/{path}", timeout=120) as r:
        return json.load(r)


def _rows(payload) -> pd.DataFrame:
    return pd.DataFrame(payload["rows"], columns=payload["columns"])


def plans() -> pd.DataFrame:
    return pd.DataFrame(_get("plans.json")["plans"])


def current_plan_year(p: pd.DataFrame | None = None) -> int:
    p = plans() if p is None else p
    hnrps = p[(p.plan_type == HNRP) & (p.in_need.fillna(0) > 0)]
    counts = hnrps.groupby("year").size()
    return int(counts[counts >= MIN_HNRPS].index.max())


def country_plans(year: int | None = None) -> pd.DataFrame:
    """One row per country with a GHO country plan in `year` (largest PiN plan if several)."""
    p = plans()
    year = current_plan_year(p) if year is None else year
    sel = p[
        (p.year == year)
        & p.is_gho.fillna(False)
        & p.plan_type.isin(COUNTRY_PLAN_TYPES)
        & p.iso3.notna()
        & ~p.iso3.fillna("").str.contains(";")
        & (p.in_need.fillna(0) > 0)
    ].copy()
    sel["is_hnrp"] = sel.plan_type.isin({HNRP, "Humanitarian response plan"})
    sel = sel.sort_values(["iso3", "is_hnrp", "in_need"], ascending=[True, False, False])
    sel = sel.drop_duplicates("iso3")
    return sel[
        ["iso3", "plan_id", "code", "name", "short_name", "plan_type", "is_hnrp", "year", "in_need"]
    ].reset_index(drop=True)


@dataclass
class AdminPin:
    iso3: str
    plan_year: int
    source: str  # "jiaf", "hapi", "jiaf (prev year shares)", "hapi (prev year shares)", "national"
    source_year: int | None
    admin_level: int | None
    table: pd.DataFrame  # columns: pcode, name, admin_level, parent_pcode, pin (scaled)
    national_pin: float


def _index_years(index_name: str) -> dict[str, list[int]]:
    idx = _get(index_name)
    return {c["iso3"]: c["years"] for c in idx["countries"]}


def _deepest(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Collapse rows to the deepest admin level present: pcode/name/parent per row."""
    for lvl in (3, 2, 1):
        code = f"admin{lvl}_code"
        if code in df and df[code].notna().any():
            sub = df[df[code].notna()].copy()
            parent = f"admin{lvl - 1}_code" if lvl > 1 else None
            out = pd.DataFrame(
                {
                    "pcode": sub[code].astype(str),
                    "name": sub[f"admin{lvl}_name"],
                    "parent_pcode": sub[parent].astype(str) if parent else None,
                    "admin1_pcode": sub["admin1_code"].astype(str),
                    "pin": sub["pin"].astype(float),
                }
            )
            return out, lvl
    return pd.DataFrame(), 0


def _jiaf(iso3: str, year: int) -> tuple[pd.DataFrame, int] | None:
    if year not in _index_years("pin_index.json").get(iso3, []):
        return None
    df = _rows(_get(f"pin/{iso3}_{year}.json"))
    df["pin"] = df["final_pin"].fillna(df["preliminary_pin"])
    df = df[df["pin"].fillna(0) > 0]
    if df.empty:
        return None
    out, lvl = _deepest(df)
    if out.empty:
        return None
    # several population groups per admin unit (residents, IDPs, returnees...) -> sum
    out = out.groupby(["pcode", "parent_pcode", "admin1_pcode"], dropna=False, as_index=False).agg(
        name=("name", "first"), pin=("pin", "sum")
    )
    return out, lvl


def _hapi(iso3: str, year: int) -> tuple[pd.DataFrame, int] | None:
    if year not in _index_years("needs_index.json").get(iso3, []):
        return None
    df = _rows(_get(f"needs/{iso3}_{year}.json"))
    df = df[
        (df.sector_code == "Intersectoral")
        & (df.population_status == "INN")
        & df.category.fillna("").isin(["", "total"])
        & (df.admin_level > 0)
    ].rename(columns={"population": "pin"})
    if df.empty:
        return None
    lvl_max = int(df.admin_level.max())
    df = df[df.admin_level == lvl_max]
    out, lvl = _deepest(df)
    if out.empty:
        return None
    out = out.groupby(["pcode", "parent_pcode", "admin1_pcode"], dropna=False, as_index=False).agg(
        name=("name", "first"), pin=("pin", "sum")
    )
    return out, lvl


def admin_pin(iso3: str, plan_year: int, national_pin: float) -> AdminPin:
    attempts = [
        ("jiaf", plan_year, _jiaf),
        ("hapi", plan_year, _hapi),
        ("jiaf (prev year shares)", plan_year - 1, _jiaf),
        ("hapi (prev year shares)", plan_year - 1, _hapi),
    ]
    for label, yr, fn in attempts:
        got = fn(iso3, yr)
        if got is None:
            continue
        table, lvl = got
        total = table.pin.sum()
        if total <= 0:
            continue
        table = table.assign(admin_level=lvl, pin=table.pin / total * national_pin)
        return AdminPin(iso3, plan_year, label, yr, lvl, table, national_pin)
    return AdminPin(iso3, plan_year, "national", None, None, pd.DataFrame(), national_pin)
