"""Per-cell annual heat metrics from daily ERA5 (or shifted ERA5) fields.

All daily inputs are (time, cell) arrays in °C; surface pressure is a (12, cell) monthly
climatology in Pa. Outputs are counts of days per cell (int16) for one year or window.
"""

from __future__ import annotations

import numpy as np

from heat import thermo

# metric -> (daily field, threshold °C). Strictly greater-than for Tmax (C3S Atlas TX35/TX40
# definition), greater-or-equal for the heat-stress thresholds.
COUNT_METRICS = {
    "tx35": ("tmax", 35.0, "gt"),
    "tx40": ("tmax", 40.0, "gt"),
    "wbgt30": ("wbgt", 30.0, "ge"),
    "wbgt32": ("wbgt", 32.0, "ge"),
    "wbt29": ("wbt", 29.0, "ge"),
    "wbt31": ("wbt", 31.0, "ge"),
}
HEATWAVE = "hw"
ALL_COUNTS = list(COUNT_METRICS) + [HEATWAVE]


def heat_stress(tmax_c, tdew_c, ps_pa, q_scale=None):
    """Daily WBT and WBGT (°C) from daily max temperature, daily mean dewpoint and pressure.

    q_scale: optional multiplicative change in specific humidity (same shape or broadcastable),
    used by the projection shift.
    """
    q = thermo.specific_humidity_from_dewpoint(tdew_c.astype(np.float64) + thermo.T0, ps_pa)
    if q_scale is not None:
        q = q * q_scale
    t_k = tmax_c.astype(np.float64) + thermo.T0
    wbt = thermo.wet_bulb_temperature(t_k, q, ps_pa) - thermo.T0
    wbgt = 0.7 * wbt + 0.3 * tmax_c
    return wbt.astype(np.float32), wbgt.astype(np.float32)


def month_index(times) -> np.ndarray:
    return (np.asarray(times).astype("datetime64[M]").astype(int) % 12).astype(np.int64)


def count_days(fields: dict, chunk_cells: int | None = None) -> dict:
    """fields: {'tmax': (t, cell), 'wbt': ..., 'wbgt': ...} -> {metric: (cell,) int16 counts}."""
    out = {}
    for m, (f, thr, op) in COUNT_METRICS.items():
        a = fields[f]
        hit = (a > thr) if op == "gt" else (a >= thr)
        out[m] = np.nansum(hit, axis=0).astype(np.int16)
    return out


def heatwave_flags(tmax, tmin, p95max, p95min):
    return (tmax > p95max[None, :]) & (tmin > p95min[None, :])


def heatwave_days(
    hot: np.ndarray, prev_last: np.ndarray | None = None, next_first: np.ndarray | None = None
) -> np.ndarray:
    """Days that belong to a run of >= 2 consecutive hot days (Lancet Countdown definition).

    hot: (t, cell) bool. prev_last / next_first: hot flag on the day before / after the period,
    so runs that cross a year boundary are counted.
    """
    z = np.zeros(hot.shape[1], dtype=bool)
    prev = np.vstack([(prev_last if prev_last is not None else z)[None, :], hot[:-1]])
    nxt = np.vstack([hot[1:], (next_first if next_first is not None else z)[None, :]])
    return (hot & (prev | nxt)).sum(axis=0).astype(np.int16)


def daily_fields(tmax, tdew, ps_clim, times, dtmax=None, dq_ratio=None, chunk=31):
    """Compute WBT / WBGT in month-sized slabs to keep memory small.

    dtmax / dq_ratio: optional (12, cell) monthly shifts for projections.
    Returns dict with tmax (shifted), wbt, wbgt as float32 (t, cell).
    """
    n_t, n_c = tmax.shape
    mi = month_index(times)
    wbt = np.empty((n_t, n_c), dtype=np.float32)
    wbgt = np.empty((n_t, n_c), dtype=np.float32)
    tmx = np.empty((n_t, n_c), dtype=np.float32)
    for t0 in range(0, n_t, chunk):
        sl = slice(t0, min(t0 + chunk, n_t))
        m = mi[sl]
        ps = ps_clim[m]
        tx = tmax[sl] + (dtmax[m] if dtmax is not None else 0.0)
        qs = dq_ratio[m] if dq_ratio is not None else None
        w, g = heat_stress(tx, tdew[sl], ps, q_scale=qs)
        wbt[sl], wbgt[sl], tmx[sl] = w, g, tx
    return {"tmax": tmx, "wbt": wbt, "wbgt": wbgt}
