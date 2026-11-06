"""Admin polygons for people-in-need units, matched to COD-AB (HDX cloud mirror).

For each country plan we build "PiN units": polygons carrying a share of the national PiN.
- Units at the PiN admin level whose p-code matches COD-AB keep their own polygon.
- Unmatched units fall back to their admin-1 polygon (their PiN is pooled per admin 1).
- Anything still unmatched, and plans with no admin split, use the whole country (admin 0).
The match rate (share of PiN placed at its own level) is reported per country.
"""

from __future__ import annotations

import logging
import re
import warnings
from dataclasses import dataclass, field
from functools import cache

import geopandas as gpd
import pandas as pd

from heat.pin import AdminPin

logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore", message=".*CRS84.*")


def _name(g: gpd.GeoDataFrame, level: int) -> pd.Series:
    """First non-empty name column: some CODs (e.g. CMR) leave adm{n}_name empty and put the
    names in adm{n}_name1 (the second language)."""
    cols = [
        c
        for c in (f"adm{level}_name", f"adm{level}_name1", f"adm{level}_name2", f"adm{level}_name3",
                  f"adm{level}_ref_name1")
        if c in g.columns
    ]
    if not cols:
        raise KeyError(f"COD-AB has no adm{level}_name* column")
    out = g[cols[0]].copy()
    for c in cols[1:]:
        out = out.where(out.notna() & (out.astype(str).str.strip() != ""), g[c])
    return out


@cache
def codab(iso3: str, level: int) -> gpd.GeoDataFrame | None:
    """COD-AB polygons with columns pcode, name, parent_pcode (level-1), admin1_pcode."""
    import ocha_stratus as stratus

    g = stratus.codab.load_codab_from_hdx(iso3, level)
    if (g is None or g.empty) and level == 0:
        # e.g. CUB is not on the HDX COD-AB mirror; FieldMaps carries every country at admin 0
        g = stratus.codab.load_codab_from_fieldmaps(iso3, 0)
    if g is None or g.empty:
        return None
    g = g.to_crs("EPSG:4326")
    if level == 0:
        g = g[["geometry"]].dissolve().reset_index(drop=True)
        g["pcode"] = iso3
        g["name"] = iso3
        return g[["pcode", "name", "geometry"]]
    out = gpd.GeoDataFrame(
        {
            "pcode": g[f"adm{level}_pcode"].astype(str),
            "name": _name(g, level),
            "parent_pcode": g[f"adm{level - 1}_pcode"].astype(str) if level > 1 else iso3,
            "admin1_pcode": g["adm1_pcode"].astype(str),
        },
        geometry=g.geometry.values,
        crs=4326,
    )
    return out


def norm_name(name) -> str:
    import unicodedata

    if name is None or (isinstance(name, float) and pd.isna(name)):
        return ""
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)


def norm(code) -> str:
    if code is None or (isinstance(code, float) and pd.isna(code)):
        return ""
    return re.sub(r"[^A-Z0-9]", "", str(code).upper())


def _variants(code: str, iso2: str) -> list[str]:
    """Known p-code drifts between plan workbooks and COD-AB (see ds-hnrp-mirror audit):
    shortened country prefix (NER 'NE' vs 'NER'), dropped zero padding (COL)."""
    c = norm(code)
    out = [c]
    m = re.match(r"^([A-Z]+)(\d+)$", c)
    if m:
        prefix, digits = m.groups()
        for p in {prefix, iso2}:
            out += [p + digits, p + digits.zfill(len(digits) + 1), p + digits.lstrip("0")]
    return list(dict.fromkeys(out))


@dataclass
class PinUnits:
    iso3: str
    polygons: gpd.GeoDataFrame  # unit_id, level, pcode, name, pin, geometry
    matched_share: float  # share of PiN placed on its own admin level
    notes: list[str] = field(default_factory=list)


def _code_lookup(pcodes, iso2):
    lookup = {}
    for pc in pcodes:
        for v in _variants(pc, iso2):
            lookup.setdefault(v, pc)
    return lookup


def _find(code, lookup, iso2):
    return next((lookup[v] for v in _variants(code, iso2) if v in lookup), None)


