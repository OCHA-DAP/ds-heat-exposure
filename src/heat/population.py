"""WorldPop R2025A 1 km (30 arc-second) population on the ERA5 0.25° grid, and admin × cell weights.

ERA5 cell centres sit on multiples of 0.25° (edges at ±0.125°); WorldPop pixel centres sit at odd
multiples of 1/240°, so every pixel falls inside exactly one ERA5 cell: no splitting is needed.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import xarray as xr
from rasterio.features import rasterize
from rasterio.windows import Window

logger = logging.getLogger(__name__)

RES = 0.25
LAT_N, LAT_S = 75.0, -60.0  # ERA5 cell-centre range used (see era5.AREA)
NLAT = int(round((LAT_N - LAT_S) / RES)) + 1  # 541
NLON = 1440
LATS = LAT_N - RES * np.arange(NLAT)
LONS = -180.0 + RES * np.arange(NLON)

YEAR = 2026
WP_DIR_DEFAULT = Path("data/raw/worldpop")
AGE_65 = ["65", "70", "75", "80", "85", "90"]


def wp_path(wp_dir: Path, group: str) -> Path:
    if group == "total":
        return wp_dir / f"global_pop_{YEAR}_CN_1km_R2025A_UA_v1.tif"
    return wp_dir / f"global_t_{group}_{YEAR}_CN_1km_R2025A_UA_v1.tif"


def cell_index(lat, lon):
    """ERA5 grid row/col for points (arrays). Rows outside the grid get -1."""
    iy = np.floor((LAT_N + RES / 2 - np.asarray(lat)) / RES).astype(np.int64)
    ix = np.floor((np.asarray(lon) + 180.0 + RES / 2) / RES).astype(np.int64) % NLON
    iy = np.where((iy >= 0) & (iy < NLAT), iy, -1)
    return iy, ix


def to_grid(tif: Path, strip_rows: int = 600) -> np.ndarray:
    """Sum a 1 km population raster into the (NLAT, NLON) ERA5 grid."""
    out = np.zeros(NLAT * NLON, dtype=np.float64)
    with rasterio.open(tif) as src:
        t = src.transform
        assert abs(t.a - 1 / 120) < 1e-9 and abs(t.e + 1 / 120) < 1e-9, t
        cols = np.arange(src.width)
        lon_c = t.c + (cols + 0.5) * t.a
        _, ix = cell_index(np.zeros_like(lon_c), lon_c)
        nodata = src.nodata
        for r0 in range(0, src.height, strip_rows):
            h = min(strip_rows, src.height - r0)
            rows = np.arange(r0, r0 + h)
            lat_c = t.f + (rows + 0.5) * t.e
            iy, _ = cell_index(lat_c, np.zeros_like(lat_c))
            if (iy < 0).all():
                continue
            block = src.read(1, window=Window(0, r0, src.width, h)).astype(np.float64)
            if nodata is not None:
                block[block == nodata] = 0.0
            block[~np.isfinite(block) | (block < 0)] = 0.0
            ok = iy >= 0
            flat = (iy[ok][:, None] * NLON + ix[None, :]).ravel()
            out += np.bincount(flat, weights=block[ok].ravel(), minlength=NLAT * NLON)
    return out.reshape(NLAT, NLON)


def grid_da(arr: np.ndarray, name: str) -> xr.DataArray:
    return xr.DataArray(
        arr.astype("float32"),
        dims=("lat", "lon"),
        coords={"lat": LATS, "lon": LONS},
        name=name,
        attrs={
            "source": f"WorldPop R2025A {YEAR} 1km constrained (UN-adjusted)",
            "units": "people",
        },
    )


def build_grids(wp_dir: Path, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    total = to_grid(wp_path(wp_dir, "total"))
    grid_da(total, "pop").to_netcdf(out_dir / "pop_total_grid025.nc")
    under1 = to_grid(wp_path(wp_dir, "00"))
    age65 = sum(to_grid(wp_path(wp_dir, a)) for a in AGE_65)
    xr.Dataset(
        {
            "total": grid_da(total, "total"),
            "under1": grid_da(under1, "under1"),
            "age65": grid_da(age65, "age65"),
        }
    ).to_netcdf(out_dir / "pop_grid025.nc")
    logger.info(
        "pop grids: total %.3fbn, 65+ %.0fM, <1 %.0fM",
        total.sum() / 1e9,
        age65.sum() / 1e6,
        under1.sum() / 1e6,
    )


def admin_cell_weights(gdf, id_col: str, wp_dir: Path, cells_lookup: np.ndarray) -> pd.DataFrame:
    """Population of every (admin unit, ERA5 cell) pair. Polygons may overlap across `level`s
    (units pooled to admin 1 or the whole country sit on top of matched lower-level units), so each
    level is rasterized on its own; polygons within a level must not overlap."""
    import pandas as pd

    if "level" in gdf.columns and gdf["level"].nunique() > 1:
        parts = [
            _weights_one_layer(g, id_col, wp_dir, cells_lookup) for _, g in gdf.groupby("level")
        ]
        return pd.concat(parts, ignore_index=True)
    return _weights_one_layer(gdf, id_col, wp_dir, cells_lookup)


def _weights_one_layer(gdf, id_col: str, wp_dir: Path, cells_lookup: np.ndarray) -> pd.DataFrame:
    """Population of every (admin unit, ERA5 cell) pair, from 1 km pixels inside each polygon.

    gdf: polygons (EPSG:4326) with an `id_col`. Pixels are assigned by centre (rasterize, not
    all_touched). cells_lookup: (NLAT*NLON,) array mapping grid index -> compact cell id (-1 if none).
    Returns columns [id_col, cell, total, age65, under1].
    """
    import pandas as pd

    groups = {"total": ["total"], "age65": AGE_65, "under1": ["00"]}
    minx, miny, maxx, maxy = gdf.total_bounds
    ids = {v: i + 1 for i, v in enumerate(gdf[id_col])}
    with rasterio.open(wp_path(wp_dir, "total")) as src:
        win = (
            rasterio.windows.from_bounds(minx, miny, maxx, maxy, src.transform)
            .round_offsets()
            .round_lengths()
        )
        win = win.intersection(Window(0, 0, src.width, src.height))
        wt = src.window_transform(win)
        shape = (int(win.height), int(win.width))
    burned = rasterize(
        (
            (geom, ids[v])
            for geom, v in zip(gdf.geometry, gdf[id_col])
            if geom is not None and not geom.is_empty
        ),
        out_shape=shape,
        transform=wt,
        fill=0,
        dtype="int32",
    )
    rows = np.arange(shape[0])
    cols = np.arange(shape[1])
    lat_c = wt.f + (rows + 0.5) * wt.e
    lon_c = wt.c + (cols + 0.5) * wt.a
    iy, _ = cell_index(lat_c, np.zeros_like(lat_c))
    _, ix = cell_index(np.zeros_like(lon_c), lon_c)
    gidx = np.where(iy[:, None] >= 0, iy[:, None] * NLON + ix[None, :], -1)
    cell = np.where(gidx >= 0, cells_lookup[np.clip(gidx, 0, None)], -1)
    sel = (burned > 0) & (cell >= 0)
    key_admin = burned[sel]
    key_cell = cell[sel]
    df = pd.DataFrame({"admin": key_admin, "cell": key_cell})
    for g, members in groups.items():
        acc = np.zeros(sel.sum(), dtype=np.float64)
        for m in members:
            with rasterio.open(wp_path(wp_dir, m)) as src:
                arr = src.read(1, window=win).astype(np.float64)
                if src.nodata is not None:
                    arr[arr == src.nodata] = 0.0
                arr[~np.isfinite(arr) | (arr < 0)] = 0.0
            acc += arr[sel]
        df[g] = acc
    out = df.groupby(["admin", "cell"], as_index=False).sum()
    inv = {i: v for v, i in ids.items()}
    out.insert(0, id_col, out.pop("admin").map(inv))
    return out
