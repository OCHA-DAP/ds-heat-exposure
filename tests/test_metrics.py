import numpy as np

from heat import metrics


def test_heatwave_needs_two_consecutive_days():
    hot = np.array([[1, 0, 1], [0, 0, 1], [1, 1, 0], [1, 0, 1], [0, 0, 1]], dtype=bool)
    # cell0: single day, then a 2-day run -> 2; cell1: one day -> 0; cell2: runs of 2 and 2 -> 4
    assert metrics.heatwave_days(hot).tolist() == [2, 0, 4]


def test_heatwave_crosses_year_boundary():
    hot = np.array([[1, 0], [0, 0], [0, 1]], dtype=bool)
    prev_last = np.array([True, False])
    next_first = np.array([False, True])
    assert metrics.heatwave_days(hot, prev_last, next_first).tolist() == [1, 1]


def test_count_thresholds_strict_for_tmax():
    f = {
        "tmax": np.array([[35.0], [35.1], [40.0]], dtype=np.float32),
        "wbt": np.array([[31.0], [29.0], [20.0]], dtype=np.float32),
        "wbgt": np.array([[32.0], [30.0], [10.0]], dtype=np.float32),
    }
    c = metrics.count_days(f)
    assert c["tx35"][0] == 2 and c["tx40"][0] == 0
    assert c["wbt31"][0] == 1 and c["wbt29"][0] == 2
    assert c["wbgt32"][0] == 1 and c["wbgt30"][0] == 2


def test_daily_fields_shift_raises_wbt():
    times = np.array(["2000-07-01", "2000-07-02"], dtype="datetime64[D]")
    tmax = np.full((2, 1), 35.0, dtype=np.float32)
    tdew = np.full((2, 1), 22.0, dtype=np.float32)
    ps = np.full((12, 1), 100000.0)
    base = metrics.daily_fields(tmax, tdew, ps, times)
    shifted = metrics.daily_fields(
        tmax, tdew, ps, times, dtmax=np.full((12, 1), 2.0), dq_ratio=np.full((12, 1), 1.14)
    )
    assert np.all(shifted["wbt"] > base["wbt"] + 1.0)
    assert np.allclose(shifted["tmax"], 37.0)
