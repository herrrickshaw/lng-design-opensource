import math

import CoolProp.CoolProp as CP
import pytest

from lng_design.tank_bog import (
    InsulationLayer, barometric_bog_kg_s, compute_bog, layer_U_W_m2K,
    pump_heat_kW, size_tank_geometry, tank_liquid_state,
)

LNG = {"Methane": 0.92, "Ethane": 0.05, "Propane": 0.015, "Nitrogen": 0.01, "n-Butane": 0.005}
P_TANK = 1.15e5


def test_geometry_volume_identity():
    g = size_tank_geometry(160000.0, height_to_diameter=0.4, vapor_space_height_m=2.0)
    assert math.pi / 4 * g.inner_diameter_m ** 2 * g.liquid_height_m == pytest.approx(160000.0, rel=1e-9)
    assert g.liquid_height_m / g.inner_diameter_m == pytest.approx(0.4)
    assert g.gross_volume_m3 > g.net_volume_m3


def test_layer_U_single_layer_closed_form():
    U = layer_U_W_m2K([InsulationLayer("x", 0.5, 0.05)], outer_film_W_m2K=10.0)
    assert U == pytest.approx(1.0 / (0.1 + 0.5 / 0.05), rel=1e-12)


def test_outer_film_choice_is_immaterial():
    layers = [InsulationLayer("perlite", 1.0, 0.045)]
    assert layer_U_W_m2K(layers, 10.0) == pytest.approx(layer_U_W_m2K(layers, 34.0), rel=0.01)


def test_latent_heat_matches_pure_fluid_route_for_methane():
    st = tank_liquid_state({"Methane": 1.0}, P_TANK)
    hfg = CP.PropsSI("H", "P", P_TANK, "Q", 1, "Methane") - CP.PropsSI("H", "P", P_TANK, "Q", 0, "Methane")
    assert st.latent_heat_J_kg == pytest.approx(hfg, rel=0.002)


def test_boil_off_gas_is_nitrogen_enriched():
    st = tank_liquid_state(LNG, P_TANK)
    assert st.bog_mole_fractions["Nitrogen"] > 15 * LNG["Nitrogen"]      # ~24x in practice
    assert st.bog_mole_fractions["Methane"] < 1.0
    assert sum(st.bog_mole_fractions.values()) == pytest.approx(1.0)
    assert st.bog_molecular_weight_g_mol < 19.0                          # lighter than the LNG


def test_static_bog_energy_identity_and_scaling():
    g = size_tank_geometry(160000.0)
    r1 = compute_bog(LNG, P_TANK, g, n_tanks=1)
    r2 = compute_bog(LNG, P_TANK, g, n_tanks=2)
    assert r1.static_bog_kg_s * r1.liquid_state.latent_heat_J_kg == pytest.approx(r1.heat_ingress_kW * 1000.0, rel=1e-9)
    assert r2.static_bog_kg_s == pytest.approx(2 * r1.static_bog_kg_s, rel=1e-9)


def test_default_stack_static_bor_is_in_the_published_order_of_magnitude():
    """0.05 %/day is the commonly quoted vendor figure for large tanks. A bare
    1-D estimate with the default (illustrative) insulation should land
    within a factor of ~2 of that, on the conservative side."""
    r = compute_bog(LNG, P_TANK, size_tank_geometry(160000.0))
    assert 0.03 < r.boil_off_rate_static_percent_per_day < 0.12


def test_thicker_insulation_lowers_bog():
    g = size_tank_geometry(160000.0)
    thin = compute_bog(LNG, P_TANK, g)
    thick = compute_bog(LNG, P_TANK, g, wall_layers=[InsulationLayer("p", 2.0, 0.045)])
    assert thick.static_bog_kg_s < thin.static_bog_kg_s


def test_pump_heat_is_input_minus_hydraulic():
    assert pump_heat_kW(500.0, 380.0) == pytest.approx(120.0)
    with pytest.raises(ValueError):
        pump_heat_kW(100.0, 200.0)


