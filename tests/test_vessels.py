import pytest

from lng_design.vessels import size_vertical_separator


def test_separator_sizing_runs_and_gives_sane_vessel():
    result = size_vertical_separator(
        gas_volumetric_flow_m3_s=2.0,
        gas_density_kg_m3=20.0,
        liquid_density_kg_m3=650.0,  # light hydrocarbon condensate
        liquid_volumetric_flow_m3_s=0.02,
    )
    assert result.standard_diameter_mm >= result.required_diameter_m * 1000.0
    assert result.vapor_velocity_design_m_s < result.vapor_velocity_max_m_s
    assert result.seam_to_seam_height_m > 0
    assert result.liquid_holdup_volume_m3 > 0


def test_standard_diameter_is_from_the_catalog():
    from lng_design.equipment_catalog import STANDARD_VESSEL_DIAMETERS_MM
    result = size_vertical_separator(1.0, 20.0, 650.0, 0.01)
    assert result.standard_diameter_mm in STANDARD_VESSEL_DIAMETERS_MM


def test_higher_gas_flow_needs_larger_vessel():
    small = size_vertical_separator(0.5, 20.0, 650.0, 0.01)
    large = size_vertical_separator(5.0, 20.0, 650.0, 0.01)
    assert large.required_diameter_m > small.required_diameter_m


def test_longer_residence_time_increases_height():
    short = size_vertical_separator(1.0, 20.0, 650.0, 0.01, liquid_residence_time_min=3.0)
    long = size_vertical_separator(1.0, 20.0, 650.0, 0.01, liquid_residence_time_min=10.0)
    assert long.seam_to_seam_height_m > short.seam_to_seam_height_m
