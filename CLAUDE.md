# ds-heat-exposure — notes for Claude

Live update of the 2022 OCHA–IFRC report *Extreme heat: Preparing for the heatwaves of the future*
(written by Greg Puley) applied to global population, GHO countries and current HNRP people in need.
Read `docs/DESIGN.md` first: it records the method and every user decision.

## Decisions that must not drift
- Framing: heat exposure of TODAY's people in need (PiN held fixed), observed + at 1.5/2/3 °C. Not a
  caseload projection.
- Projections shift ERA5 1995–2014 daily by CMIP6 monthly changes from the C3S Atlas. Never use the
  CDS `sis-extreme-indices-cmip6` heat-stress data (CICERO licence; user declined 2026-11-04).
- Site is password-gated (encrypted page) until OCHA's climate team has reviewed it.
- "Deadly heat days" in the report are Mora et al. 2017; our stand-ins are WBGT ≥ 32 °C and
  WBT ≥ 31 °C — say so wherever they are shown.
- Plain language on the site; no table/column names or raw codes in visible text.
- The site map uses the Equal Earth projection (UN General Assembly "Correct the Map" resolution,
  Sept 2026; user asked 2026-11-06), drawn with d3-geo, not Mercator web tiles. World outlines:
  `site/world.json` from `scripts/build_world.py` (FieldMaps admin 0, intl worldview, USGS coastlines).
  d3 is spherical: rings must be clockwise or a shape fills the whole globe (`fixWinding` in app.js).

## Data plumbing
- ERA5 daily data come from ARCO-ERA5 hourly (public Google Cloud zarr; `heat/arco.py`,
  `scripts/fetch_arco.py`), not the CDS: the CDS queue held single requests 8–20 h (user agreed
  2026-11-05). UTC-day max/min/mean of the 24 hours = the CDS daily-statistics product.
- The backfill and the build run on Databricks (`databricks.yml`, job `heat_exposure_backfill`,
  id 48618764487730, single-node Job Compute). Prod deploys are run by the user (`!`); compacted
  years go to the project blob as they finish, so a retry resumes. ~1.4 TB read: never on the laptop.
- Copernicus (still used for the one-off Atlas and static downloads): never more than 2 requests in
  flight (service protection measures; the key is shared with the team's flood monitoring).
- Shared copies in the team DEV `raster` container (`heat/shared.py`): ERA5 daily full-grid files
  `era5/daily/processed/` (ours, from ARCO), untouched downloads in `era5/static/raw/`,
  `era5/monthly/raw/`, `c3s_atlas/raw/`, `worldpop/age_structures/`. KB: `pipelines/heat-exposure.md`.
  Keep those paths stable — other projects read them.
- CDS: `heat.cds_jobs.JobBook` keeps request ids in `data/state/*.json`; `collect` is resumable.
  `CDSAPI_URL` on the team machines points at EWDS — the code sets the CDS URL explicitly.
- ERA5 compact store `data/era5c/{var}/{var}_{year}.nc`: int16 hundredths of °C on land/populated
  cells (`cells.nc`). The current year's file is overwritten by each monthly refresh.
- PiN comes from the HNRP mirror's public export (`ocha-dap.github.io/ds-hnrp-mirror/data/`), JIAF
  admin PiN first; admin shares are rescaled to the plan's official national PiN.
- p-code matching cascade in `heat/zonal.py` (code → name within parent → parent → admin 1 → country).
  COD health zones match by name only.
