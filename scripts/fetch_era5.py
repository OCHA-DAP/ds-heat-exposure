"""ERA5 static fields from the CDS (one-off): the land-sea mask and the 2015-2024 monthly surface
pressure (for the per-calendar-month pressure climatology). Daily data come from ARCO-ERA5
(scripts/fetch_arco.py).

    uv run python scripts/fetch_era5.py submit     # both requests (2, so within the CDS limit)
    uv run python scripts/fetch_era5.py collect    # download, share, build cells.nc

Both files are already in the team-shared dev `raster` container (heat.shared.ERA5_STATIC);
`scripts/sync_blob.py down era5static` fetches them from there, so a new setup never needs this.
"""

import argparse
import logging
from pathlib import Path

import xarray as xr

from heat import era5, shared
from heat.cds_jobs import JobBook

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("ecmwf").setLevel(logging.WARNING)
logging.getLogger("azure").setLevel(logging.WARNING)
logger = logging.getLogger("fetch_era5")

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "era5"
STORE = ROOT / "data" / "era5c"
BOOK = JobBook(ROOT / "data" / "state" / "era5_jobs.json")


def submit_static():
    BOOK.submit("lsm", "reanalysis-era5-single-levels", era5.lsm_request(), RAW / "lsm.nc")
    BOOK.submit(
        "ps_clim",
        "reanalysis-era5-single-levels-monthly-means",
        era5.ps_clim_request(),
        RAW / "ps_clim.nc",
    )


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
    BOOK.collect(["lsm", "ps_clim"])
    for name in ("lsm", "ps_clim"):
        job = BOOK.jobs.get(name)
        if job and job["status"] == "downloaded" and not job.get("shared"):
            if Path(job["target"]).exists():
                shared.upload(
                    Path(job["target"]),
                    shared.ERA5_STATIC[name],
                    {"dataset": job["dataset"], "request": job["request"]},
                )
                job["shared"] = shared.ERA5_STATIC[name]
                BOOK.save()
    cells()
    print(BOOK.status_counts())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["submit", "collect", "status"])
    a = ap.parse_args()
    if a.cmd == "submit":
        submit_static()
    elif a.cmd == "collect":
        collect()
    print(BOOK.status_counts())
