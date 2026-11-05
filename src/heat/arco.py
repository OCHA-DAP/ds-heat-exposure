"""ERA5 daily statistics from ARCO-ERA5 hourly data.

ARCO-ERA5 is Google's public analysis-ready copy of ERA5 (Google Cloud public datasets; no login,
no queue): hourly 0.25° fields from 1940, final ERA5 and then ERA5T up to about a week ago. We read
2 m temperature and 2 m dewpoint and reduce each UTC day's 24 hours to max/min/mean, which is what
the CDS `derived-era5-single-levels-daily-statistics` dataset computes (frequency 1_hourly,
utc+00:00). Checked against our CDS download of 1986 daily maxima: identical to < 0.01 °C on every
cell (1986-01-15 and 1986-07-15). We left the CDS route in November 2026 because its queue held
single requests for 8-20 hours.

Per year this reads ~33 GB of compressed hourly chunks (~2 MB each; ~1.4 TB for 1986-2026), so the
backfill runs on Databricks; the monthly refresh rebuilds only the current year. Days are fetched
in parallel threads; zarr fetches each day's 24 hourly chunks concurrently as well.
"""

from __future__ import annotations

import calendar
import datetime as dt
import logging
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import netCDF4
import numpy as np
import xarray as xr

from heat import era5

logger = logging.getLogger(__name__)

URL = (
    "https://storage.googleapis.com/gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3"
)
SOURCE = "ERA5 hourly (ARCO-ERA5, gcp-public-data-arco-era5) -> UTC daily statistics"
T2M, D2M = "2m_temperature", "2m_dewpoint_temperature"
SHORT = {T2M: "t2m", D2M: "d2m"}
OUT_VARS = ("tmax", "tmin", "tmean", "tdew")

# ARCO grid: latitude 90 -> -90 (721), longitude 0 -> 359.75 (1440). Our grid (era5.AREA, the same
# grid as the CDS downloads and cells.nc): latitude 75 -> -60 (541), longitude -180 -> 179.75.
ROWS = slice(60, 601)
COLS = np.r_[720:1440, 0:720]
LATS = np.linspace(75, -60, 541)
LONS = np.arange(-180, 180, 0.25)


def open_store() -> xr.Dataset:
    return xr.open_zarr(URL, consolidated=True, chunks=None)[[T2M, D2M]]


def last_day(ds: xr.Dataset) -> dt.date:
    """Last day with all 24 hours (ERA5T included)."""
    stop = ds.attrs.get("valid_time_stop_era5t") or ds.attrs["valid_time_stop"]
    return dt.date.fromisoformat(str(stop)[:10])


def final_through(ds: xr.Dataset) -> dt.date:
    """Last day of final ERA5; later days are ERA5T, which ECMWF replaces ~2-3 months on."""
    return dt.date.fromisoformat(str(ds.attrs["valid_time_stop"])[:10])


def complete_months(year: int, last: dt.date) -> list[int]:
    return [m for m in range(1, 13) if dt.date(year, m, calendar.monthrange(year, m)[1]) <= last]


def days_of(year: int, months: list[int] | None = None) -> list[dt.date]:
    months = months or list(range(1, 13))
    return [
        dt.date(year, m, d) for m in months for d in range(1, calendar.monthrange(year, m)[1] + 1)
    ]


def _hours(ds: xr.Dataset, var: str, day: dt.date) -> np.ndarray:
    """(24, 541, 1440) float32 kelvin on our grid; retries transient HTTP failures."""
    sel = ds[var].sel(time=slice(f"{day}T00:00", f"{day}T23:00"))
    for attempt in range(5):
        try:
            vals = sel.values
            break
        except Exception as e:  # network errors surface as several exception types
            if attempt == 4:
                raise
            logger.warning("%s %s: %s; retrying", var, day, e)
            time.sleep(10 * (attempt + 1))
    if vals.shape[0] != 24:
        raise ValueError(f"{var} {day}: {vals.shape[0]} hours")
    vals = vals[:, ROWS, :][:, :, COLS]
    if not np.isfinite(vals).all():
        raise ValueError(f"{var} {day}: missing values (past the end of the record?)")
    return vals