COLS = ["unit_id", "level", "pcode", "name", "pin", "geometry"]


def pin_units(ap: AdminPin) -> PinUnits:
    """Place every admin PiN row on a polygon. Cascade per row:
    1. p-code at the PiN level (allowing known prefix / zero-padding drifts),
    2. same name within the same parent unit (e.g. COD health zones vs COD-AB codes),
    3. the parent polygon (level - 1), PiN pooled per parent,
    4. the admin-1 polygon, pooled,
    5. the whole country.
    """
    iso3 = ap.iso3
    adm0 = codab(iso3, 0)
    if adm0 is None:
        raise RuntimeError(f"no admin 0 boundary for {iso3}")
    if ap.table.empty:
        poly = adm0.assign(unit_id=iso3, level=0, pin=ap.national_pin)[COLS]
        return PinUnits(iso3, gpd.GeoDataFrame(poly, crs=4326), 0.0, ["no admin split: national"])

    lvl = ap.admin_level
    t = ap.table.copy()
    polys = codab(iso3, lvl)
    notes = []
    iso2 = norm(polys.pcode.iloc[0])[:2] if polys is not None and len(polys) else iso3[:2]
    t["target"] = None
    t["tlevel"] = None
    if polys is not None:
        lk = _code_lookup(polys.pcode, iso2)
        t["target"] = [_find(pc, lk, iso2) for pc in t.pcode]
        t.loc[t.target.notna(), "tlevel"] = lvl
        # 2. name within parent
        by_name = {}
        for pc, nm, par in zip(polys.pcode, polys.name, polys.parent_pcode):
            by_name.setdefault((norm(par), norm_name(nm)), pc)
            by_name.setdefault(("*", norm_name(nm)), pc)
        miss = t.target.isna()
        par_lk = _code_lookup(polys.parent_pcode.unique(), iso2)
        for i in t.index[miss]:
            par = _find(t.at[i, "parent_pcode"], par_lk, iso2) if t.at[i, "parent_pcode"] else None
            hit = by_name.get((norm(par), norm_name(t.at[i, "name"]))) if par else None
            if hit is not None:
                t.at[i, "target"], t.at[i, "tlevel"] = hit, lvl
        n_name = int(miss.sum() - t.target.isna().sum())
        if n_name:
            notes.append(f"{n_name} units matched by name within their parent")
    else:
        notes.append(f"no COD-AB admin {lvl}")
    matched_share = t.loc[t.target.notna(), "pin"].sum() / t.pin.sum()

    # 3-4. parent level, then admin 1
    for up in sorted({lvl - 1, 1}, reverse=True):
        miss = t.target.isna()
        if not miss.any() or up < 1:
            continue
        upp = codab(iso3, up)
        if upp is None:
            continue
        lk = _code_lookup(upp.pcode, iso2)
        col = "parent_pcode" if up == lvl - 1 else "admin1_pcode"
        for i in t.index[miss]:
            hit = _find(t.at[i, col], lk, iso2) if t.at[i, col] else None
            if hit is not None:
                t.at[i, "target"], t.at[i, "tlevel"] = hit, up
        n = int(miss.sum() - t.target.isna().sum())
        if n:
            notes.append(f"{n} units pooled to their admin-{up} polygon")

    rows = []
    for tl, grp in t[t.target.notna()].groupby("tlevel"):
        tl = int(tl)
        g = grp.groupby("target", as_index=False).pin.sum()
        g = codab(iso3, tl).merge(g, left_on="pcode", right_on="target")
        g["unit_id"] = g.pcode if tl == lvl else f"A{tl}:" + g.pcode
        g["level"] = tl
        rows.append(g[COLS])
    leftover = t.loc[t.target.isna(), "pin"].sum()
    if leftover > 0:
        rows.append(adm0.assign(unit_id=f"A0:{iso3}", level=0, pin=leftover)[COLS])
        names = ", ".join(t.loc[t.target.isna(), "name"].astype(str).head(3))
        notes.append(f"{leftover:,.0f} PiN ({names}) spread over the whole country")
    out = gpd.GeoDataFrame(pd.concat(rows, ignore_index=True), crs=4326)
    return PinUnits(iso3, out, float(matched_share), notes)
