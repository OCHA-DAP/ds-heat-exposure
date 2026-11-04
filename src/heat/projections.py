"""CMIP6 monthly changes at global warming levels, from the C3S Atlas, on the ERA5 cells.

For each model run: the 20-year window centred on the year it reaches the warming level (IPCC AR6
Atlas table, SSP5-8.5) minus the 1995-2014 reference window, per calendar month. Temperatures
additively, specific humidity as a ratio. Then the median across models, and bilinear
interpolation from the Atlas grid to the ERA5 cell centres.
"""

from __future__ import annotations

import io
import logging
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

logger = logging.getLogger(__name__)

GWL_TABLE_URL = (
    "https://raw.githubusercontent.com/SantanderMetGroup/ATLAS/main/warming-levels/"
    "CMIP6_Atlas_WarmingLevels.csv"
)
LEVELS = (1.5, 2.0, 3.0)
REF = (1995, 2014)
SCENARIO = "ssp5_8_5"
GWL_COL = {1.5: "1.5_ssp585", 2.0: "2_ssp585", 3.0: "3_ssp585", 4.0: "4_ssp585"}

DELTA_VARS = {
    "dtmax": "monthly_daily_maximum_temperature",
    "dtmin": "monthly_daily_minimum_temperature",
    "dtmean": "monthly_temperature",
    "qratio": "monthly_near_surface_specific_humidity",
}

# IPCC AR6 WGI SPM Figure SPM.6: frequency of hot extremes over land relative to 1850-1900
# (median, likely range) at each warming level. "Present" in the figure is labelled 1 °C.
IPCC_SPM6 = {
    "10yr": {
        "freq": {
            1.0: (2.8, 1.8, 3.2),
            1.5: (4.1, 2.8, 4.7),
            2.0: (5.6, 3.8, 6.0),
            4.0: (9.4, 8.3, 9.6),
        },
        "intensity": {1.0: 1.2, 1.5: 1.9, 2.0: 2.6, 4.0: 5.1},
    },
    "50yr": {
        "freq": {
            1.0: (4.8, 2.3, 6.4),
            1.5: (8.6, 4.3, 10.7),
            2.0: (13.9, 6.9, 16.6),
            4.0: (39.2, 27.0, 41.4),
        },
        "intensity": {1.0: 1.2, 1.5: 2.0, 2.0: 2.7, 4.0: 5.3},
    },
}
IGCC_URL = (
    "https://raw.githubusercontent.com/ClimateIndicator/data/main/data/base/anthropogenic_warming/"
    "Assessment-Extrapolation-2026_GMST_headlines.csv"
)


def ipcc_at(level: float, event: str = "50yr") -> dict:
    """Linear interpolation of SPM.6 between the published warming levels."""
    tab = IPCC_SPM6[event]
    xs = sorted(tab["freq"])
    out = {}
    for i, name in enumerate(("median", "low", "high")):
        out[name] = float(np.interp(level, xs, [tab["freq"][x][i] for x in xs]))
    out["intensity"] = float(np.interp(level, xs, [tab["intensity"][x] for x in xs]))
    return out


def current_warming(url: str = IGCC_URL) -> dict:
    """Latest single-year human-induced warming (IGCC), main definition (no notes)."""
    df = pd.read_csv(url)
    df = df[(df.timebound_upper - df.timebound_lower == 1) & df.notes.isna()]
    import datetime as dt

    this_year = dt.date.today().year
    df = df[df.timebound_lower <= this_year].sort_values("timebound_lower")
    r = df.iloc[-1]
    return {
        "year": int(r.timebound_lower),
        "p50": float(r.anthropogenic_p50),
        "p05": float(r.anthropogenic_p05),
        "p95": float(r.anthropogenic_p95),
        "source": url,
    }


def gwl_table(url: str = GWL_TABLE_URL) -> pd.DataFrame:
    return pd.read_csv(url, na_values=["NA"]).set_index("model_run")


