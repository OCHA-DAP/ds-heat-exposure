"""Scheduled refresh (GitHub Actions, daily). Resumable: every step is a no-op when there is
nothing new.

1. pull pipeline state and inputs from the dev blob
2. submit the current year's ERA5 requests once a new month is complete (CDS queue can take hours;
   the job ids live in data/state/era5_jobs.json on blob, so a later run collects them)
3. collect finished requests, compact, recompute this year's (and last year's) observed metrics
4. rebuild the PiN units/weights when the HNRP mirror's plan data change
5. rebuild the exposure tables, push everything back to blob

    uv run python scripts/refresh.py
"""

import hashlib
import json
import logging
import subprocess
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("refresh")

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "data" / "state"
PLANS_URL = "https://ocha-dap.github.io/ds-hnrp-mirror/data/plans.json"


def run(*args):
    logger.info("$ %s", " ".join(args))
    subprocess.run([sys.executable, *args], cwd=ROOT, check=True)


def plans_fingerprint() -> str:
    """Hash of the plan fields we use (not the mirror's generated_at, which changes daily)."""
    from heat import pin

    cp = pin.country_plans()
    return hashlib.sha256(cp.to_csv(index=False).encode()).hexdigest()[:16]


def main():
    run("scripts/sync_blob.py", "down", "state", "static", "current", "metrics", "pop")
    STATE.mkdir(parents=True, exist_ok=True)

    from heat.cds_jobs import JobBook

    book = JobBook(STATE / "era5_jobs.json")
    before = {n for n, j in book.jobs.items() if j.get("compacted")}
    run("scripts/fetch_era5.py", "current")
    run("scripts/fetch_era5.py", "collect")
    book = JobBook(STATE / "era5_jobs.json")
    new = {n for n, j in book.jobs.items() if j.get("compacted")} - before
    years = sorted({int(n.split("_", 1)[1][:4]) for n in new})
    if years:
        logger.info("new ERA5 data for %s", years)
        affected = sorted(set(years) | {y - 1 for y in years})
        run("scripts/build_observed.py", "years", *map(str, affected))
        run("scripts/sync_blob.py", "up", "current", "metrics")

    fp_path = STATE / "plans_fingerprint.json"
    old = json.loads(fp_path.read_text()).get("fp") if fp_path.exists() else None
    fp = plans_fingerprint()
    if fp != old:
        logger.info("plan data changed (%s -> %s): rebuilding PiN units and weights", old, fp)
        run("scripts/sync_blob.py", "down", "worldpop")
        run("scripts/build_population.py", "plans")
        fp_path.write_text(json.dumps({"fp": fp}))
        run("scripts/sync_blob.py", "up", "pop")

    run("scripts/build_tables.py")
    run("scripts/sync_blob.py", "up", "tables", "state")


if __name__ == "__main__":
    main()
