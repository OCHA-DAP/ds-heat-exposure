"""Team-shared copies of the third-party data this project downloads, in the dev `raster` container,
so other projects reuse them instead of downloading again (KB: infrastructure/datasets/era5-daily.md).

  era5/daily/raw/{variable}_{statistic}/era5_daily_{variable}_{statistic}_{YYYY}.nc
        CDS derived-era5-single-levels-daily-statistics, untouched NetCDF, one file per year,
        0.25°, 75N-60S, 1-hourly input, UTC days. The current year is overwritten each month.
  era5/static/raw/era5_land_sea_mask.nc
  era5/monthly/raw/era5_surface_pressure_monthly_2015-2024.nc
  c3s_atlas/raw/{origin}_{variable}_{experiment}_{bias_adjustment}_75N-60S.zip
        C3S Atlas (multi-origin-c3s-atlas), untouched download
  worldpop/age_structures/global_t_{AA}_2026_CN_1km_R2025A_UA_v1.tif   (next to worldpop/pop_count/)

Writes go to DEV only (prod writes run on Databricks).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path

import ocha_stratus as stratus

logger = logging.getLogger(__name__)

CONTAINER = "raster"
STAGE = "dev"
PRODUCER = "OCHA-DAP/ds-heat-exposure"


def era5_daily_blob(cds_variable: str, statistic: str, year: int) -> str:
    folder = f"{cds_variable}_{statistic}"
    return f"era5/daily/raw/{folder}/era5_daily_{folder}_{year}.nc"


ERA5_STATIC = {
    "lsm": "era5/static/raw/era5_land_sea_mask.nc",
    "ps_clim": "era5/monthly/raw/era5_surface_pressure_monthly_2015-2024.nc",
}


def atlas_blob(request: dict) -> str:
    parts = [request["origin"], request["variable"]]
    if "experiment" in request:
        parts.append(request["experiment"])
    parts.append(request.get("bias_adjustment", "no_bias_adjustment"))
    return "c3s_atlas/raw/" + "_".join(parts) + "_75N-60S.zip"


def worldpop_age_blob(filename: str) -> str:
    return f"worldpop/age_structures/{filename}"


def _client(write=False):
    return stratus.get_container_client(container_name=CONTAINER, stage=STAGE, write=write)


def blob_size(name: str) -> int | None:
    b = _client().get_blob_client(name)
    try:
        return b.get_blob_properties().size
    except Exception:
        return None


def upload(local: Path, name: str, source: dict | None = None, overwrite_if_size_differs=True):
    """Upload `local` to the shared container unless an identical-size copy is already there."""
    local = Path(local)
    size = local.stat().st_size
    have = blob_size(name)
    if have == size or (have is not None and not overwrite_if_size_differs):
        return False
    meta = {
        "producer": PRODUCER,
        "uploaded": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if source:
        # blob metadata values must be ASCII strings
        meta["source"] = json.dumps(source, separators=(",", ":"))[:7000]
    with open(local, "rb") as f:
        _client(write=True).upload_blob(name, f, overwrite=True, metadata=meta, max_concurrency=8)
    logger.info("shared copy: %s/%s (%.0f MB)", CONTAINER, name, size / 1e6)
    return True


def download(name: str, local: Path) -> bool:
    if blob_size(name) is None:
        return False
    local = Path(local)
    local.parent.mkdir(parents=True, exist_ok=True)
    tmp = local.with_suffix(local.suffix + ".part")
    with open(tmp, "wb") as f:
        _client().download_blob(name, max_concurrency=8).readinto(f)
    tmp.replace(local)
    return True
