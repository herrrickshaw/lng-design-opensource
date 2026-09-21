import math

import CoolProp.CoolProp as CP
import pytest

from lng_design.regas_terminal import (
    CP_SEAWATER_J_KG_K, heating_curve, lhv_MJ_per_kg, size_lng_pump, size_orv,
    size_recondenser, size_regas_train, size_scv, vaporizer_duty,
)
from lng_design.tank_bog import tank_liquid_state

LNG = {"Methane": 0.92, "Ethane": 0.05, "Propane": 0.015, "Nitrogen": 0.01, "n-Butane": 0.005}
P_TANK = 1.15e5


@pytest.fixture(scope="module")
def tank():
    return tank_liquid_state(LNG, P_TANK)


def test_lhv_methane_is_nist_value():
    assert lhv_MJ_per_kg({"Methane": 1.0}) == pytest.approx(50.0, rel=0.005)


def test_lhv_unknown_component_rejected():
    with pytest.raises(ValueError):
        lhv_MJ_per_kg({"Hexane": 1.0})


def test_pump_hydraulic_power_matches_incompressible_estimate(tank):
    m, P1, P2 = 100.0, 10e5, 85e5
    r = size_lng_pump(LNG, tank.temperature_K, P1, P2, m, efficiency=0.75)
    approx = m * (P2 - P1) / r.liquid_density_kg_m3 / 1000.0
    assert r.hydraulic_kW == pytest.approx(approx, rel=0.04)
    assert r.shaft_kW == pytest.approx(r.hydraulic_kW / 0.75, rel=1e-9)
    assert r.temperature_rise_K > 0                 # pump losses warm the LNG


@pytest.mark.parametrize("eff", [0.5, 0.7, 0.85])
@pytest.mark.parametrize("p_out_bar", [60.0, 85.0, 100.0])
def test_pump_hydraulic_power_tracks_incompressible_estimate_across_states(tank, eff, p_out_bar):
    """Regression for the CoolProp mixture-flash flake: with automatic phase
    detection, some (efficiency, pressure) combinations silently returned a
    hydraulic power ~24 % too high (an earlier worked-example run showed HP
    pump 3,240 kW hydraulic instead of 2,616) without raising. Sweeping the
    states catches a garbage point that a single test state can miss."""
    m, P1, P2 = 100.0, 10e5, p_out_bar * 1e5
    r = size_lng_pump(LNG, tank.temperature_K + 0.4, P1, P2, m, efficiency=eff)
    incompressible = m * (P2 - P1) / r.liquid_density_kg_m3 / 1000.0
    assert r.hydraulic_kW == pytest.approx(incompressible, rel=0.04)
    assert 0.5 < r.temperature_rise_K < 10.0


def test_pump_warming_falls_with_efficiency(tank):
    lo = size_lng_pump(LNG, tank.temperature_K, 10e5, 85e5, 100.0, 0.6)
    hi = size_lng_pump(LNG, tank.temperature_K, 10e5, 85e5, 100.0, 0.85)
    assert hi.temperature_rise_K < lo.temperature_rise_K


def test_pump_rejects_vapor_suction_and_bad_pressures():
    with pytest.raises(ValueError, match="sub-cooled"):
        size_lng_pump(LNG, 200.0, 3e5, 85e5, 10.0)
    with pytest.raises(ValueError):
        size_lng_pump(LNG, 110.0, 10e5, 5e5, 10.0)


def test_vaporizer_duty_in_expected_band_and_close_to_pure_methane(tank):
    d = vaporizer_duty(LNG, 85e5, 114.0, 278.15, 1.0)        # kJ/kg
    assert 650.0 < d < 950.0
    dm = (CP.PropsSI("H", "P", 85e5, "T", 278.15, "Methane")
          - CP.PropsSI("H", "P", 85e5, "T", 114.0, "Methane")) / 1000.0
    assert d == pytest.approx(dm, rel=0.08)


def test_heating_curve_is_monotone_and_ends_at_duty():
    T, Q = heating_curve(LNG, 85e5, 114.0, 278.15, 10.0, n_points=30)
    assert all(b > a for a, b in zip(Q, Q[1:]))
    assert Q[-1] == pytest.approx(vaporizer_duty(LNG, 85e5, 114.0, 278.15, 10.0), rel=1e-9)


