"""Projected heat metrics at 1.5 / 2 / 3 °C of global warming, by shifting ERA5 1995-2014.

    uv run python scripts/build_projections.py deltas     # Atlas CMIP6 -> data/metrics/deltas_{L}.nc
    uv run python scripts/build_projections.py shift      # ERA5 1995-2014 shifted -> data/metrics/proj/
    uv run python scripts/build_projections.py check      # shift vs Atlas ISIMIP TX35/TX40 changes

Outputs (data/metrics/proj/):
  ref.nc          mean annual counts over 1995-2014 (unshifted) + mat (Atlas ERA5 annual mean)
  gwl_{L}.nc      the same with the CMIP6 change at warming level L applied
"""

import logging
import sys
from pathlib import Path

import numpy as np
import xarray as xr

from heat import era5, metrics, projections

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("build_projections")

ROOT = Path(__file__).resolve().parent.parent
ATLAS = ROOT / "data" / "raw" / "atlas"
STORE = ROOT / "data" / "era5c"
OUT = ROOT / "data" / "metrics"
REF_YEARS = range(projections.REF[0], projections.REF[1] + 1)


def cells():
    return xr.open_dataset(STORE / "cells.nc").load()


def build_deltas():
    c = cells()
    table = projections.gwl_table()
    arrays = {}
    for short, var in projections.DELTA_VARS.items():
        arrays[short] = (
            projections.open_atlas(ATLAS / f"cmip6_{var}_historical.zip"),
            projections.open_atlas(ATLAS / f"cmip6_{var}_ssp5_8_5.zip"),
        )
    # same models for every variable, so temperature and humidity changes are consistent
    common = None
    for hist, fut in arrays.values():
        ms = set(hist.member.values) & set(fut.member.values)
        common = ms if common is None else common & ms
    common = {m for m in common if projections.table_row(table, m) is not None}
    logger.info("models with all four variables and a warming-level row: %d", len(common))
    for level in projections.LEVELS:
        fields, attrs = {}, {"level": level}
        for short, (hist, fut) in arrays.items():
            d = projections.model_deltas(
                hist, fut, table, level, ratio=(short == "qratio"), only=common
            )
            med = d.median("member").compute()
            fields[short] = (
                ("month", "cell"),
                projections.to_cells(med, c.lat.values, c.lon.values),
            )
            attrs[f"n_models_{short}"] = int(d.sizes["member"])
            attrs[f"models_{short}"] = ",".join(sorted(str(m) for m in d.member.values))
            logger.info("L=%s %s: %d models", level, short, d.sizes["member"])
        xr.Dataset(fields, attrs=attrs).to_netcdf(OUT / f"deltas_{level}.nc")


def atlas_era5_mat(c, years) -> np.ndarray:
    """Mean annual temperature over `years` from the Atlas ERA5 monthly series, on the cells."""
    da = projections.open_atlas(ATLAS / "era5_monthly_temperature.zip")
    if float(da.max()) > 200:  # kelvin
        da = da - 273.15
    sel = da.sel(time=slice(f"{years[0]}-01-01", f"{years[-1]}-12-31")).mean("time")
    pts = sel.sel(
        lat=xr.DataArray(c.lat.values, dims="cell"),
        lon=xr.DataArray(c.lon.values, dims="cell"),
        method="nearest",
    )
    return pts.values.astype(np.float32)


def build_shift():
    c = cells()
    ps = xr.open_dataarray(OUT / "ps_clim.nc").values
    p95 = xr.open_dataset(OUT / "p95.nc")
    p95max, p95min = p95.p95max.values, p95.p95min.values
    deltas = {L: xr.open_dataset(OUT / f"deltas_{L}.nc").load() for L in projections.LEVELS}
    scen = {"ref": None, **{f"gwl_{L}": deltas[L] for L in projections.LEVELS}}
    acc = {
        s: {m: np.zeros(c.sizes["cell"], dtype=np.float64) for m in metrics.ALL_COUNTS}
        for s in scen
    }
    years = list(REF_YEARS)
    for y in years:
        tmax = era5.load_compact(STORE, "tmax", y)
        times = tmax.time.values
        tmax = tmax.values
        tmin = era5.load_compact(STORE, "tmin", y).values
        tdew = era5.load_compact(STORE, "tdew", y).values
        mi = metrics.month_index(times)
        for s, d in scen.items():
            dmx = d.dtmax.values if d is not None else None
            dq = d.qratio.values if d is not None else None
            f = metrics.daily_fields(tmax, tdew, ps, times, dtmax=dmx, dq_ratio=dq)
            for m, v in metrics.count_days(f).items():
                acc[s][m] += v
            tmn = tmin + (d.dtmin.values[mi] if d is not None else 0.0)
            hot = metrics.heatwave_flags(f["tmax"], tmn, p95max, p95min)
            acc[s][metrics.HEATWAVE] += metrics.heatwave_days(hot)
            del f
        logger.info("shifted %d", y)
    mat_ref = atlas_era5_mat(c, years)
    (OUT / "proj").mkdir(parents=True, exist_ok=True)
    for s, d in scen.items():
        fields = {m: ("cell", (v / len(years)).astype(np.float32)) for m, v in acc[s].items()}
        mat = mat_ref + (d.dtmean.values.mean(axis=0) if d is not None else 0.0)
        fields["mat"] = ("cell", mat.astype(np.float32))
        xr.Dataset(fields, attrs={"scenario": s, "ref_years": f"{years[0]}-{years[-1]}"}).to_netcdf(
            OUT / "proj" / f"{s}.nc"
        )


def check():
    """Compare the shift method's change in hot days with the Atlas ISIMIP-adjusted CMIP6 change."""
    c = cells()
    table = projections.gwl_table()
    pop = xr.open_dataset(ROOT / "data" / "pop" / "pop_grid025.nc").total.values[
        c.iy.values, c.ix.values
    ]
    ref = xr.open_dataset(OUT / "proj" / "ref.nc")
    for var, metric in (
        ("monthly_extreme_hot_days", "tx35"),
        ("monthly_very_extreme_hot_days", "tx40"),
    ):
        hist = projections.open_atlas(ATLAS / f"cmip6isimip_{var}_historical.zip")
        fut = projections.open_atlas(ATLAS / f"cmip6isimip_{var}_ssp5_8_5.zip")
        for L in projections.LEVELS:
            d = projections.model_deltas(hist, fut, table, L, ratio=False)  # per month, days
            atlas = projections.to_cells(d.median("member"), c.lat.values, c.lon.values).sum(axis=0)
            shift = (
                xr.open_dataset(OUT / "proj" / f"gwl_{L}.nc")[metric].values - ref[metric].values
            )
            w = pop / pop.sum()
            logger.info(
                "%s +%s°C: pop-weighted change, shift %.1f d vs Atlas ISIMIP %.1f d (%d models)",
                metric,
                L,
                (shift * w).sum(),
                (atlas * w).sum(),
                d.sizes["member"],
            )


if __name__ == "__main__":
    {"deltas": build_deltas, "shift": build_shift, "check": check}[sys.argv[1]]()
