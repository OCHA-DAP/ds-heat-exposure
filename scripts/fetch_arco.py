"""ERA5 daily statistics from ARCO-ERA5 hourly data (heat.arco) -> compact store + shared copies.

    uv run python scripts/fetch_arco.py backfill [--first 1986] [--workers 16] [--persist-blob]
    uv run python scripts/fetch_arco.py current [--workers 8]
    uv run python scripts/fetch_arco.py year 1986 [--months 1 7] [--store DIR] [--no-share]

backfill  every complete year from --first, then `current`. A complete year is skipped when its
          four compact files exist (locally, or on the project blob with --persist-blob) and its
          four full-grid files are in the team-shared container. With --persist-blob each year goes
          to the project blob as soon as it is written, so a retried Databricks run resumes.
current   this year's complete months (and last year's December, in January), rebuilt only when
          ARCO-ERA5 has a complete month that the compact files on disk don't have yet (the refresh
          pulls them from blob first). Each rebuild re-reads the whole year, so months that have
          moved from ERA5T to final ERA5 come in too; last year is rebuilt once more when final
          ERA5 reaches its 31 December (~March).
year      one year, for checks. With --months, writes only to --store (required) and shares nothing.

Each year's full-grid daily files (75N-60S, float32 K) go to the shared dev `raster` container
(heat.shared.era5_daily_blob) and are then deleted locally.
"""

import argparse
import datetime as dt
import logging
import sys
from pathlib import Path

import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parent))

from heat import arco, era5, shared  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("azure").setLevel(logging.WARNING)
logger = logging.getLogger("fetch_arco")

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "data" / "era5c"
GRID_TMP = ROOT / "data" / "tmp" / "era5_daily_grid"


def cells(store: Path = STORE) -> xr.Dataset:
    path = store / "cells.nc"
    if not path.exists():
        path = STORE / "cells.nc"
    if not path.exists():
        raise SystemExit("data/era5c/cells.nc missing: `scripts/sync_blob.py down static` first")
    return xr.open_dataset(path).load()


def share(grid_files: dict, year: int, days: int):
    for v, path in grid_files.items():
        var, stat = era5.VARS[v]
        shared.upload(
            path,
            shared.era5_daily_blob(var, stat, year),
            {"source": arco.URL, "method": "UTC daily " + stat, "year": year, "days": days},
        )
        path.unlink()


def shared_done(year: int) -> bool:
    return all(shared.blob_size(shared.era5_daily_blob(*era5.VARS[v], year)) for v in arco.OUT_VARS)


def compact_final_through(year: int, store: Path = STORE) -> dt.date | None:
    """Last final-ERA5 day the year's tmax file was built with (None if missing or unrecorded)."""
    p = store / "tmax" / f"tmax_{year}.nc"
    if not p.exists():
        return None
    with xr.open_dataset(p) as ds:
        v = ds.attrs.get("era5_final_through")
    return dt.date.fromisoformat(v) if v else None


def compact_last_date(year: int, store: Path = STORE) -> dt.date | None:
    """Earliest last day over the four compact files of `year` (None if any is missing)."""
    out = []
    for v in arco.OUT_VARS:
        p = store / v / f"{v}_{year}.nc"
        if not p.exists():
            return None
        with xr.open_dataset(p) as ds:
            out.append(dt.date.fromisoformat(str(ds.time.values[-1])[:10]))
    return min(out)


def build(ds, year, months, store, workers, share_grids=True):
    grid_dir = GRID_TMP if share_grids else None
    files = arco.build_year(ds, year, cells(store), store, grid_dir, months, workers)
    if share_grids:
        share(files, year, len(arco.days_of(year, months)))


def current(ds, workers, store=STORE) -> list[int]:
    """Rebuild last year / this year where ARCO has newer complete months. Returns years rebuilt."""
    last = arco.last_day(ds)
    final = arco.final_through(ds)
    rebuilt = []
    for year in (last.year - 1, last.year):
        months = arco.complete_months(year, last)
        if not months:
            continue
        target = arco.days_of(year, months)[-1]
        have = compact_last_date(year, store)
        if have is None and year < last.year:
            continue  # last year not on disk: the backfill owns complete years
        built_final = compact_final_through(year, store)
        now_final = final >= target and (built_final is None or built_final < target)
        if have is not None and have >= target and not now_final:
            logger.info("%d: up to date (to %s)", year, have)
            continue
        if have is not None and have >= target:
            logger.info("%d: final ERA5 now covers the year; rebuilding", year)
        logger.info("%d: rebuilding to %s (have %s)", year, target, have)
        build(ds, year, months if len(months) < 12 else None, store, workers)
        rebuilt.append(year)
    return rebuilt


def backfill(ds, first, workers, persist_blob):
    remote = set()
    if persist_blob:
        import sync_blob

        sync_blob.down(["static", "current"])  # cells.nc; this year's files for `current`
        c = sync_blob.client()
        remote = set(sync_blob.remote_sizes(c, "era5c/"))
    last = arco.last_day(ds)
    for year in range(first, last.year):  # complete years (current() keeps last year up to date)
        have = all(
            (STORE / v / f"{v}_{year}.nc").exists() or f"era5c/{v}/{v}_{year}.nc" in remote
            for v in arco.OUT_VARS
        )
        if have and shared_done(year):
            continue
        build(ds, year, None, STORE, workers)
        if persist_blob:
            sync_blob.up(["era5c"])
    current(ds, workers)
    if persist_blob:
        sync_blob.up(["era5c"])
    logger.info("backfill complete")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["backfill", "current", "year"])
    ap.add_argument("year", nargs="?", type=int)
    ap.add_argument("--first", type=int, default=1986)
    ap.add_argument("--months", type=int, nargs="*")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--store", type=Path, default=STORE)
    ap.add_argument("--no-share", action="store_true")
    ap.add_argument("--persist-blob", action="store_true")
    a = ap.parse_args()
    store = arco.open_store()
    if a.cmd == "backfill":
        backfill(store, a.first, a.workers, a.persist_blob)
    elif a.cmd == "current":
        print(current(store, a.workers))
    else:
        if a.months and a.store.resolve() == STORE.resolve():
            ap.error(
                "--months needs --store: a partial year must not replace the real compact file"
            )
        share_grids = not (a.no_share or a.months)
        build(store, a.year, a.months, a.store, a.workers, share_grids=share_grids)
