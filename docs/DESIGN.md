# ds-heat-exposure — design

A live version of the findings in **"Extreme heat: Preparing for the heatwaves of the future"**
(OCHA, IFRC and the Red Cross Red Crescent Climate Centre, October 2022, researched and written by
Greg Puley), recomputed with current data and applied to three populations:

1. everyone (global population),
2. people living in countries with a current humanitarian plan (GHO countries),
3. people in need in the current HNRPs, at the admin level the plans publish.

## What the report claims, and what we recompute

The report is a literature review. Its numbers come from other studies. We rebuild each one from
open data with a method we can run every month.

| Report finding | Source study | Our live metric | Observed | Projected |
|---|---|---|---|---|
| Deadly heat days (temperature + humidity) | Mora et al. 2017 | Days with wet-bulb globe temperature ≥ 32 °C (shade) and days with wet-bulb temperature ≥ 31 °C. Mora's own threshold curve is not published in a reusable form; these are the stand-ins, named as such on the site. | ERA5 daily | ERA5 1995–2014 daily shifted by the CMIP6 monthly change in Tmax and specific humidity (C3S Atlas) |
| Heatwave exposure of over-65s and infants | Lancet Countdown | Heatwave days (≥ 2 consecutive days with both daily max and daily min above the 1986–2005 95th percentile) × people aged 65+ and under 1 | ERA5 daily | ERA5 1995–2014 daily shifted by the CMIP6 monthly change in Tmax/Tmin (C3S Atlas) |
| Very hot days | IPCC AR6, general | Days with Tmax > 35 °C and > 40 °C | ERA5 daily | ERA5 1995–2014 daily shifted by the CMIP6 monthly change in Tmax (C3S Atlas); cross-checked against the Atlas's ISIMIP bias-adjusted CMIP6 counts |
| Unprecedented heat / human climate niche | Xu et al. 2020 (Lenton et al. 2023 update) | People living where the annual mean temperature is ≥ 29 °C | ERA5 daily mean | ERA5 1995–2014 annual mean + CMIP6 change (C3S Atlas) |
| A 1-in-50-year heat extreme is 4.8× as frequent now, 13.9× at 2 °C | IPCC AR6 SPM.6 | IPCC table, read at the latest observed warming level | Indicators of Global Climate Change, yearly | — (the IPCC table itself) |

### Projections
- **Global warming levels** 1.5, 2 and 3 °C above 1850–1900, IPCC AR6 method: for each model, the
  20-year window centred on the year its global mean crosses the level (IPCC Atlas table
  `CMIP6_Atlas_WarmingLevels.csv`, SSP5-8.5 runs so every model reaches 3 °C).
- **Reference period 1995–2014** (IPCC AR6 "recent past"). Every daily metric is projected the same
  way: take ERA5's observed days for 1995–2014, add the CMIP6 model-median monthly change between the
  reference window and the warming-level window (Tmax, Tmin and daily mean temperature additively,
  specific humidity as a ratio), regridded from the Atlas's 1° grid to 0.25°, and recount. This keeps
  ERA5's spatial detail and day-to-day weather, removes model bias, and uses one method for all
  metrics. It does not capture changes in day-to-day variability (IPCC: the hottest days warm a little
  faster than the mean in many regions), so it is likely to understate extremes somewhat; the
  hot-day cross-check against the Atlas's ISIMIP-adjusted counts measures by how much.
- **No CICERO-licensed data** (decision 2026-11-04): the CDS CMIP6 heat-stress indicators
  (`sis-extreme-indices-cmip6`) need a licence limited to non-commercial research with prompt open
  publication, which does not fit this dashboard. Everything used is under the standard Copernicus
  licence (CC-BY).
- **Population and people in need are held fixed** at today's figures. The projections answer
  "how much heat would today's people in need face at 2 °C", not "how many people will be in need".
  Projections do not refresh; only the people counted under them do.

### Populations
- **Grid:** WorldPop R2025A 1 km constrained global mosaic, 2026 (total; age bands 0–1, 65+).
- **Countries:** GHO = countries with a current country plan (HNRP or flash appeal) in the HPC data.
  Regional refugee plans are excluded from the country view (they cover people across several host
  countries, with no consistent admin split).
- **People in need:** intersectoral PiN from the HNRP mirror's public export
  (`ocha-dap.github.io/ds-hnrp-mirror/data/`), admin 1–3 as published. Within each admin unit PiN is
  spread like the WorldPop population. For each country the most recent plan year with published
  admin PiN is used; national PiN only where no admin PiN exists.
- **Age share for PiN:** PiN aged 65+ / under 1 = PiN × the WorldPop age share in that admin unit.

### Exposure measures (for every metric × population)
- **Person-days:** Σ people × days above the threshold, per year.
- **People exposed:** people living where the metric reaches at least N days a year (N = 1, 10, 30),
  or where the annual mean is ≥ 29 °C.
- **Mean days per person.**

### Refresh cadence
| Input | Cadence |
|---|---|
| ERA5 daily (CDS) | monthly, ~6 days behind real time; the current year is shown as year-to-date |
| People in need | daily mirror; we rebuild weekly |
| Current warming level | yearly (Indicators of Global Climate Change) |
| WorldPop | yearly release |
| CMIP6 changes (C3S Atlas) | fixed; the CMIP6 change fields are archived on our blob |

## Wet-bulb temperature
Isobaric wet-bulb temperature, solved by Newton iteration of the psychrometric equation
`cp·(T − Tw) = L(Tw)·(qs(Tw, p) − q)` with Bolton (1980) saturation vapour pressure. Inputs follow the
CDS heat-stress indicators: daily maximum 2 m temperature, daily mean specific humidity (from daily mean
2 m dewpoint) and surface pressure. WBGT (shade) = 0.7·WBT + 0.3·Tmax, as in the CDS dataset.
We do not vendor the Davies-Jones (2008) implementations in circulation (AGPL licence, and several
contain known bugs); the isobaric solution differs from DJ08 by a few tenths of a degree.

## Calibration checks
- Lancet Countdown: over-65s and infants faced ~3.7 billion more heatwave person-days in 2020 than the
  1986–2005 average. Our ERA5 + WorldPop recomputation should land within ~2× of this.
- Lenton et al. 2023: ~60 million people live where the annual mean is ≥ 29 °C today.
- IPCC SPM.6 values are copied, not recomputed.