def test_pump_heat_adds_bog():
    g = size_tank_geometry(160000.0)
    base = compute_bog(LNG, P_TANK, g)
    hot = compute_bog(LNG, P_TANK, g, pump_heat_total_kW=200.0)
    st = base.liquid_state
    assert hot.pump_bog_kg_s == pytest.approx(200e3 / st.latent_heat_J_kg, rel=1e-9)
    assert hot.holding_bog_kg_s > base.holding_bog_kg_s


def test_barometric_zero_when_pressure_rises_and_linear_when_falling():
    st = tank_liquid_state(LNG, P_TANK)
    assert barometric_bog_kg_s(st, 7e7, 1e4, -50.0) == 0.0
    a = barometric_bog_kg_s(st, 7e7, 1e4, 50.0)
    b = barometric_bog_kg_s(st, 7e7, 1e4, 100.0)
    assert a > 0 and b == pytest.approx(2 * a, rel=1e-9)


def test_barometric_flash_matches_manual_sensible_heat_balance():
    st = tank_liquid_state(LNG, P_TANK)
    inv, dPdt = 7e7, 100.0 / 3600.0
    manual = inv * st.liquid_cp_J_kg_K * st.dTsat_dP_K_per_Pa * dPdt / st.latent_heat_J_kg
    assert barometric_bog_kg_s(st, inv, 0.0, 100.0) == pytest.approx(manual, rel=1e-9)


def test_unloading_displacement_closed_form_and_vapor_return():
    g = size_tank_geometry(160000.0)
    r = compute_bog(LNG, P_TANK, g, n_tanks=2, unloading_rate_m3_h=12000.0)
    assert r.displacement_bog_kg_s == pytest.approx(12000.0 / 3600.0 * r.liquid_state.vapor_density_kg_m3, rel=1e-9)
    ret = compute_bog(LNG, P_TANK, g, n_tanks=2, unloading_rate_m3_h=12000.0, vapor_return_fraction=0.4)
    assert ret.displacement_bog_kg_s == pytest.approx(0.6 * r.displacement_bog_kg_s, rel=1e-9)
    assert r.unloading_bog_kg_s > r.holding_bog_kg_s
    assert r.design_mode == "unloading"


def test_holding_mode_has_no_displacement():
    r = compute_bog(LNG, P_TANK, size_tank_geometry(160000.0))
    assert r.displacement_bog_kg_s == 0.0 and r.design_mode == "holding"
    assert r.design_bog_kg_s == r.holding_bog_kg_s


def test_flash_on_arrival_only_when_warm():
    g = size_tank_geometry(160000.0)
    T = tank_liquid_state(LNG, P_TANK).temperature_K
    cold = compute_bog(LNG, P_TANK, g, unloading_rate_m3_h=12000.0, arriving_T_K=T - 5.0, arriving_P_Pa=3e5)
    warm = compute_bog(LNG, P_TANK, g, unloading_rate_m3_h=12000.0, arriving_T_K=T + 3.0, arriving_P_Pa=1.3e5)
    assert cold.flash_bog_kg_s == 0.0
    assert warm.flash_bog_kg_s > 0.0


def test_arrival_pressure_must_be_a_letdown():
    with pytest.raises(ValueError, match="let-down"):
        compute_bog(LNG, P_TANK, size_tank_geometry(1e5), unloading_rate_m3_h=1000.0,
                    arriving_T_K=111.0, arriving_P_Pa=P_TANK)


def test_input_validation():
    g = size_tank_geometry(1e5)
    with pytest.raises(ValueError):
        compute_bog(LNG, P_TANK, g, fill_fraction=0.0)
    with pytest.raises(ValueError):
        compute_bog(LNG, P_TANK, g, vapor_return_fraction=1.5)
    with pytest.raises(ValueError):
        compute_bog({"Methane": 0.5}, P_TANK, g)
