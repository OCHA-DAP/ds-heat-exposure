"""World country outlines for the dashboard map, in d3 winding (one-off; rerun only to refresh).

    uv run python scripts/build_world.py

Reads FieldMaps' admin-0 polygons (international worldview: disputed areas as in the UN Clear Map;
USGS coastlines, public domain; https://fieldmaps.io/data/adm0) one country at a time over HTTP,
simplifies each to ~TOL degrees, keeps every country's largest part plus any other part bigger than
MIN_AREA (so small island states don't vanish), drops Antarctica, orients rings the way d3-geo
expects (clockwise exteriors) and writes site/world.json (GeoJSON, 2-decimal coordinates).
"""

import json
import logging
from pathlib import Path

import pyarrow.parquet as pq
import shapely
from fsspec.implementations.http import HTTPFileSystem
from shapely.geometry import MultiPolygon, Polygon, mapping
from shapely.geometry.polygon import orient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("build_world")

URL = "https://data.fieldmaps.io/adm0/usgs/intl/adm0_polygons.parquet"
OUT = Path(__file__).resolve().parent.parent / "site" / "world.json"
TOL = 0.08  # degrees (~9 km); a screen pixel is ~40 km at full view, ~5 km at the 8x zoom limit
MIN_AREA = 0.3  # square degrees; smaller parts are kept only if they are a country's largest


def polygons(g):
    if isinstance(g, Polygon):
        return [g]
    if isinstance(g, MultiPolygon):
        return list(g.geoms)
    return [p for part in getattr(g, "geoms", []) for p in polygons(part)]


def d3_orient(g):
    """Clockwise exterior rings in lon/lat: d3-geo is spherical and fills the complement otherwise."""
    parts = [orient(p, -1.0) for p in polygons(g)]
    return parts[0] if len(parts) == 1 else MultiPolygon(parts)


def rounded(coords):
    if isinstance(coords, (float, int)):
        return round(coords, 2)
    return [rounded(c) for c in coords]


def main():
    f = pq.ParquetFile(URL, filesystem=HTTPFileSystem())
    feats = []
    for i in range(f.metadata.num_row_groups):
        t = f.read_row_group(i, columns=["iso_3", "adm0_name", "status_nm", "geometry"]).to_pylist()[0]
        if t["iso_3"] == "ATA":
            continue
        parts = [
            p.simplify(TOL, preserve_topology=True)
            for p in polygons(shapely.from_wkb(t["geometry"]))
        ]
        parts = [p for p in parts if not p.is_empty]
        if not parts:
            continue
        largest = max(parts, key=lambda p: p.area)
        keep = [p for p in parts if p is largest or p.area >= MIN_AREA]
        geom = d3_orient(MultiPolygon(keep) if len(keep) > 1 else keep[0])
        gj = mapping(geom)
        feats.append(
            {
                "type": "Feature",
                "properties": {"iso3": t["iso_3"], "name": t["adm0_name"], "status": t["status_nm"]},
                "geometry": {"type": gj["type"], "coordinates": rounded(gj["coordinates"])},
            }
        )
        if (i + 1) % 50 == 0:
            logger.info("%d/%d", i + 1, f.metadata.num_row_groups)
    OUT.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":")))
    logger.info("%s: %d features, %.0f KB", OUT, len(feats), OUT.stat().st_size / 1e3)


if __name__ == "__main__":
    main()
