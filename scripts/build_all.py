"""Everything after the ERA5 backfill, in one go (Databricks task or laptop).

    uv run python scripts/build_all.py

Pulls the inputs from blob (compact ERA5 store and job state from the project prefix; Atlas files,
ERA5 static fields and WorldPop from the team-shared raster container), then builds the 1986-2005
percentiles, the observed metrics for every year, the warming-level changes and the shifted
projections, the shift-vs-Atlas cross-check, the exposure tables, and pushes the results back.
"""

import logging
import subprocess
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("build_all")
ROOT = Path(__file__).resolve().parent.parent


def run(*args):
    logger.info("$ %s", " ".join(args))
    subprocess.run([sys.executable, *args], cwd=ROOT, check=True)


def main():
    run("scripts/sync_blob.py", "down", "state", "static", "era5c", "pop", "era5static", "atlas")
    if not (ROOT / "data" / "metrics" / "p95.nc").exists():
        run("scripts/build_observed.py", "p95")
    run("scripts/build_observed.py", "years")
    run("scripts/build_projections.py", "deltas")
    run("scripts/build_projections.py", "shift")
    run("scripts/build_projections.py", "check")
    run("scripts/sync_blob.py", "up", "static", "metrics")
    run("scripts/build_tables.py")
    run("scripts/sync_blob.py", "up", "tables")


if __name__ == "__main__":
    main()
