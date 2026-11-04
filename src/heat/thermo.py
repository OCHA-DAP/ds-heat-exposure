"""Moist thermodynamics for the heat-stress indicators.

Inputs follow the CDS CMIP6 heat-stress indicators (sis-extreme-indices-cmip6): daily maximum
2 m temperature, daily mean specific humidity and surface pressure.

Wet-bulb temperature is the isobaric (psychrometric) wet-bulb temperature, solved by Newton
iteration of  cp·(T − Tw) = L(Tw)·(qs(Tw, p) − q).  See docs/DESIGN.md for why this rather than a
Davies-Jones (2008) port.
"""

import numpy as np

EPS = 0.622  # Rd / Rv
CPD = 1005.7  # J kg-1 K-1, dry air
CPV = 1860.0  # J kg-1 K-1, water vapour
T0 = 273.15


def sat_vapour_pressure(t_k):
    """Saturation vapour pressure over water (Pa), Bolton (1980). t_k in kelvin."""
    tc = t_k - T0
    return 611.2 * np.exp(17.67 * tc / (tc + 243.5))


def _d_es_dt(t_k, es):
    tc = t_k - T0
    return es * 17.67 * 243.5 / (tc + 243.5) ** 2


def specific_humidity_from_vp(e, p):
    """Specific humidity (kg/kg) from vapour pressure e (Pa) and pressure p (Pa)."""
    return EPS * e / (p - (1.0 - EPS) * e)


def specific_humidity_from_dewpoint(td_k, p):
    return specific_humidity_from_vp(sat_vapour_pressure(td_k), p)


def latent_heat(t_k):
    """Latent heat of vaporisation (J/kg), linear in temperature."""
    return 2.501e6 - 2370.0 * (t_k - T0)


def wet_bulb_temperature(t_k, q, p, n_iter=12):
    """Isobaric wet-bulb temperature (K).

    t_k: air temperature (K); q: specific humidity (kg/kg); p: pressure (Pa). Arrays broadcast.
    Supersaturated inputs (q > qs(T)) return T.
    """
    t_k = np.asarray(t_k, dtype=np.float64)
    q = np.asarray(q, dtype=np.float64)
    p = np.asarray(p, dtype=np.float64)
    q = np.minimum(q, specific_humidity_from_vp(sat_vapour_pressure(t_k), p))
    cp = CPD + q * CPV
    # first guess: one third of the way from T down to the dewpoint
    e = q * p / (EPS + (1.0 - EPS) * q)
    ln = np.log(np.maximum(e, 1e-3) / 611.2)
    td = T0 + 243.5 * ln / (17.67 - ln)
    tw = t_k - (t_k - td) / 3.0
    for _ in range(n_iter):
        es = sat_vapour_pressure(tw)
        denom = p - (1.0 - EPS) * es
        qs = EPS * es / denom
        lw = latent_heat(tw)
        f = cp * (t_k - tw) - lw * (qs - q)
        dqs = EPS * p / denom**2 * _d_es_dt(tw, es)
        df = -cp + 2370.0 * (qs - q) - lw * dqs
        tw = tw - f / df
        tw = np.minimum(tw, t_k)
    return tw


def wbgt_shade(t_k, tw_k):
    """Indoor / shade wet-bulb globe temperature (K): 0.7·Tw + 0.3·T (no sun, no wind),
    the definition used by the CDS CMIP6 heat-stress indicators."""
    return 0.7 * tw_k + 0.3 * t_k
