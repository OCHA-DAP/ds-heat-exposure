"""Exposure tables from per-cell metrics and population vectors.

    uv run python scripts/build_tables.py

Inputs: data/metrics/obs/obs_{YEAR}.nc, data/metrics/proj/{ref,gwl_*}.nc, data/pop/*
Outputs (data/tables/):
  exposure.parquet   scenario, period, group, iso3, age, metric, people, person_days, mean_days,
                     people_ge1/10/30 (day metrics) or people_mat29 (mat)
  units.parquet      per PiN unit: population-weighted mean of each metric, per scenario/period
  meta.json          as-of dates, warming level, IPCC multipliers, plan summary
"""

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from heat import era5, exposure, projections

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("build_tables")

ROOT = Path(__file__).resolve().parent.parent
import os

MET = Path(os.environ.get("HEAT_METRICS", ROOT / "data" / "metrics"))
OUT = Path(os.environ.get("HEAT_TABLES", ROOT / "data" / "tables"))
ATLAS = ROOT / "data" / "raw" / "atlas"
STORE = ROOT / "data" / "era5c"
RECENT = 10  # years in the "recent average" map period


def obs_years():
    return sorted(int(p.stem.split("_")[1]) for p in (MET / "obs").glob("obs_*.nc"))


def atlas_mat_by_year(c):
    path = ATLAS / "era5_monthly_temperature.zip"
    if not path.exists():
        return {}
    da = projections.open_atlas(path)
    if float(da.max()) > 200:
        da = da - 273.15
    ann = da.groupby("time.year").mean("time")
    pts = ann.sel(
        lat=xr.DataArray(c.lat.values, dims="cell"),
        lon=xr.DataArray(c.lon.values, dims="cell"),
        method="nearest",
    )
    out = {}
    for y in pts.year.values:
        n = int(da.sel(time=str(int(y))).sizes["time"])
        if n == 12:
            out[int(y)] = pts.sel(year=y).values.astype(np.float32)
    return out


def daily_mat(year):
    path = STORE / "tmean" / f"tmean_{year}.nc"
    if not path.exists():
        return None
    da = era5.load_compact(STORE, "tmean", year)
    if not str(da.time.values[-1])[:10].endswith("12-31"):
        return None
    return np.nanmean(da.values, axis=0)


def main():
    c = xr.open_dataset(STORE / "cells.nc").load()
    pv = exposure.load(ROOT / "data" / "pop", c)
    OUT.mkdir(parents=True, exist_ok=True)
    rows, unit_rows = [], []
    mats = atlas_mat_by_year(c)
    years = obs_years()
    obs_fields = {}
    meta_years = {}
    for y in years:
        ds = xr.open_dataset(MET / "obs" / f"obs_{y}.nc")
        f = {m: ds[m].values for m in ds.data_vars}
        mat = mats.get(y)
        if mat is None:
            mat = daily_mat(y)
        if mat is not None:
            f["mat"] = mat
        obs_fields[y] = f
        meta_years[y] = {
            "n_days": int(ds.attrs["n_days"]),
            "last_date": ds.attrs["last_date"],
            "complete": bool(ds.attrs["complete"]),
        }
        rows += exposure.all_measures(f, pv, "observed", str(y))
        logger.info("observed %d", y)
    complete = [y for y in years if meta_years[y]["complete"]]
    latest = complete[-1]
    unit_rows += exposure.unit_means(obs_fields[latest], pv, "observed", str(latest))
    recent = complete[-RECENT:]
    avg = {
        m: np.mean([obs_fields[y][m] for y in recent if m in obs_fields[y]], axis=0)
        for m in obs_fields[latest]
    }
    period = f"{recent[0]}-{recent[-1]}"
    rows += exposure.all_measures(avg, pv, "observed_mean", period)
    unit_rows += exposure.unit_means(avg, pv, "observed_mean", period)
    for p in sorted((MET / "proj").glob("*.nc")):
        ds = xr.open_dataset(p)
        f = {m: ds[m].values for m in ds.data_vars}
        rows += exposure.all_measures(f, pv, p.stem, ds.attrs.get("ref_years", ""))
        unit_rows += exposure.unit_means(f, pv, p.stem, ds.attrs.get("ref_years", ""))
        logger.info("projection %s", p.stem)
    pd.DataFrame(rows).to_parquet(OUT / "exposure.parquet")
    pd.concat(unit_rows, ignore_index=True).to_parquet(OUT / "units.parquet")

    warming = projections.current_warming()
    meta = {
        "years": meta_years,
        "latest_complete_year": latest,
        "recent_period": period,
        "warming": warming,
        "ipcc_50yr_now": projections.ipcc_at(warming["p50"], "50yr"),
        "ipcc_10yr_now": projections.ipcc_at(warming["p50"], "10yr"),
        "ipcc_table": projections.IPCC_SPM6,
        "plans": pv.plans.drop(columns=[c for c in ("geometry",) if c in pv.plans]).to_dict(
            "records"
        ),
    }
    (OUT / "meta.json").write_text(json.dumps(meta, indent=1, default=str))
    logger.info("tables written: %d exposure rows", len(rows))


if __name__ == "__main__":
    main()
