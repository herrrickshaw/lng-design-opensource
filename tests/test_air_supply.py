import pytest

from lng_design.air_supply import size_instrument_air_system


def test_average_demand_matches_manual_calc():
    n, per_inst, div = 400, 0.85, 0.6
    result = size_instrument_air_system(n, avg_consumption_Nm3_h_per_instrument=per_inst, diversity_factor=div)
    assert result.average_demand_Nm3_h == pytest.approx(n * per_inst * div, rel=1e-9)


def test_compressor_capacity_includes_margin():
    result = size_instrument_air_system(400, design_margin=0.3)
    assert result.compressor_capacity_Nm3_h == pytest.approx(result.average_demand_Nm3_h * 1.3, rel=1e-9)


def test_receiver_volume_scales_with_demand_and_minutes():
    small = size_instrument_air_system(400, receiver_minutes=5.0)
    large = size_instrument_air_system(400, receiver_minutes=15.0)
    assert large.receiver_volume_m3 == pytest.approx(3 * small.receiver_volume_m3, rel=1e-9)


def test_more_instruments_needs_more_air():
    small = size_instrument_air_system(100)
    large = size_instrument_air_system(1000)
    assert large.average_demand_Nm3_h > small.average_demand_Nm3_h
