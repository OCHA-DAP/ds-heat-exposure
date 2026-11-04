"""ERA5 daily backfill, a few requests at a time.

The Copernicus data stores ask users to "submit requests sequentially, rather than in parallel or in
large batches" (service protection measures, October 2026) and may suspend accounts that don't. The
CDS key used here is shared with other team monitoring (the EWDS flood runs), so this driver keeps at
most MAX_IN_FLIGHT requests open, polls only those, and holds new submissions around the 10:00 UTC
Somalia flood-monitoring run. Resumable: state lives in data/state/era5_jobs.json.

    uv run python scripts/backfill_sequential.py                     # laptop
    run_task.py scripts/backfill_sequential.py --stage dev -- --persist-blob   # Databricks job

Order: the heatwave baseline (Tmax/Tmin 1986-2005), the projection reference (1995-2014), the latest
years, the current year, then the rest.
"""

import datetime as dt
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fetch_era5 as fe  # noqa: E402
from heat import era5  # noqa: E402
from heat.cds_jobs import JobBook  # noqa: E402

logger = logging.getLogger("backfill")

MAX_IN_FLIGHT = 2
POLL_SECONDS = 300
MAX_FAILURES = 2
QUIET_UTC = (dt.time(9, 40), dt.time(10, 40))  # around the SOM flood-monitoring run


def queue(today=None) -> list[tuple[str, int, list[int] | None]]:
    today = today or dt.date.today()
    last_full = today.year - 1
    q = []
    q += [(v, y, None) for y in range(1986, 2006) for v in ("tmax", "tmin")]
    q += [(v, y, None) for y in range(1995, 2015) for v in ("tdew",)]
    q += [(v, y, None) for y in range(2006, 2015) for v in ("tmax", "tmin")]
    q += [(v, last_full, None) for v in ("tmax", "tmin", "tdew")]
    months = era5.complete_months(today.year, today)
    if months:
        q += [(v, today.year, months) for v in ("tmax", "tmin", "tdew", "tmean")]
    q += [(v, y, None) for y in range(last_full - 1, 2014, -1) for v in ("tmax", "tmin", "tdew")]
    q += [(v, y, None) for y in range(1986, 1995) for v in ("tdew",)]
    seen, out = set(), []
    for item in q:
        if (item[0], item[1]) not in seen:
            seen.add((item[0], item[1]))
            out.append(item)
    return out


def name_for(v, y, months):
    return f"{v}_{y}m{months[-1]:02d}" if months else f"{v}_{y}"


REMOTE_DONE: set[str] = (
    set()
)  # era5c/{var}/{var}_{year}.nc names on the project blob (--persist-blob)


def done(v, y, months) -> bool:
    if months is not None:
        # the current year: done once this month-tag's request has been compacted
        job = fe.BOOK.jobs.get(name_for(v, y, months), {})
        return bool(job.get("compacted"))
    rel = f"era5c/{v}/{v}_{y}.nc"
    return (fe.STORE / v / f"{v}_{y}.nc").exists() or rel in REMOTE_DONE


def quiet_now() -> bool:
    now = dt.datetime.now(dt.timezone.utc).time()
    return QUIET_UTC[0] <= now <= QUIET_UTC[1]


def persist():
    """Push compacted years and the job state to the project blob, and refresh REMOTE_DONE."""
    import sync_blob

    sync_blob.up(["era5c", "state"])
    c = sync_blob.client()
    REMOTE_DONE.clear()
    REMOTE_DONE.update(k for k in sync_blob.remote_sizes(c, "era5c/") if k.endswith(".nc"))


def main(persist_blob: bool = False):
    if persist_blob:
        import sync_blob

        # resume: the job state and the cell index come from the project blob
        sync_blob.down(["state", "static"])
        persist()
    while True:
        fe.BOOK = JobBook(fe.BOOK.path)  # re-read state (fe.collect uses the module global)
        fe.collect()  # downloads finished jobs: shared copy -> compact -> delete raw
        if persist_blob:
            persist()
        book = fe.BOOK
        in_flight = [n for n, j in book.jobs.items() if j["status"] == "submitted"]
        todo = [(v, y, m) for v, y, m in queue() if not done(v, y, m)]
        if not todo and not in_flight:
            logger.info("backfill complete")
            break
        while len(in_flight) < MAX_IN_FLIGHT and todo and not quiet_now():
            v, y, m = todo.pop(0)
            name = name_for(v, y, m)
            job = book.jobs.get(name)
            if job and job["status"] in ("submitted", "downloaded"):
                continue
            attempts = job.get("attempts", 1) if job else 0
            if job and job["status"] == "failed" and attempts >= MAX_FAILURES:
                logger.warning("%s failed %d times; skipping", name, attempts)
                continue
            if m is None and fe.from_shared(v, y):
                fe.collect()
                continue
            book.submit(
                name, era5.DAILY_DATASET, era5.daily_request(v, y, m), fe.RAW / f"{name}.nc"
            )
            book.jobs[name]["attempts"] = attempts + 1
            book.save()
            in_flight.append(name)
            logger.info("submitted %s (%d still to go)", name, len(todo))
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--persist-blob",
        action="store_true",
        help="keep state and compacted years on the project blob (Databricks runs)",
    )
    main(ap.parse_args().persist_blob)