def day_stats(ds: xr.Dataset, day: dt.date) -> dict[str, np.ndarray]:
    """Daily grids (541, 1440) float32 kelvin for tmax, tmin, tmean, tdew."""
    t = _hours(ds, T2M, day)
    d = _hours(ds, D2M, day)
    return {
        "tmax": t.max(axis=0),
        "tmin": t.min(axis=0),
        "tmean": t.mean(axis=0, dtype=np.float64).astype(np.float32),
        "tdew": d.mean(axis=0, dtype=np.float64).astype(np.float32),
    }


def _open_grid_nc(path: Path, var: str, year: int, days: list[dt.date]) -> netCDF4.Dataset:
    """Full-grid daily file in the layout of the CDS daily-statistics downloads."""
    era5_var, stat = era5.VARS[var]
    short = SHORT[era5_var]
    path.parent.mkdir(parents=True, exist_ok=True)
    nc = netCDF4.Dataset(path, "w", format="NETCDF4")
    nc.createDimension("valid_time", len(days))
    nc.createDimension("latitude", LATS.size)
    nc.createDimension("longitude", LONS.size)
    t = nc.createVariable("valid_time", "i4", ("valid_time",))
    t.units = f"days since {year}-01-01"
    t.calendar = "proleptic_gregorian"
    t[:] = [(d - dt.date(year, 1, 1)).days for d in days]
    la = nc.createVariable("latitude", "f8", ("latitude",))
    la.units, la.standard_name = "degrees_north", "latitude"
    la[:] = LATS
    lo = nc.createVariable("longitude", "f8", ("longitude",))
    lo.units, lo.standard_name = "degrees_east", "longitude"
    lo[:] = LONS
    v = nc.createVariable(
        short,
        "f4",
        ("valid_time", "latitude", "longitude"),
        zlib=True,
        complevel=1,
        chunksizes=(1, LATS.size, LONS.size),
    )
    v.units = "K"
    v.long_name = f"{era5_var.replace('_', ' ')} {stat.replace('_', ' ')}"
    v.statistic = f"{stat} of the 24 hourly values, 00-23 UTC"
    nc.source = SOURCE
    nc.arco_store = URL
    nc.producer = "OCHA-DAP/ds-heat-exposure (heat.arco)"
    return nc


def build_year(
    ds: xr.Dataset,
    year: int,
    cells: xr.Dataset,
    store: Path,
    grid_dir: Path | None,
    months: list[int] | None = None,
    workers: int = 8,
) -> dict[str, Path]:
    """Compute one year (or its first `months`) of daily statistics.

    Writes the compact files store/{var}/{var}_{year}.nc and, if grid_dir is given, the full-grid
    daily files grid_dir/{var}_{year}.nc (for the team-shared container). Returns the grid files.
    """
    days = days_of(year, months)
    iy, ix = cells.iy.values, cells.ix.values
    assert cells.attrs["nlat"] == LATS.size and cells.attrs["nlon"] == LONS.size
    compact = {v: np.empty((len(days), iy.size), dtype=np.float32) for v in OUT_VARS}
    grids = {}
    if grid_dir is not None:
        grids = {v: _open_grid_nc(grid_dir / f"{v}_{year}.nc", v, year, days) for v in OUT_VARS}
    t0 = time.time()
    try:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            # Sliding window: a new day is submitted as each one is written, in day order, so
            # the pool stays busy and at most 2 x workers finished days wait in memory.
            window = 2 * workers
            pending = deque()
            nxt = 0
            for i in range(len(days)):
                while nxt < len(days) and len(pending) < window:
                    pending.append(ex.submit(day_stats, ds, days[nxt]))
                    nxt += 1
                stats = pending.popleft().result()
                for v in OUT_VARS:
                    compact[v][i] = stats[v][iy, ix]
                    if grids:
                        grids[v].variables[SHORT[era5.VARS[v][0]]][i] = stats[v]
                if (i + 1) % 30 == 0 or i + 1 == len(days):
                    rate = (i + 1) / (time.time() - t0)
                    logger.info("%d: %d/%d days (%.2f days/s)", year, i + 1, len(days), rate)
    finally:
        for nc in grids.values():
            nc.close()
    times = np.array([np.datetime64(d, "ns") for d in days])
    attrs = {"era5_final_through": final_through(ds).isoformat()}
    for v in OUT_VARS:
        era5.write_compact(store / v / f"{v}_{year}.nc", v, year, times, compact[v], SOURCE, attrs)
    logger.info("%d: %d days to %s in %.0f s", year, len(days), days[-1], time.time() - t0)
    return {v: grid_dir / f"{v}_{year}.nc" for v in OUT_VARS} if grid_dir is not None else {}
