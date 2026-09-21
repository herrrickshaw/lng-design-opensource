import math

import pytest

from lng_design.bog_compressor import size_bog_compressor, turndown_check
from lng_design.tank_bog import tank_liquid_state

LNG = {"Methane": 0.92, "Ethane": 0.05, "Propane": 0.015, "Nitrogen": 0.01, "n-Butane": 0.005}
BOG = tank_liquid_state(LNG, 1.15e5).bog_mole_fractions


def test_stage_count_follows_max_ratio():
    c = size_bog_compressor(BOG, 6.0, 1.10e5, 9e5, max_stage_ratio=2.5)
    assert c.n_stages == math.ceil(math.log(9e5 / 1.10e5) / math.log(2.5))
    assert c.stage_pressure_ratio ** c.n_stages == pytest.approx(9e5 / 1.10e5, rel=1e-9)
    assert c.stage_pressure_ratio <= 2.5 + 1e-9


def test_cold_suction_halves_power_versus_warm():
    """Head ~ T_in: -130 C vs +25 C suction, same mass flow and PR."""
    cold = size_bog_compressor(BOG, 6.0, 1.10e5, 9e5, suction_T_K=143.15)
    warm = size_bog_compressor(BOG, 6.0, 1.10e5, 9e5, suction_T_K=298.15)
    ratio = cold.gas_power_kW_per_machine / warm.gas_power_kW_per_machine
    assert ratio == pytest.approx(143.15 / 298.15, rel=0.10)


def test_power_scales_linearly_with_flow_and_margin():
    a = size_bog_compressor(BOG, 4.0, 1.10e5, 9e5, margin=0.0)
    b = size_bog_compressor(BOG, 8.0, 1.10e5, 9e5, margin=0.0)
    assert b.gas_power_kW_per_machine == pytest.approx(2 * a.gas_power_kW_per_machine, rel=1e-6)
    m = size_bog_compressor(BOG, 4.0, 1.10e5, 9e5, margin=0.10)
    assert m.design_flow_kg_s == pytest.approx(4.4)


def test_redundancy_splits_flow_and_installed_power():
    one = size_bog_compressor(BOG, 6.0, 1.10e5, 9e5, n_operating=1, n_spare=1)
    two = size_bog_compressor(BOG, 6.0, 1.10e5, 9e5, n_operating=2, n_spare=1)
    assert two.flow_per_machine_kg_s == pytest.approx(one.flow_per_machine_kg_s / 2)
    assert two.installed_shaft_power_kW == pytest.approx(3 * two.shaft_power_kW_per_machine)
    assert one.installed_shaft_power_kW == pytest.approx(2 * one.shaft_power_kW_per_machine)


def test_higher_discharge_pressure_needs_more_power_and_stages():
    lo = size_bog_compressor(BOG, 6.0, 1.10e5, 9e5)
    hi = size_bog_compressor(BOG, 6.0, 1.10e5, 80e5)
    assert hi.gas_power_kW_per_machine > lo.gas_power_kW_per_machine
    assert hi.n_stages > lo.n_stages


def test_nitrogen_rich_bog_is_lighter_than_lng():
    c = size_bog_compressor(BOG, 6.0, 1.10e5, 9e5)
    assert c.bog_molecular_weight_g_mol < 19.0


def test_dew_point_guard():
    with pytest.raises(ValueError, match="dew point"):
        size_bog_compressor(BOG, 6.0, 1.10e5, 9e5, suction_T_K=110.0)


def test_machine_note_small_flow_points_to_positive_displacement():
    small = size_bog_compressor(BOG, 0.3, 1.10e5, 9e5)
    assert small.frame is None and "reciprocating" in small.machine_note


def test_turndown_check():
    frac, ok = turndown_check(1.0, 6.0)
    assert frac == pytest.approx(1 / 6) and not ok
    assert turndown_check(4.0, 6.0)[1]


def test_input_validation():
    with pytest.raises(ValueError):
        size_bog_compressor(BOG, 6.0, 9e5, 1.1e5)
    with pytest.raises(ValueError):
        size_bog_compressor(BOG, 6.0, 1.1e5, 9e5, n_operating=0)
