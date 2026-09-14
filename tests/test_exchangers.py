import pytest

from lng_design.exchangers import size_shell_and_tube, _lmtd_counter_current


def test_lmtd_equal_dT_reduces_to_that_value():
    # When dT1 == dT2, the log-mean is indeterminate (0/0) and the
    # correct limiting value is simply that common dT - the classic
    # textbook special case. dT1 = T_hot_in - T_cold_out = 350-330 = 20;
    # dT2 = T_hot_out - T_cold_in = 340-320 = 20.
    lmtd = _lmtd_counter_current(T_hot_in=350.0, T_hot_out=340.0, T_cold_in=320.0, T_cold_out=330.0)
    assert lmtd == pytest.approx(20.0, abs=1e-6)


def test_lmtd_rejects_temperature_crossing():
    with pytest.raises(ValueError):
        _lmtd_counter_current(T_hot_in=320.0, T_hot_out=310.0, T_cold_in=315.0, T_cold_out=305.0)


def test_area_matches_manual_QUA_calc():
    duty_kW, U, F = 500.0, 600.0, 0.9
    lmtd = _lmtd_counter_current(350.0, 320.0, 300.0, 315.0)
    expected_area = (duty_kW * 1000.0) / (U * F * lmtd)

    result = size_shell_and_tube(duty_kW, 350.0, 320.0, 300.0, 315.0, overall_U_W_m2K=U,
                                  lmtd_correction_factor_F=F)
    assert result.required_area_m2 == pytest.approx(expected_area, rel=1e-9)
    assert result.lmtd_K == pytest.approx(lmtd, rel=1e-9)


def test_standard_shell_size_covers_required_diameter():
    result = size_shell_and_tube(2000.0, 350.0, 320.0, 300.0, 315.0, overall_U_W_m2K=600.0)
    assert result.standard_shell_od_mm >= result.required_shell_diameter_m * 1000.0


def test_more_duty_needs_bigger_shell():
    small = size_shell_and_tube(200.0, 350.0, 320.0, 300.0, 315.0, overall_U_W_m2K=600.0)
    large = size_shell_and_tube(5000.0, 350.0, 320.0, 300.0, 315.0, overall_U_W_m2K=600.0)
    assert large.required_area_m2 > small.required_area_m2
    assert large.standard_shell_od_mm >= small.standard_shell_od_mm
