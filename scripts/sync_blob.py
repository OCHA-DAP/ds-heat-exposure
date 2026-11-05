"""Move pipeline files between data/ and the dev blob (projects/ds-heat-exposure/).

    uv run python scripts/sync_blob.py up   GROUP [GROUP ...]
    uv run python scripts/sync_blob.py down GROUP [GROUP ...]

Groups (paths relative to data/):
  state     state/*.json                     plan fingerprint; CDS job ids of the one-off downloads
  static    era5c/cells.nc, metrics/p95.nc, metrics/ps_clim.nc, metrics/deltas_*.nc
  current   era5c/*/*_{this year and last}.nc  daily store needed for the monthly refresh
  era5c     era5c/**                         the whole compact ERA5 archive (~19 GB; backfill/build)
  metrics   metrics/obs/*.nc, metrics/proj/*.nc
  pop       pop/** (grids, plans.csv, units, weights)
  worldpop  raw/worldpop/*.tif               1 km WorldPop 2026 (~2.2 GB; needed to rebuild plans),
                                             DOWN only, from the team-shared raster container
  atlas     raw/atlas/*.zip                  C3S Atlas downloads (~28 GB), DOWN only, shared container
  era5static raw/era5/lsm.nc, ps_clim.nc     DOWN only, shared container
  tables    tables/*

Uploads only send files whose size differs from the blob copy; downloads likewise.
"""

import datetime as dt
import logging
import os
import sys
from pathlib import Path

import ocha_stratus as stratus

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("azure").setLevel(logging.WARNING)
logger = logging.getLogger("sync_blob")

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
PREFIX = "ds-heat-exposure"
CONTAINER = "projects"
STAGE = os.environ.get("STAGE", "dev")


def _year_globs():
    # this year and last year are recomputed; the year before gives last year's 31 December
    # heatwave flag
    y = dt.date.today().year
    return [
        f"era5c/*/*_{y}.nc",
        f"era5c/*/*_{y - 1}.nc",
        f"era5c/tmax/tmax_{y - 2}.nc",
        f"era5c/tmin/tmin_{y - 2}.nc",
    ]


GROUPS = {
    "state": ["state/*.json"],
    "static": ["era5c/cells.nc", "metrics/p95.nc", "metrics/ps_clim.nc", "metrics/deltas_*.nc"],
    "current": None,  # computed
    "era5c": ["era5c/**/*.nc"],
    "metrics": ["metrics/obs/*.nc", "metrics/proj/*.nc"],
    "pop": ["pop/*.nc", "pop/*.csv", "pop/units/*.parquet", "pop/weights/*.parquet"],
    "tables": ["tables/*"],
}


def patterns(group):
    return _year_globs() if group == "current" else GROUPS[group]


def client(write=False):
    return stratus.get_container_client(container_name=CONTAINER, stage=STAGE, write=write)


def remote_sizes(c, sub=""):
    return {
        b.name[len(PREFIX) + 1 :]: b.size for b in c.list_blobs(name_starts_with=f"{PREFIX}/{sub}")
    }


def up(groups):
    c = client(write=True)
    have = remote_sizes(c)
    n = 0
    for g in groups:
        for pat in patterns(g):
            for p in sorted(DATA.glob(pat)):
                if not p.is_file():
                    continue
                rel = p.relative_to(DATA).as_posix()
                if have.get(rel) == p.stat().st_size:
                    continue
                with open(p, "rb") as f:
                    c.upload_blob(f"{PREFIX}/{rel}", f, overwrite=True, max_concurrency=4)
                n += 1
                logger.info("up %s (%.1f MB)", rel, p.stat().st_size / 1e6)
    logger.info("uploaded %d files", n)


def down(groups):
    import fnmatch

    c = client()
    have = remote_sizes(c)
    n = 0
    for g in groups:
        for pat in patterns(g):
            regex_pat = pat.replace("**/", "*")
            for rel, size in sorted(have.items()):
                if not fnmatch.fnmatch(rel, regex_pat):
                    continue
                p = DATA / rel
                if p.exists() and p.stat().st_size == size:
                    continue
                p.parent.mkdir(parents=True, exist_ok=True)
                tmp = p.with_suffix(p.suffix + ".part")
                with open(tmp, "wb") as f:
                    c.download_blob(f"{PREFIX}/{rel}", max_concurrency=4).readinto(f)
                tmp.replace(p)
                n += 1
    logger.info("downloaded %d files", n)


def down_atlas():
    """C3S Atlas zips from the team-shared raster container, under their local job names."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import fetch_atlas

    from heat import shared

    for name, req in fetch_atlas.requests():
        local = fetch_atlas.RAW / f"{name}.zip"
        if local.exists() and local.stat().st_size == shared.blob_size(shared.atlas_blob(req)):
            continue
        if not shared.download(shared.atlas_blob(req), local):
            raise SystemExit(f"missing shared blob raster/{shared.atlas_blob(req)}")
        logger.info("down raster/%s", shared.atlas_blob(req))


def down_era5static():
    from heat import shared

    for name, blob in shared.ERA5_STATIC.items():
        local = DATA / "raw" / "era5" / f"{name}.nc"
        if local.exists():
            continue
        if not shared.download(blob, local):
            raise SystemExit(f"missing shared blob raster/{blob}")


def down_worldpop():
    """WorldPop 2026 total + age bands from the team-shared raster container (heat.shared)."""
    from heat import population, shared

    wp = DATA / "raw" / "worldpop"
    blobs = {
        population.wp_path(
            wp, "total"
        ): "worldpop/pop_count/global_pop_2026_CN_1km_R2025A_UA_v1.tif"
    }
    for g in ["00", *population.AGE_65]:
        f = population.wp_path(wp, g)
        blobs[f] = shared.worldpop_age_blob(f.name)
    for local, blob in blobs.items():
        if local.exists() and local.stat().st_size > 0:
            continue
        if not shared.download(blob, local):
            raise SystemExit(f"missing shared blob raster/{blob}")
        logger.info("down raster/%s", blob)


if __name__ == "__main__":
    cmd, *groups = sys.argv[1:]
    special = {"worldpop": down_worldpop, "atlas": down_atlas, "era5static": down_era5static}
    if cmd == "down":
        for g in [g for g in groups if g in special]:
            groups.remove(g)
            special[g]()
        if not groups:
            sys.exit(0)
    bad = [g for g in groups if g not in GROUPS]
    if cmd not in ("up", "down") or not groups or bad:
        sys.exit(__doc__)
    (up if cmd == "up" else down)(groups)
