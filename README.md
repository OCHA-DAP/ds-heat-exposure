# ds-heat-exposure

A live version of the findings in **Extreme heat: Preparing for the heatwaves of the future**
(OCHA, IFRC and the Red Cross Red Crescent Climate Centre, October 2022), recomputed with current
data for three populations: everyone, people in countries with a current humanitarian plan (GHO), and
people in need in the current Humanitarian Needs and Response Plans (HNRPs), at the admin level the
plans publish.

**Site:** password-protected GitHub Pages (URL added on first deploy).

What it answers: how much dangerous heat do today's people in need face — in recent years (observed,
updated monthly) and at 1.5, 2 and 3 °C of global warming (people in need held at today's figures).
It does **not** project how many people will be in need.

Method, data sources and decisions: [docs/DESIGN.md](docs/DESIGN.md).

## Pipeline

| Step | Command | Output |
|---|---|---|
| C3S Atlas (CMIP6 monthly changes, ERA5 observed counts) | `uv run python scripts/fetch_atlas.py submit` then `collect` | `data/raw/atlas/` |
| ERA5 daily backfill (CDS queue; resumable) | `uv run python scripts/fetch_era5.py submit` then `collect` (`scripts/collect_loop.sh` polls) | `data/era5c/` (land cells, int16) |
| Population grids + PiN units/weights | `uv run python scripts/build_population.py grids` / `plans` | `data/pop/` |
| Observed metrics | `uv run python scripts/build_observed.py p95` then `years` | `data/metrics/obs/` |
| Projections at warming levels | `uv run python scripts/build_projections.py` | `data/metrics/proj/` |
| Exposure tables + site | `uv run python scripts/build_site.py` | `site/build/` |

`data/` is git-ignored. Copernicus credentials: `CDSAPI_KEY` (the same key works for CDS and EWDS; the
URL is set in code because `CDSAPI_URL` points at EWDS on the team machines).

Licences: ERA5 and the C3S Atlas are Copernicus (CC-BY); WorldPop CC-BY 4.0; HNRP data via the
[HNRP mirror](https://ocha-dap.github.io/ds-hnrp-mirror/) (OCHA HPC / HDX). The CDS CMIP6 heat-stress
indicators (CICERO licence) are deliberately not used.
