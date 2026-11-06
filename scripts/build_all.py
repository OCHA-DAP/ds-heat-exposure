"""Everything after the ERA5 backfill, in one go (Databricks task or laptop).

    uv run python scripts/build_all.py [--from STEP]

Pulls the inputs from blob (compact ERA5 store and job state from the project prefix; Atlas files,
ERA5 static fields and WorldPop from the team-shared raster container), then builds the 1986-2005
percentiles, the observed metrics for every year, the warming-level changes and the shifted
projections, the shift-vs-Atlas cross-check and the exposure tables. Each step's outputs go back
to blob as soon as it finishes, so after a failure `--from STEP` picks up from the saved outputs
(on Databricks: repair the run with job_parameters {"build_from": "STEP"}; Databricks
refuses python_params on a job that has job parameters).

Steps: p95 (skipped when p95.nc is already on blob), years, deltas, shift, check, tables.
"""

import argparse
import logging
import subprocess
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("build_all")
ROOT = Path(__file__).resolve().parent.parent

STEPS = {
    "p95": [("scripts/build_observed.py", "p95"), ("scripts/sync_blob.py", "up", "static")],
    "years": [
        ("scripts/build_observed.py", "years"),
        ("scripts/sync_blob.py", "up", "static", "metrics"),  # static: ps_clim.nc
    ],
    "deltas": [("scripts/build_projections.py", "deltas"), ("scripts/sync_blob.py", "up", "static")],
    "shift": [
        ("scripts/build_projections.py", "shift"),
        ("scripts/sync_blob.py", "up", "static", "metrics"),  # static: ps_clim.nc if shift made it
    ],
    "check": [("scripts/build_projections.py", "check")],
    "tables": [("scripts/build_tables.py",), ("scripts/sync_blob.py", "up", "tables")],
}


def run(*args):
    logger.info("$ %s", " ".join(args))
    subprocess.run([sys.executable, *args], cwd=ROOT, check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", choices=list(STEPS), default="p95")
    a = ap.parse_args()
    names = list(STEPS)[list(STEPS).index(a.start) :]
    groups = ["state", "static", "era5c", "pop", "era5static", "atlas"]
    if a.start not in ("p95", "years"):
        groups.append("metrics")  # observed years (and projections) from the earlier run
    run("scripts/sync_blob.py", "down", *groups)
    for name in names:
        if name == "p95" and (ROOT / "data" / "metrics" / "p95.nc").exists():
            logger.info("p95.nc already on blob; skipping p95")
            continue
        for cmd in STEPS[name]:
            run(*cmd)


if __name__ == "__main__":
    main()
