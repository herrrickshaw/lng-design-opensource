import pytest

from lng_design.air_cooler import size_air_cooler
from lng_design.equipment_catalog import (
    STANDARD_AIR_COOLER_BAY_LENGTHS_M,
    STANDARD_AIR_COOLER_BAY_WIDTHS_M,
)


def test_air_mass_flow_matches_manual_calc():
    duty_kW, rise = 3000.0, 14.0
    result = size_air_cooler(duty_kW, design_ambient_T_C=35.0, air_temperature_rise_K=rise)
    expected_mdot = (duty_kW * 1000.0) / (1006.0 * rise)
    assert result.air_mass_flow_kg_s == pytest.approx(expected_mdot, rel=1e-9)


def test_selected_bay_dimensions_are_from_catalog():
    result = size_air_cooler(3000.0, design_ambient_T_C=35.0)
    assert result.bay_width_m in STANDARD_AIR_COOLER_BAY_WIDTHS_M
    assert result.bay_length_m in STANDARD_AIR_COOLER_BAY_LENGTHS_M


def test_selected_bays_cover_the_required_face_area():
    result = size_air_cooler(3000.0, design_ambient_T_C=35.0)
    assert result.n_bays * result.bay_width_m * result.bay_length_m >= result.required_face_area_m2


def test_larger_temperature_rise_needs_less_air_and_fewer_bays():
    small_rise = size_air_cooler(3000.0, design_ambient_T_C=35.0, air_temperature_rise_K=8.0)
    large_rise = size_air_cooler(3000.0, design_ambient_T_C=35.0, air_temperature_rise_K=20.0)
    assert large_rise.air_mass_flow_kg_s < small_rise.air_mass_flow_kg_s


def test_fan_power_positive_and_scales_with_bays():
    result = size_air_cooler(3000.0, design_ambient_T_C=35.0)
    assert result.fan_power_kW_per_bay > 0
    assert result.total_fan_power_kW == pytest.approx(
        result.fan_power_kW_per_bay * result.n_bays, rel=1e-9
    )
