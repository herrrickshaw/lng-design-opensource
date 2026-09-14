import pytest

from lng_design.water_system import cooling_water_demand


def test_evaporation_matches_gpsa_rule_of_thumb_fraction():
    # GPSA rule: evaporation fraction of circulation = 0.00085 * delta_T_F
    result = cooling_water_demand(
        total_cooling_duty_kW=10000.0, supply_temp_C=30.0, return_temp_C=40.0,
    )
    delta_T_F = (40.0 - 30.0) * 9.0 / 5.0
    expected_fraction = 0.00085 * delta_T_F
    assert result.evaporation_m3_h == pytest.approx(
        expected_fraction * result.circulation_rate_m3_h, rel=1e-9
    )


def test_makeup_equals_sum_of_components():
    result = cooling_water_demand(10000.0, 30.0, 40.0)
    assert result.total_makeup_m3_h == pytest.approx(
        result.evaporation_m3_h + result.blowdown_m3_h + result.drift_m3_h, rel=1e-9
    )


def test_higher_cycles_of_concentration_reduces_blowdown():
    low_coc = cooling_water_demand(10000.0, 30.0, 40.0, cycles_of_concentration=3.0)
    high_coc = cooling_water_demand(10000.0, 30.0, 40.0, cycles_of_concentration=6.0)
    assert high_coc.blowdown_m3_h < low_coc.blowdown_m3_h


def test_rejects_non_physical_temperatures():
    with pytest.raises(ValueError):
        cooling_water_demand(10000.0, supply_temp_C=40.0, return_temp_C=30.0)


def test_rejects_cycles_at_or_below_one():
    with pytest.raises(ValueError):
        cooling_water_demand(10000.0, 30.0, 40.0, cycles_of_concentration=1.0)
