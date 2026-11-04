"""Submit / collect the C3S Atlas files (CMIP6 monthly changes + ERA5 observed counts).

    uv run python scripts/fetch_atlas.py submit
    uv run python scripts/fetch_atlas.py collect

Files land in data/raw/atlas/. They are small pre-computed files (monthly, Atlas grid).
"""

import logging
import sys
from pathlib import Path

from heat.cds_jobs import JobBook

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "atlas"
BOOK = JobBook(ROOT / "data" / "state" / "atlas_jobs.json")
AREA = [75, -180, -60, 180]  # N, W, S, E: populated land

# CMIP6 changes for the shift method (no bias adjustment needed: only differences are used)
CMIP6_DELTA_VARS = [
    "monthly_daily_maximum_temperature",
    "monthly_daily_minimum_temperature",
    "monthly_temperature",
    "monthly_near_surface_specific_humidity",
]
# CMIP6 ISIMIP bias-adjusted counts: cross-check for the shift method
CMIP6_COUNT_VARS = ["monthly_extreme_hot_days", "monthly_very_extreme_hot_days"]
# ERA5 observed, 1940-2025
ERA5_VARS = ["monthly_extreme_hot_days", "monthly_very_extreme_hot_days", "monthly_temperature"]

EXPERIMENTS = {"historical": "1850-2014", "ssp5_8_5": "2015-2100"}


def requests():
    for var in CMIP6_DELTA_VARS:
        for exp, period in EXPERIMENTS.items():
            yield (
                f"cmip6_{var}_{exp}",
                {
                    "origin": "cmip6",
                    "experiment": exp,
                    "domain": "global",
                    "period": period,
                    "variable": var,
                    "bias_adjustment": "no_bias_adjustment",
                    "area": AREA,
                },
            )
    for var in CMIP6_COUNT_VARS:
        for exp, period in EXPERIMENTS.items():
            yield (
                f"cmip6isimip_{var}_{exp}",
                {
                    "origin": "cmip6",
                    "experiment": exp,
                    "domain": "global",
                    "period": period,
                    "variable": var,
                    "bias_adjustment": "isimip_method",
                    "area": AREA,
                },
            )
    for var in ERA5_VARS:
        yield (
            f"era5_{var}",
            {
                "origin": "era5",
                "domain": "global",
                "period": "1940-2025",
                "variable": var,
                "area": AREA,
            },
        )


def main(cmd):
    if cmd == "submit":
        for name, req in requests():
            BOOK.submit(name, "multi-origin-c3s-atlas", req, RAW / f"{name}.zip")
    elif cmd == "collect":
        BOOK.collect()
    print(BOOK.status_counts())


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "collect")
