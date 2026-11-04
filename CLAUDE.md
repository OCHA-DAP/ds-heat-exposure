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

## Data plumbing
- CDS: `heat.cds_jobs.JobBook` keeps request ids in `data/state/*.json`; `collect` is resumable.
  `CDSAPI_URL` on the team machines points at EWDS — the code sets the CDS URL explicitly.
- ERA5 compact store `data/era5c/{var}/{var}_{year}.nc`: int16 hundredths of °C on land/populated
  cells (`cells.nc`). The current year's file is overwritten by each monthly refresh.
- PiN comes from the HNRP mirror's public export (`ocha-dap.github.io/ds-hnrp-mirror/data/`), JIAF
  admin PiN first; admin shares are rescaled to the plan's official national PiN.
- p-code matching cascade in `heat/zonal.py` (code → name within parent → parent → admin 1 → country).
  COD health zones match by name only.
