import numpy as np

from heat import thermo

P0 = 101325.0


def _q_from_rh(t_c, rh):
    e = rh / 100 * thermo.sat_vapour_pressure(t_c + thermo.T0)
    return thermo.specific_humidity_from_vp(e, P0)


def test_saturated_air_wet_bulb_equals_temperature():
    for t in (10.0, 25.0, 35.0):
        tw = thermo.wet_bulb_temperature(t + thermo.T0, _q_from_rh(t, 100), P0) - thermo.T0
        assert abs(tw - t) < 1e-3


def test_stull_reference_points():
    # Stull (2011) quotes 13.7 °C for T = 20 °C, RH = 50 % at sea level; his fit is good to ~0.3 °C.
    tw = thermo.wet_bulb_temperature(20 + thermo.T0, _q_from_rh(20, 50), P0) - thermo.T0
    assert abs(tw - 13.7) < 0.4


def test_psychrometric_table_values():
    # Standard psychrometric chart values at 101.325 kPa.
    cases = [(30, 50, 22.0), (35, 40, 24.4), (40, 30, 25.5), (35, 75, 31.1)]
    for t, rh, expected in cases:
        tw = thermo.wet_bulb_temperature(t + thermo.T0, _q_from_rh(t, rh), P0) - thermo.T0
        assert abs(tw - expected) < 0.4, (t, rh, tw, expected)


def test_monotonic_in_humidity_and_vectorised():
    t = np.full(5, 35 + thermo.T0)
    q = _q_from_rh(35, np.array([10, 30, 50, 70, 90]))
    tw = thermo.wet_bulb_temperature(t, q, P0)
    assert np.all(np.diff(tw) > 0)
    assert tw.shape == (5,)
