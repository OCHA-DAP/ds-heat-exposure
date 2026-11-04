"""Population inputs.

    uv run python scripts/build_population.py grids     # WorldPop 1 km -> ERA5 0.25° grids
    uv run python scripts/build_population.py plans     # current country plans: PiN units + weights

Outputs (data/pop/):
  pop_total_grid025.nc, pop_grid025.nc     (lat, lon) total / 65+ / under-1
  plans.csv                                one row per current GHO country plan + PiN source notes
  units/{ISO3}.parquet                     PiN units (GeoParquet: unit_id, level, pcode, name, pin)
  weights/{ISO3}_pin.parquet               (unit_id, cell, total, age65, under1) people per unit x cell
  weights/{ISO3}_adm0.parquet              (unit_id=ISO3, cell, total, age65, under1) whole country
"""

import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from heat import pin, population, zonal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("ocha_stratus").setLevel(logging.ERROR)
logger = logging.getLogger("build_population")

ROOT = Path(__file__).resolve().parent.parent
WP = ROOT / "data" / "raw" / "worldpop"
OUT = ROOT / "data" / "pop"
CELLS = ROOT / "data" / "era5c" / "cells.nc"


def cells_lookup():
    c = xr.open_dataset(CELLS)
    lk = np.full(population.NLAT * population.NLON, -1, dtype=np.int64)
    lk[c.iy.values * population.NLON + c.ix.values] = np.arange(c.sizes["cell"])
    return lk


def build_plans():
    lk = cells_lookup()
    (OUT / "units").mkdir(parents=True, exist_ok=True)
    (OUT / "weights").mkdir(parents=True, exist_ok=True)
    cp = pin.country_plans()
    rows = []
    for _, r in cp.iterrows():
        ap = pin.admin_pin(r.iso3, int(r.year), float(r.in_need))
        u = zonal.pin_units(ap)
        polys = u.polygons.copy()
        polys["geometry"] = polys.geometry.make_valid()
        w = population.admin_cell_weights(polys, "unit_id", WP, lk)
        w.to_parquet(OUT / "weights" / f"{r.iso3}_pin.parquet")
        adm0 = zonal.codab(r.iso3, 0).assign(unit_id=r.iso3)
        adm0["geometry"] = adm0.geometry.make_valid()
        w0 = population.admin_cell_weights(adm0, "unit_id", WP, lk)
        w0.to_parquet(OUT / "weights" / f"{r.iso3}_adm0.parquet")
        simple = polys.copy()
        simple["geometry"] = simple.geometry.simplify(0.01, preserve_topology=True)
        simple.to_parquet(OUT / "units" / f"{r.iso3}.parquet")
        no_pop = sorted(set(polys.unit_id) - set(w.unit_id))
        rows.append(
            {
                **r.to_dict(),
                "pin_source": ap.source,
                "pin_source_year": ap.source_year,
                "pin_admin_level": ap.admin_level,
                "n_units": len(polys),
                "matched_share": round(u.matched_share, 4),
                "notes": "; ".join(u.notes),
                "country_pop": w0.total.sum(),
                "units_without_pop": len(no_pop),
            }
        )
        logger.info(
            "%s: %d units, pop %.1fM, %s", r.iso3, len(polys), w0.total.sum() / 1e6, ap.source
        )
    pd.DataFrame(rows).to_csv(OUT / "plans.csv", index=False)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "grids"
    if cmd == "grids":
        population.build_grids(WP, OUT)
    elif cmd == "plans":
        build_plans()
