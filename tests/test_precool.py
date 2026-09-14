"""Validate the propane pre-cool cycle module.

test_matches_manual_cycle_calc cross-checks the module's output against an
independently hand-derived cycle calculation (not calling the module's own
internals) using the same CoolProp state points, so it exercises the
module as a black box.
"""
import CoolProp.CoolProp as CP
import pytest

from lng_design.precool import propane_cycle_power, optimal_evap_temperature


def test_matches_manual_cycle_calc():
    duty_kW, T_evap, T_cond, eta = 1000.0, 250.0, 313.15, 0.75

    h1 = CP.PropsSI("H", "T", T_evap, "Q", 1, "Propane")
    s1 = CP.PropsSI("S", "T", T_evap, "Q", 1, "Propane")
    P_cond = CP.PropsSI("P", "T", T_cond, "Q", 0, "Propane")
    h2s = CP.PropsSI("H", "P", P_cond, "S", s1, "Propane")
    h2 = h1 + (h2s - h1) / eta
    h3 = CP.PropsSI("H", "T", T_cond, "Q", 0, "Propane")
    mdot_expected = duty_kW * 1000.0 / (h1 - h3)
    power_expected = mdot_expected * (h2 - h1) / 1000.0

    result = propane_cycle_power(duty_kW, T_evap, T_cond, eta)
    assert result.compressor_power_kW == pytest.approx(power_expected, rel=1e-6)
    assert result.refrigerant_mass_flow_kg_s == pytest.approx(mdot_expected, rel=1e-6)


def test_cop_decreases_as_lift_increases():
    # Larger temperature lift (colder evap, same condenser) must reduce COP
    warm = propane_cycle_power(500.0, 260.0, 313.15)
    cold = propane_cycle_power(500.0, 230.0, 313.15)
    assert cold.cop < warm.cop


def test_optimal_evap_sits_at_mita_boundary_for_single_stage():
    # For a single evaporation level, power is monotonic in T_evap, so the
    # MITA-limited boundary is the true optimum (see precool.py docstring).
    mita = 3.0
    T_cold_target = 253.15
    result = optimal_evap_temperature(2000.0, T_cold_target, 313.15, mita_K=mita)
    assert result.T_evap_K == pytest.approx(T_cold_target - mita, abs=0.05)


def test_infeasible_mita_raises():
    # Propane's triple point is ~85.5 K, so a cold-end target of 80 K leaves
    # no valid evaporator temperature above the triple point once MITA is
    # subtracted - unambiguously infeasible for a single propane stage.
    with pytest.raises(ValueError):
        optimal_evap_temperature(1000.0, T_cold_end_target_K=80.0, T_cond_K=313.15, mita_K=3.0)
