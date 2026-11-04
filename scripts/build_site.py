"""Assemble the dashboard: data JSON inlined into the page, then encrypted for the password gate.

    uv run python scripts/build_site.py                 # site/build/ (plaintext preview, git-ignored)
    PAGE_PASSWORD=... uv run python scripts/build_site.py --encrypt
                                                         # site/build/ with gate + page.enc only

Layout of the built site (Pages artifact):
  index.html                 landing page (one card per product)
  dashboard/index.html       gate (encrypted mode) or the dashboard itself (preview mode)
  dashboard/page.enc         encrypted dashboard incl. data (encrypted mode)

Encryption format as ds-longterm-outlook/pipeline/build_page.py: base64(salt[16] | iv[12] |
AES-256-GCM ciphertext+tag), key = PBKDF2-HMAC-SHA256(password, salt, 300 000 iterations).
"""

import argparse
import base64
import json
import math
import os
import shutil
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
TABLES = Path(os.environ.get("HEAT_TABLES", ROOT / "data" / "tables"))
POP = ROOT / "data" / "pop"
SRC = ROOT / "site"
BUILD = ROOT / "site" / "build"
ITER = 300_000

GROUPS = ["world", "gho_countries", "gho_pin", "hnrp_pin"]
METRICS = ["wbgt32", "wbt31", "tx35", "tx40", "hw", "mat", "wbgt30", "wbt29"]
DAY_MEASURES = [
    "people_ge1",
    "people_ge10",
    "people_ge20",
    "people_ge30",
    "person_days",
    "mean_days",
]


def _r(x, nd=0):
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    return round(float(x), nd) if nd else int(round(float(x)))


def build_data():
    exp = pd.read_parquet(TABLES / "exposure.parquet")
    units = pd.read_parquet(TABLES / "units.parquet")
    meta = json.loads((TABLES / "meta.json").read_text())
    obs = exp[exp.scenario == "observed"].copy()
    years = sorted(obs.period.astype(int).unique().tolist())

    def measures_for(metric):
        return ["people", "people_mat29"] if metric == "mat" else ["people"] + DAY_MEASURES

    series, scen = {}, {}
    scen_names = ["ref", "observed_mean", "gwl_1.5", "gwl_2.0", "gwl_3.0"]
    latest = str(meta["latest_complete_year"])
    key_cols = ["group", "iso3", "age", "metric"]
    for (group, iso3, age, metric), g in exp.groupby(key_cols):
        if metric not in METRICS:
            continue
        gkey = group if not iso3 else f"{group}:{iso3}"
        o = g[g.scenario == "observed"].set_index(g[g.scenario == "observed"].period.astype(int))
        s = g[g.scenario != "observed"].set_index("scenario")
        for m in measures_for(metric):
            if m not in g:
                continue
            nd = 2 if m == "mean_days" else 0
            if not iso3:
                series.setdefault(gkey, {}).setdefault(age, {}).setdefault(metric, {})[m] = [
                    _r(o[m].get(y), nd) if y in o.index else None for y in years
                ]
            row = {sn: _r(s[m].get(sn), nd) if sn in s.index else None for sn in scen_names}
            row["latest"] = _r(o[m].get(int(latest)), nd) if int(latest) in o.index else None
            scen.setdefault(gkey, {}).setdefault(age, {}).setdefault(metric, {})[m] = row

    # map units: geometry + per-unit means
    feats = []
    um = units[
        units.scenario.isin(["observed", "observed_mean", "ref", "gwl_1.5", "gwl_2.0", "gwl_3.0"])
    ]
    um = um.assign(skey=np.where(um.scenario == "observed", "latest", um.scenario))
    plans = pd.read_csv(POP / "plans.csv")
    for iso3 in plans.iso3:
        g = gpd.read_parquet(POP / "units" / f"{iso3}.parquet")
        sub = um[um.iso3 == iso3]
        vals = {}
        for _, r in sub.iterrows():
            v = vals.setdefault(r.unit_id, {})
            for m in METRICS:
                if m in r and pd.notna(r[m]):
                    v.setdefault(m, {})[r.skey] = round(float(r[m]), 2 if m == "mat" else 1)
        for _, u in g.iterrows():
            geom = u.geometry
            if geom is None or geom.is_empty:
                continue
            feats.append(
                {
                    "type": "Feature",
                    "geometry": json.loads(gpd.GeoSeries([geom]).to_json())["features"][0][
                        "geometry"
                    ],
                    "properties": {
                        "id": u.unit_id,
                        "iso3": iso3,
                        "name": u["name"],
                        "level": int(u.level),
                        "pin": _r(u.pin),
                        "v": vals.get(u.unit_id, {}),
                    },
                }
            )
    geo = {"type": "FeatureCollection", "features": feats}
    gtxt = json.dumps(geo, separators=(",", ":"))
    # trim coordinate precision to 3 decimals (~100 m)
    import re

    gtxt = re.sub(r"(-?\d+\.\d{3})\d+", r"\1", gtxt)

    countries = []
    for _, p in plans.iterrows():
        countries.append(
            {
                k: (None if isinstance(v, float) and math.isnan(v) else v)
                for k, v in p.to_dict().items()
            }
        )
    data = {"years": years, "meta": meta, "series": series, "scen": scen, "countries": countries}
    return data, gtxt


def encrypt(plain: bytes, password: str) -> str:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    salt, iv = os.urandom(16), os.urandom(12)
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITER).derive(
        password.encode()
    )
    return base64.b64encode(salt + iv + AESGCM(key).encrypt(iv, plain, None)).decode()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--encrypt", action="store_true")
    a = ap.parse_args()
    data, geo = build_data()
    if BUILD.exists():
        shutil.rmtree(BUILD)
    (BUILD / "dashboard").mkdir(parents=True)
    shutil.copy(SRC / "landing.html", BUILD / "index.html")
    tpl = (SRC / "dashboard.html").read_text()
    js = (SRC / "app.js").read_text()
    css = (SRC / "style.css").read_text()
    payload = json.dumps(data, separators=(",", ":"), default=str).replace("</", "<\\/")
    page = (
        tpl.replace("/*__CSS__*/", css)
        .replace(
            "/*__DATA__*/", f"window.HEAT={payload};window.HEAT_GEO={geo.replace('</', '<\\/')};"
        )
        .replace("/*__APP__*/", js)
    )
    if a.encrypt:
        pw = os.environ.get("PAGE_PASSWORD")
        if not pw:
            sys.exit("set PAGE_PASSWORD")
        (BUILD / "dashboard" / "page.enc").write_text(encrypt(page.encode(), pw))
        shutil.copy(SRC / "gate.html", BUILD / "dashboard" / "index.html")
    else:
        (BUILD / "dashboard" / "index.html").write_text(page)
    size = sum(p.stat().st_size for p in BUILD.rglob("*") if p.is_file())
    print(f"site/build: {size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
