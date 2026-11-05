"""ERA5 on the project's cells: the compact store, the cell index, and the static-field requests.

Compact store (data/era5c/): one NetCDF per variable-year with dims (time, cell), int16 hundredths
of a degree Celsius, only the land/populated cells of the 0.25° grid 75N-60S (`cells.nc` holds the
lat/lon and grid indices of each cell). ~115 MB per variable-year instead of ~1.1 GB. The daily
values come from ARCO-ERA5 hourly data (`heat.arco`); the land-sea mask and the surface-pressure
climatology are one-off CDS downloads (`scripts/fetch_era5.py`).
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import xarray as xr

logger = logging.getLogger(__name__)

AREA = [75, -180, -60, 180]  # N, W, S, E
LSM_MIN = 0.1

# short name -> (ERA5 variable, daily statistic): UTC days from the 24 hourly values
VARS = {
    "tmax": ("2m_temperature", "daily_maximum"),
    "tmin": ("2m_temperature", "daily_minimum"),
    "tmean": ("2m_temperature", "daily_mean"),
    "tdew": ("2m_dewpoint_temperature", "daily_mean"),
}
SCALE = 100.0  # int16 = round((K - 273.15) * SCALE)
FILL = np.int16(-32768)


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


def write_compact(
    out_path: Path,
    var: str,
    year: int,
    times: np.ndarray,
    kelvin: np.ndarray,
    source: str,
    attrs: dict | None = None,
):
    """Daily values (time, cell) in kelvin -> int16 hundredths of °C, the compact store format."""
    vals = (np.asarray(kelvin, dtype=np.float64) - 273.15) * SCALE
    bad = ~np.isfinite(vals)
    out = np.clip(np.round(np.nan_to_num(vals, nan=0.0)), -32767, 32767).astype(np.int16)
    out[bad] = FILL
    res = xr.Dataset(
        {
            var: (
                ("time", "cell"),
                out,
                {"scale": SCALE, "offset_c": 0.0, "units": "0.01 degC", "_FillValue": FILL},
            )
        },
        coords={"time": times},
        attrs={"source": f"{source} {VARS[var]}", "year": year, **(attrs or {})},
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_name(out_path.name + ".part")  # not *.nc, so no glob picks it up
    n_t, n_cell = out.shape
    enc = {var: {"zlib": True, "complevel": 1, "chunksizes": (min(31, n_t), n_cell)}}
    res.to_netcdf(tmp, encoding=enc, format="NETCDF4", engine="netcdf4")
    tmp.replace(out_path)


def load_compact(store: Path, var: str, year: int, cells: slice | None = None) -> xr.DataArray:
    """Daily values in °C as float32 (time, cell), optionally for a slice of cells only."""
    ds = xr.open_dataset(store / var / f"{var}_{year}.nc", mask_and_scale=False)
    raw = ds[var].values if cells is None else ds[var].values[:, cells]
    vals = raw.astype(np.float32) / SCALE
    vals[raw == FILL] = np.nan
    return xr.DataArray(vals, dims=("time", "cell"), coords={"time": ds.time.values}, name=var)