def test_heating_curve_survives_coolprop_flake_at_136p435K():
    """Regression: CoolProp's mixture PT flash at exactly T=136.435 K, 85 bar
    returned h = -40,000 kJ/kg (found by running the Streamlit app, whose
    25-point curve from 116.19 K lands on that temperature)."""
    T, Q = heating_curve(LNG, 85e5, 116.19, 278.15, 158.44, n_points=25)
    assert all(b > a for a, b in zip(Q, Q[1:]))
    assert Q[-1] > 1e5      # ~111.7 MW, not a garbage value


def test_orv_seawater_and_units_closed_form():
    r = size_orv(duty_kW=112000.0, lng_flow_kg_s=158.0, seawater_in_C=20.0,
                 seawater_dT_K=5.0, unit_capacity_t_h=180.0)
    assert r.seawater_flow_t_h * 1000.0 / 3600.0 * CP_SEAWATER_J_KG_K * 5.0 == pytest.approx(112000e3, rel=1e-9)
    assert r.n_operating == math.ceil(158.0 * 3.6 / 180.0)
    assert r.seawater_outlet_C == 15.0 and r.usable


def test_orv_flagged_unusable_in_cold_water():
    r = size_orv(1e5, 150.0, seawater_in_C=3.0)
    assert not r.usable and "SCV" in r.note


def test_scv_fuel_fraction_is_low_single_digit_percent(tank):
    duty = vaporizer_duty(LNG, 85e5, 114.0, 278.15, 158.0)
    s = size_scv(duty, LNG, 158.0)
    assert 0.010 < s.fuel_fraction_of_sendout < 0.025
    assert s.fuel_gas_kg_s * lhv_MJ_per_kg(LNG) * 1000.0 * 0.98 == pytest.approx(duty, rel=1e-9)


def test_train_pieces_are_consistent(tank):
    r = size_regas_train(LNG, 158.0, P_TANK, tank.temperature_K, 10e5, 85e5)
    assert r.total_pump_shaft_kW == pytest.approx(r.lp_pump.shaft_kW + r.hp_pump.shaft_kW)
    assert r.hp_pump.hydraulic_kW > r.lp_pump.hydraulic_kW
    assert r.duty_kJ_per_kg == pytest.approx(r.duty_kW / 158.0)
    assert r.scv.duty_kW == r.orv.duty_kW == r.duty_kW


def test_recondenser_enthalpy_balance_closes(tank):
    bog = tank.bog_mole_fractions
    lng_T, bog_T, P = tank.temperature_K + 0.5, 240.0, 9e5
    r = size_recondenser(LNG, lng_T, bog, bog_T, 8.0, P, available_lng_kg_s=158.0)

    def h(comp, T):
        names = [n for n, x in comp.items() if x > 1e-12]
        s = CP.AbstractState("HEOS", "&".join(names))
        s.set_mole_fractions([comp[n] for n in names]); s.update(CP.PT_INPUTS, P, T)
        return s.hmass()

    lhs = 1.0 * h(bog, bog_T) + r.lng_to_bog_mass_ratio * h(LNG, lng_T)
    rhs = (1.0 + r.lng_to_bog_mass_ratio) * h(r.outlet_composition, r.outlet_T_K)
    assert lhs == pytest.approx(rhs, rel=1e-5)
    assert r.lng_required_kg_s == pytest.approx(r.lng_to_bog_mass_ratio * 8.0)


def test_recondenser_excess_bog_when_lng_flow_is_short(tank):
    bog = tank.bog_mole_fractions
    tight = size_recondenser(LNG, tank.temperature_K + 0.5, bog, 240.0, 30.0, 9e5, available_lng_kg_s=50.0)
    assert tight.excess_bog_kg_s > 0
    assert tight.recondensed_bog_kg_s == pytest.approx(tight.max_recondensable_bog_kg_s)
    ample = size_recondenser(LNG, tank.temperature_K + 0.5, bog, 240.0, 5.0, 9e5, available_lng_kg_s=150.0)
    assert ample.excess_bog_kg_s == 0.0


def test_colder_lng_needs_less_lng_per_kg_bog(tank):
    bog = tank.bog_mole_fractions
    warm = size_recondenser(LNG, tank.temperature_K + 8.0, bog, 240.0, 8.0, 9e5, 150.0)
    cold = size_recondenser(LNG, tank.temperature_K + 0.5, bog, 240.0, 8.0, 9e5, 150.0)
    assert cold.lng_to_bog_mass_ratio < warm.lng_to_bog_mass_ratio