def open_atlas(path: Path) -> xr.DataArray:
    """Open an Atlas download (zip of one NetCDF, or a NetCDF) as (member?, time, lat, lon)."""
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.endswith(".nc")]
            data = z.read(names[0])
        ds = xr.open_dataset(io.BytesIO(data))
    else:
        ds = xr.open_dataset(path)
    var = [v for v in ds.data_vars if ds[v].ndim >= 3][0]
    da = ds[var]
    ren = {}
    for a, b in (("latitude", "lat"), ("longitude", "lon"), ("valid_time", "time")):
        if a in da.dims:
            ren[a] = b
    da = da.rename(ren)
    member_dim = [d for d in da.dims if d not in ("time", "lat", "lon")]
    if member_dim:
        md = member_dim[0]
        labels = None
        for cand in ("member_id", "member", md):
            if cand in da.coords and da.coords[cand].dtype.kind in "OUS":
                labels = [str(x) for x in da.coords[cand].values]
                break
        if labels is None:
            raise ValueError(f"no member labels in {path}: {list(da.coords)}")
        da = da.assign_coords({md: labels}).rename({md: "member"})
    if float(da.lon.max()) > 180:
        da = da.assign_coords(lon=((da.lon + 180) % 360) - 180).sortby("lon")
    return da


def _member_key(label: str) -> str:
    return label.replace("/", "_").strip()


def monthly_clim(da: xr.DataArray, y0: int, y1: int) -> xr.DataArray:
    sel = da.sel(time=slice(f"{y0}-01-01", f"{y1}-12-31"))
    return sel.groupby("time.month").mean("time")


def model_deltas(
    hist: xr.DataArray, fut: xr.DataArray, table: pd.DataFrame, level: float, ratio: bool
) -> xr.DataArray:
    """(member, month, lat, lon) change for each model that reaches `level` under SSP5-8.5."""
    out = []
    members = [m for m in fut.member.values if m in set(hist.member.values)]
    for m in members:
        key = _member_key(m)
        row = table.index[table.index.str.lower() == key.lower()]
        if len(row) == 0:
            # Atlas labels can be "MODEL_rXiYpZfW" or just "MODEL"; match on the model name
            row = table.index[
                table.index.str.split("_").str[0].str.lower() == key.split("_")[0].lower()
            ]
        if len(row) == 0:
            continue
        cy = table.loc[row[0], GWL_COL[level]]
        if pd.isna(cy):
            continue
        cy = int(cy)
        series = xr.concat([hist.sel(member=m), fut.sel(member=m)], dim="time")
        ref = monthly_clim(series, *REF)
        win = monthly_clim(series, cy - 9, cy + 10)
        d = (win / ref) if ratio else (win - ref)
        out.append(d.expand_dims(member=[m]))
    if not out:
        raise ValueError(f"no models for level {level}")
    return xr.concat(out, dim="member")


def to_cells(field: xr.DataArray, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """Bilinear interpolation of (month, lat, lon) to cell points, with longitude wrap."""
    f = field.sortby("lat").sortby("lon")
    # pad longitude for wrap-around
    left = f.isel(lon=-1).assign_coords(lon=f.lon[-1].values - 360)
    right = f.isel(lon=0).assign_coords(lon=f.lon[0].values + 360)
    f = xr.concat([left, f, right], dim="lon")
    pts = f.interp(lat=xr.DataArray(lat, dims="cell"), lon=xr.DataArray(lon, dims="cell"))
    # cells outside the model land mask (NaN) take the nearest valid value
    if np.isnan(pts.values).any():
        near = (
            f.ffill("lon")
            .bfill("lon")
            .ffill("lat")
            .bfill("lat")
            .interp(
                lat=xr.DataArray(lat, dims="cell"),
                lon=xr.DataArray(lon, dims="cell"),
                method="nearest",
            )
        )
        pts = pts.fillna(near)
    return pts.transpose("month", "cell").values.astype(np.float32)
