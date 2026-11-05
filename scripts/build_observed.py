"""Observed per-cell heat metrics from the compact ERA5 store.

    uv run python scripts/build_observed.py p95            # 1986-2005 95th percentiles of Tmax/Tmin
    uv run python scripts/build_observed.py years [YEAR..] # per-year counts (default: every year available)

Outputs (data/metrics/):
  p95.nc                 p95max, p95min (cell) °C
  ps_clim.nc             surface pressure monthly climatology (12, cell) Pa
  obs/obs_{YEAR}.nc      counts per metric (cell), plus n_days and last_day / first_day heat flags
"""

import logging
import sys
from pathlib import Path

import numpy as np
import xarray as xr

from heat import era5, metrics, projections

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("build_observed")

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "data" / "era5c"
OUT = ROOT / "data" / "metrics"
BASE_YEARS = range(1986, 2006)


def cells():
    return xr.open_dataset(STORE / "cells.nc").load()


def ps_clim(c):
    path = OUT / "ps_clim.nc"
    if path.exists():
        return xr.open_dataarray(path).values
    ds = xr.open_dataset(ROOT / "data" / "raw" / "era5" / "ps_clim.nc")
    da = era5._std_coords(era5._main_var(ds)).sortby("lat", ascending=False)
    clim = da.groupby("time.month").mean("time").values  # (12, lat, lon)
    arr = clim[:, c.iy.values, c.ix.values].astype(np.float32)
    OUT.mkdir(parents=True, exist_ok=True)
    xr.DataArray(arr, dims=("month", "cell"), name="ps").to_netcdf(path)
    return arr


def available(var):
    return sorted(int(p.stem.split("_")[1]) for p in (STORE / var).glob(f"{var}_*.nc"))


def build_p95():
    out = {}
    for var in ("tmax", "tmin"):
        missing = [y for y in BASE_YEARS if y not in available(var)]
        if missing:
            raise SystemExit(f"{var}: baseline years missing {missing}")
        n_cell = cells().sizes["cell"]
        res = np.empty(n_cell, dtype=np.float32)
        step = 20000
        for c0 in range(0, n_cell, step):
            sl = slice(c0, min(c0 + step, n_cell))
            stack = np.concatenate(
                [era5.load_compact(STORE, var, y, sl).values for y in BASE_YEARS]
            )
            res[sl] = np.nanpercentile(stack, 95, axis=0)
            logger.info("%s p95 cells %d-%d", var, sl.start, sl.stop)
        out[f"p95{var[1:]}"] = ("cell", res)
    OUT.mkdir(parents=True, exist_ok=True)  # netCDF reports a missing folder as "Permission denied"
    xr.Dataset(out).to_netcdf(OUT / "p95.nc")


_ATLAS_MAT = {}


def atlas_mat(c, year):
    """Annual mean temperature from the C3S Atlas ERA5 monthly series (complete years only)."""
    path = ROOT / "data" / "raw" / "atlas" / "era5_monthly_temperature.zip"
    if not path.exists():
        return None
    if "da" not in _ATLAS_MAT:
        da = projections.open_atlas(path)
        _ATLAS_MAT["da"] = da
        _ATLAS_MAT["iy"] = xr.DataArray(c.lat.values, dims="cell")
        _ATLAS_MAT["ix"] = xr.DataArray(c.lon.values, dims="cell")
    da = _ATLAS_MAT["da"].sel(time=str(year))
    if da.sizes.get("time", 0) != 12:
        return None
    ann = da.mean("time")
    vals = ann.sel(lat=_ATLAS_MAT["iy"], lon=_ATLAS_MAT["ix"], method="nearest").values
    if np.nanmax(vals) > 200:  # kelvin
        vals = vals - 273.15
    return vals.astype(np.float32)


def daily_mat(year):
    if year not in available("tmean"):
        return None
    da = era5.load_compact(STORE, "tmean", year)
    if not str(da.time.values[-1])[:10].endswith("12-31"):
        return None
    return np.nanmean(da.values, axis=0).astype(np.float32)


def build_year(year, c, ps, p95):
    have = {v: year in available(v) for v in ("tmax", "tmin", "tdew")}
    if not all(have.values()):
        logger.info("%d: missing %s", year, [v for v, ok in have.items() if not ok])
        return
    tmax = era5.load_compact(STORE, "tmax", year)
    tmin = era5.load_compact(STORE, "tmin", year).values
    tdew = era5.load_compact(STORE, "tdew", year).values
    times = tmax.time.values
    f = metrics.daily_fields(tmax.values, tdew, ps, times)
    counts = metrics.count_days(f)
    hot = metrics.heatwave_flags(tmax.values, tmin, p95["p95max"], p95["p95min"])
    prev_last = None
    if (year - 1) in available("tmax") and (year - 1) in available("tmin"):
        pmx = era5.load_compact(STORE, "tmax", year - 1).values[-1]
        pmn = era5.load_compact(STORE, "tmin", year - 1).values[-1]
        prev_last = (pmx > p95["p95max"]) & (pmn > p95["p95min"])
    next_first = None
    if (year + 1) in available("tmax") and (year + 1) in available("tmin"):
        nmx = era5.load_compact(STORE, "tmax", year + 1).values[0]
        nmn = era5.load_compact(STORE, "tmin", year + 1).values[0]
        next_first = (nmx > p95["p95max"]) & (nmn > p95["p95min"])
    counts[metrics.HEATWAVE] = metrics.heatwave_days(hot, prev_last, next_first)
    mat = daily_mat(year)
    if mat is None:
        mat = atlas_mat(c, year)
    prev_file = OUT / "obs" / f"obs_{year}.nc"
    if mat is None and prev_file.exists():
        # keep the value from an earlier build (e.g. from the Atlas, which CI does not download)
        with xr.open_dataset(prev_file) as old:
            if "mat" in old:
                mat = old["mat"].values.copy()
    if mat is not None:
        counts["mat"] = mat
    last_date = str(np.datetime_as_string(times[-1], unit="D"))
    ds = xr.Dataset(
        {k: ("cell", v) for k, v in counts.items()},
        attrs={
            "year": year,
            "n_days": len(times),
            "last_date": last_date,
            "complete": int(last_date.endswith("12-31")),
        },
    )
    (OUT / "obs").mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(OUT / "obs" / f"obs_{year}.nc")
    logger.info("%d done (%d days to %s)", year, len(times), last_date)


def main(argv):
    cmd = argv[0] if argv else "years"
    if cmd == "p95":
        build_p95()
        return
    c = cells()
    ps = ps_clim(c)
    p95 = xr.open_dataset(OUT / "p95.nc").load()
    p95 = {k: p95[k].values for k in p95.data_vars}
    years = [int(a) for a in argv[1:]] or available("tmax")
    for y in years:
        build_year(y, c, ps, p95)


if __name__ == "__main__":
    main(sys.argv[1:])
