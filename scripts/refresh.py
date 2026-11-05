"""Scheduled refresh (GitHub Actions, daily). Resumable: every step is a no-op when there is
nothing new.

1. pull pipeline state and inputs from the dev blob
2. once ARCO-ERA5 has a new complete month, rebuild this year's ERA5 daily store from it (a few
   minutes; scripts/fetch_arco.py current) and recompute this year's (and last year's) observed
   metrics
3. rebuild the PiN units/weights when the HNRP mirror's plan data change
4. rebuild the exposure tables, push everything back to blob

    uv run python scripts/refresh.py
"""

import datetime as dt
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

    sys.path.insert(0, str(ROOT / "scripts"))
    import fetch_arco

    this_year = dt.date.today().year
    before = {y: fetch_arco.compact_last_date(y) for y in (this_year - 1, this_year)}
    run("scripts/fetch_arco.py", "current")
    after = {y: fetch_arco.compact_last_date(y) for y in (this_year - 1, this_year)}
    years = sorted(y for y in after if after[y] is not None and after[y] != before[y])
    run(
        "scripts/sync_blob.py", "up", "current"
    )  # at once, so a later failure can't force a re-read
    if years:
        logger.info("new ERA5 data for %s", years)
        affected = sorted(set(years) | {y - 1 for y in years})
        run("scripts/build_observed.py", "years", *map(str, affected))
        run("scripts/sync_blob.py", "up", "metrics")

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
