"""ERA5 daily statistics: request specs, download, and compaction to land cells.

Compact store (data/era5c/): one NetCDF per variable-year with dims (time, cell), int16 hundredths of
a degree Celsius, only the land cells of the grid (land-sea mask >= LSM_MIN). `cells.nc` holds the
lat/lon of each cell. This is ~180 MB per variable-year instead of ~1.1 GB, so the whole
1986-present archive fits on a laptop and on blob.
"""

from __future__ import annotations

import calendar
import datetime as dt
import logging
from pathlib import Path

import numpy as np
import xarray as xr

logger = logging.getLogger(__name__)

AREA = [75, -180, -60, 180]  # N, W, S, E
LSM_MIN = 0.1
DAILY_DATASET = "derived-era5-single-levels-daily-statistics"

# short name -> (CDS variable, daily statistic)
VARS = {
    "tmax": ("2m_temperature", "daily_maximum"),
    "tmin": ("2m_temperature", "daily_minimum"),
    "tmean": ("2m_temperature", "daily_mean"),
    "tdew": ("2m_dewpoint_temperature", "daily_mean"),
}
SCALE = 100.0  # int16 = round((K - 273.15) * SCALE)
FILL = np.int16(-32768)


def daily_request(var: str, year: int, months: list[int] | None = None) -> dict:
    cds_var, stat = VARS[var]
    months = months or list(range(1, 13))
    return {
        "product_type": "reanalysis",
        "variable": [cds_var],
        "year": str(year),
        "month": [f"{m:02d}" for m in months],
        "day": [f"{d:02d}" for d in range(1, 32)],
        "daily_statistic": stat,
        "time_zone": "utc+00:00",
        "frequency": "1_hourly",
        "area": AREA,
    }


def lsm_request() -> dict:
    return {
        "product_type": ["reanalysis"],
        "variable": ["land_sea_mask"],
        "year": ["2020"],
        "month": ["01"],
        "day": ["01"],
        "time": ["00:00"],
        "data_format": "netcdf",
        "area": AREA,
    }


def ps_clim_request() -> dict:
    """Monthly mean surface pressure 2015-2024, for a per-calendar-month climatology."""
    return {
        "product_type": ["monthly_averaged_reanalysis"],
        "variable": ["surface_pressure"],
        "year": [str(y) for y in range(2015, 2025)],
        "month": [f"{m:02d}" for m in range(1, 13)],
        "time": ["00:00"],
        "data_format": "netcdf",
        "area": AREA,
    }


def complete_months(year: int, today: dt.date | None = None, lag_days: int = 7) -> list[int]:
    """Months of `year` whose last day is at least `lag_days` before today (ERA5 latency)."""
    today = today or dt.date.today()
    out = []
    for m in range(1, 13):
        last = dt.date(year, m, calendar.monthrange(year, m)[1])
        if (today - last).days >= lag_days:
            out.append(m)
    return out


def _main_var(ds: xr.Dataset) -> xr.DataArray:
    names = [v for v in ds.data_vars if ds[v].ndim >= 2]
    return ds[names[0]]


def _std_coords(da: xr.DataArray) -> xr.DataArray:
    ren = {}
    for a, b in (("valid_time", "time"), ("latitude", "lat"), ("longitude", "lon")):
        if a in da.dims or a in da.coords:
            ren[a] = b
    da = da.rename(ren)
    drop = [c for c in da.coords if c not in ("time", "lat", "lon")]
    return da.drop_vars(drop)


def build_cells(lsm_path: Path, out_path: Path, pop_grid_path: Path) -> xr.Dataset:
    """Cells kept = land (land-sea mask >= LSM_MIN) OR any WorldPop population in the 0.25° cell,
    so islands and coastal strips that ERA5 counts as sea are not dropped."""
    ds = xr.open_dataset(lsm_path)
    lsm = _std_coords(_main_var(ds)).squeeze(drop=True)
    lsm = lsm.sortby("lat", ascending=False)
    pop = xr.open_dataarray(pop_grid_path)
    assert pop.shape == lsm.shape, (pop.shape, lsm.shape)
    assert abs(float(pop.lat[0]) - float(lsm.lat[0])) < 1e-6
    assert abs(float(pop.lon[0]) - float(lsm.lon[0])) < 1e-6
    mask = (lsm >= LSM_MIN).values | (pop.values > 0)
    iy, ix = np.nonzero(mask)
    cells = xr.Dataset(
        {
            "lat": ("cell", lsm.lat.values[iy].astype("float32")),
            "lon": ("cell", lsm.lon.values[ix].astype("float32")),
            "iy": ("cell", iy.astype("int32")),
            "ix": ("cell", ix.astype("int32")),
            "lsm": ("cell", lsm.values[iy, ix].astype("float32")),
        },
        attrs={
            "nlat": lsm.sizes["lat"],
            "nlon": lsm.sizes["lon"],
            "lat0": float(lsm.lat[0]),
            "lon0": float(lsm.lon[0]),
            "res": 0.25,
        },
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cells.to_netcdf(out_path)
    logger.info("cells: %d land cells of %d", cells.sizes["cell"], mask.size)
    return cells


def compact(raw_path: Path, cells: xr.Dataset, out_path: Path, var: str, year: int):
    """Raw CDS NetCDF (time, lat, lon) in kelvin -> int16 (time, cell) hundredths of °C."""
    ds = xr.open_dataset(raw_path)
    da = _std_coords(_main_var(ds)).sortby("lat", ascending=False)
    assert da.sizes["lat"] == cells.attrs["nlat"] and da.sizes["lon"] == cells.attrs["nlon"], (
        da.sizes,
        cells.attrs,
    )
    iy = cells.iy.values
    ix = cells.ix.values
    n_t = da.sizes["time"]
    out = np.empty((n_t, iy.size), dtype=np.int16)
    for t0 in range(0, n_t, 31):  # month-sized slabs keep memory small
        block = da.isel(time=slice(t0, t0 + 31)).values  # (t, lat, lon) float32 K
        vals = (block[:, iy, ix] - 273.15) * SCALE
        bad = ~np.isfinite(vals)
        vals = np.clip(np.round(np.nan_to_num(vals, nan=0.0)), -32767, 32767).astype(np.int16)
        vals[bad] = FILL
        out[t0 : t0 + block.shape[0]] = vals
    times = da.time.values
    ds.close()
    res = xr.Dataset(
        {
            var: (
                ("time", "cell"),
                out,
                {"scale": SCALE, "offset_c": 0.0, "units": "0.01 degC", "_FillValue": FILL},
            )
        },
        coords={"time": times},
        attrs={"source": f"ERA5 {DAILY_DATASET} {VARS[var]}", "year": year},
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".tmp.nc")
    res.to_netcdf(tmp, encoding={var: {"zlib": True, "complevel": 1, "chunksizes": (31, iy.size)}})
    tmp.replace(out_path)


def load_compact(store: Path, var: str, year: int, cells: slice | None = None) -> xr.DataArray:
    """Daily values in °C as float32 (time, cell), optionally for a slice of cells only."""
    ds = xr.open_dataset(store / var / f"{var}_{year}.nc", mask_and_scale=False)
    raw = ds[var].values if cells is None else ds[var].values[:, cells]
    vals = raw.astype(np.float32) / SCALE
    vals[raw == FILL] = np.nan
    return xr.DataArray(vals, dims=("time", "cell"), coords={"time": ds.time.values}, name=var)
