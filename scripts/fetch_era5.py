"""ERA5 daily backfill / refresh.

    uv run python scripts/fetch_era5.py submit [--first 1986] [--last 2025]
    uv run python scripts/fetch_era5.py collect          # download finished jobs, compact, delete raw
    uv run python scripts/fetch_era5.py current          # (re)submit the current year's complete months

Raw downloads go to data/raw/era5/ and are deleted once compacted into data/era5c/.
"""

import argparse
import datetime as dt
import logging
from pathlib import Path

import xarray as xr

from heat import era5
from heat.cds_jobs import JobBook

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("ecmwf").setLevel(logging.WARNING)
logger = logging.getLogger("fetch_era5")

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "era5"
STORE = ROOT / "data" / "era5c"
BOOK = JobBook(ROOT / "data" / "state" / "era5_jobs.json")

# backfill variables: tmean comes from the C3S Atlas (ERA5 monthly mean) up to its last year
BACKFILL_VARS = ["tmax", "tmin", "tdew"]
CURRENT_VARS = ["tmax", "tmin", "tdew", "tmean"]


def submit_static():
    BOOK.submit("lsm", "reanalysis-era5-single-levels", era5.lsm_request(), RAW / "lsm.nc")
    BOOK.submit(
        "ps_clim",
        "reanalysis-era5-single-levels-monthly-means",
        era5.ps_clim_request(),
        RAW / "ps_clim.nc",
    )


def submit_backfill(first: int, last: int):
    submit_static()
    # priority order: the heatwave baseline (1986-2005) and projection reference (1995-2014) first
    years = list(range(first, last + 1))
    order = sorted(years, key=lambda y: (0 if 1986 <= y <= 2014 else 1, y))
    for y in order:
        for v in BACKFILL_VARS:
            name = f"{v}_{y}"
            if (STORE / v / f"{v}_{y}.nc").exists():
                continue
            BOOK.submit(name, era5.DAILY_DATASET, era5.daily_request(v, y), RAW / f"{name}.nc")


def submit_current(today=None):
    today = today or dt.date.today()
    year = today.year
    months = era5.complete_months(year, today)
    if not months:
        year -= 1
        months = era5.complete_months(year, today)
    tag = f"{year}m{months[-1]:02d}"
    for v in CURRENT_VARS:
        name = f"{v}_{tag}"
        BOOK.submit(
            name, era5.DAILY_DATASET, era5.daily_request(v, year, months), RAW / f"{name}.nc"
        )
    return year, months


def cells():
    path = STORE / "cells.nc"
    if path.exists():
        return xr.open_dataset(path).load()
    lsm = RAW / "lsm.nc"
    pop = ROOT / "data" / "pop" / "pop_total_grid025.nc"  # written by scripts/build_population.py
    if not (lsm.exists() and pop.exists()):
        return None
    return era5.build_cells(lsm, path, pop)


def collect():
    # download one finished job at a time so raw files never pile up on disk
    pending = [n for n, j in BOOK.jobs.items() if j["status"] == "submitted"]
    statics_first = sorted(pending, key=lambda n: (n not in ("lsm", "ps_clim"), n))
    for name in statics_first:
        got = BOOK.collect([name])
        if not got:
            continue
        if name in ("lsm", "ps_clim"):
            continue
        c = cells()
        if c is None:
            logger.info("%s downloaded; waiting for the land-sea mask before compacting", name)
            continue
        _compact_one(name, c)
    # anything downloaded earlier but not yet compacted (e.g. arrived before the mask)
    c = cells()
    if c is not None:
        for name, job in BOOK.jobs.items():
            if (
                job["status"] == "downloaded"
                and name not in ("lsm", "ps_clim")
                and not job.get("compacted")
            ):
                _compact_one(name, c)
    print(BOOK.status_counts())


def _compact_one(name, c):
    job = BOOK.jobs[name]
    var, tag = name.split("_", 1)
    year = int(tag[:4])
    raw = Path(job["target"])
    if not raw.exists():
        return
    out = STORE / var / f"{var}_{year}.nc"
    era5.compact(raw, c, out, var, year)
    job["compacted"] = str(out)
    BOOK.save()
    raw.unlink()
    logger.info("compacted %s -> %s", name, out.name)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["submit", "collect", "current", "status"])
    ap.add_argument("--first", type=int, default=1986)
    ap.add_argument("--last", type=int, default=2025)
    a = ap.parse_args()
    if a.cmd == "submit":
        submit_backfill(a.first, a.last)
    elif a.cmd == "current":
        print(submit_current())
    elif a.cmd == "collect":
        collect()
    print(BOOK.status_counts())
