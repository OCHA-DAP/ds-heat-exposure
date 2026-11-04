"""Population vectors over ERA5 cells, and exposure measures.

A population vector is a (cell,) array of people. Groups:
  world          WorldPop 2026, everyone
  gho_countries  everyone living in a country with a current GHO country plan
  gho_pin        people in need in those plans (HNRPs at admin level, other plans spread nationally)
  hnrp_pin       people in need in the HNRPs only
plus per-country population and PiN vectors. Each comes in three ages: total, age65, under1.
PiN by age = PiN of the unit x the WorldPop age share of the unit.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import xarray as xr

logger = logging.getLogger(__name__)

AGES = ("total", "age65", "under1")
DAY_THRESHOLDS = (1, 10, 20, 30)  # 20: Mora et al. 2017 "deadly heat on >= 20 days a year"
MAT_THRESHOLD = 29.0


@dataclass
class PopVectors:
    n_cell: int
    groups: dict = field(default_factory=dict)  # (group, iso3 or "", age) -> (cell,) float64
    unit_weights: dict = field(
        default_factory=dict
    )  # iso3 -> DataFrame unit_id, cell, w (PiN per cell)
    units: dict = field(default_factory=dict)  # iso3 -> GeoDataFrame
    plans: pd.DataFrame | None = None


def _vec(n, cells, values):
    v = np.zeros(n, dtype=np.float64)
    np.add.at(v, cells, values)
    return v


def load(pop_dir: Path, cells: xr.Dataset) -> PopVectors:
    n = cells.sizes["cell"]
    pv = PopVectors(n)
    grid = xr.open_dataset(pop_dir / "pop_grid025.nc")
    iy, ix = cells.iy.values, cells.ix.values
    for age in AGES:
        pv.groups[("world", "", age)] = grid[age].values[iy, ix].astype(np.float64)
    plans = pd.read_csv(pop_dir / "plans.csv")
    pv.plans = plans
    for age in AGES:
        pv.groups[("gho_countries", "", age)] = np.zeros(n)
        pv.groups[("gho_pin", "", age)] = np.zeros(n)
        pv.groups[("hnrp_pin", "", age)] = np.zeros(n)
    for _, p in plans.iterrows():
        iso3 = p.iso3
        w0 = pd.read_parquet(pop_dir / "weights" / f"{iso3}_adm0.parquet")
        wp = pd.read_parquet(pop_dir / "weights" / f"{iso3}_pin.parquet")
        units = gpd.read_parquet(pop_dir / "units" / f"{iso3}.parquet")
        pv.units[iso3] = units
        unit_pop = wp.groupby("unit_id").total.sum()
        pin_u = units.set_index("unit_id").pin
        # PiN of units with no WorldPop population inside goes to the whole country
        orphan = pin_u[~pin_u.index.isin(unit_pop[unit_pop > 0].index)].sum()
        if orphan > 0:
            logger.info(
                "%s: %.0f PiN in units without population -> spread nationally", iso3, orphan
            )
        share = wp.unit_id.map(pin_u) / wp.unit_id.map(unit_pop)
        pv.unit_weights[iso3] = wp.assign(pin_per_person=share)
        c0_tot = w0.total.sum()
        for age in AGES:
            popv = _vec(n, w0.cell.values, w0[age].values)
            pinv = _vec(n, wp.cell.values, (wp[age] * share).fillna(0).values)
            if orphan > 0:
                pinv += popv * orphan / c0_tot
            pv.groups[("country_pop", iso3, age)] = popv
            pv.groups[("country_pin", iso3, age)] = pinv
            pv.groups[("gho_countries", "", age)] += popv
            pv.groups[("gho_pin", "", age)] += pinv
            if bool(p.is_hnrp):
                pv.groups[("hnrp_pin", "", age)] += pinv
    return pv


def day_measures(days: np.ndarray, people: np.ndarray) -> dict:
    d = np.nan_to_num(days.astype(np.float64))
    pop = people.sum()
    pdays = float((d * people).sum())
    out = {"people": pop, "person_days": pdays, "mean_days": pdays / pop if pop else np.nan}
    for k in DAY_THRESHOLDS:
        out[f"people_ge{k}"] = float(people[d >= k].sum())
    return out


def mat_measures(mat: np.ndarray, people: np.ndarray) -> dict:
    pop = people.sum()
    return {
        "people": pop,
        "people_mat29": float(people[np.nan_to_num(mat, nan=-99) >= MAT_THRESHOLD].sum()),
    }


def all_measures(fields: dict, pv: PopVectors, scenario: str, period: str) -> list[dict]:
    """fields: metric -> (cell,) values (counts, or 'mat' in °C)."""
    rows = []
    for (group, iso3, age), people in pv.groups.items():
        if people.sum() <= 0:
            continue
        for metric, vals in fields.items():
            m = mat_measures(vals, people) if metric == "mat" else day_measures(vals, people)
            rows.append(
                {
                    "scenario": scenario,
                    "period": period,
                    "group": group,
                    "iso3": iso3,
                    "age": age,
                    "metric": metric,
                    **m,
                }
            )
    return rows


def unit_means(fields: dict, pv: PopVectors, scenario: str, period: str) -> list[dict]:
    """Per PiN unit: population-weighted mean of each metric (days, or °C for mat)."""
    rows = []
    for iso3, wp in pv.unit_weights.items():
        g = wp[["unit_id", "cell", "total"]]
        tot = g.groupby("unit_id").total.sum()
        res = {"unit_id": tot.index}
        for metric, vals in fields.items():
            v = np.nan_to_num(vals[g.cell.values].astype(np.float64))
            res[metric] = (g.assign(x=v * g.total.values).groupby("unit_id").x.sum() / tot).values
        df = pd.DataFrame(res)
        df.insert(0, "iso3", iso3)
        df.insert(0, "period", period)
        df.insert(0, "scenario", scenario)
        rows.append(df)
    return rows
