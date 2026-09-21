import pytest

from lng_design.lpg_terminal import (
    LPGTerminalBasis, size_bog_reliquefaction, size_import_storage, size_lpg_heater,
    size_lpg_import_terminal, vapor_pressure_Pa,
)
from lng_design.precool import propane_cycle_power
from lng_design.tank_bog import tank_liquid_state

import CoolProp.CoolProp as CP

PROPANE = {"Propane": 1.0}


@pytest.fixture(scope="module")
def base():
    return size_lpg_import_terminal()


def test_propane_vapor_pressure_matches_pure_fluid_value():
    assert vapor_pressure_Pa(PROPANE, 313.15) == pytest.approx(CP.PropsSI("P", "T", 313.15, "Q", 0, "Propane"), rel=1e-6)
    # widely tabulated: propane ~13.7 bar at 40 C
    assert vapor_pressure_Pa(PROPANE, 313.15) / 1e5 == pytest.approx(13.7, rel=0.02)


def test_refrigerated_tank_temperatures_are_the_textbook_values():
    assert tank_liquid_state(PROPANE, 1.01325e5).temperature_K - 273.15 == pytest.approx(-42.1, abs=0.3)
    assert tank_liquid_state({"n-Butane": 1.0}, 1.01325e5).temperature_K - 273.15 == pytest.approx(-0.5, abs=0.3)


def test_butane_needs_far_lower_condensing_pressure_than_propane():
    assert vapor_pressure_Pa({"n-Butane": 1.0}, 318.15) < 0.35 * vapor_pressure_Pa(PROPANE, 318.15)


def test_storage_is_one_cargo_plus_contingency_plus_heel():
    s = size_import_storage(throughput_kg_s=31.7, liquid_density_kg_m3=580.0, cargo_m3=84000.0,
                            contingency_days=5.0, heel_fraction=0.10, n_tanks=2)
    daily = 31.7 * 86400 / 580.0
    assert s.contingency_m3 == pytest.approx(5 * daily)
    assert s.net_volume_m3 == pytest.approx((84000.0 + 5 * daily) / 0.9)
    assert s.heel_m3 == pytest.approx(0.10 * s.net_volume_m3)
    assert s.per_tank_m3 * 2 == pytest.approx(s.net_volume_m3)
    with pytest.raises(ValueError):
        size_import_storage(31.7, 580.0, 84000.0, heel_fraction=0.6)


def test_reliquefaction_flow_equals_the_propane_refrigeration_cycle():
    """Independent check: for pure propane the compress-condense-return loop
    IS a propane refrigeration cycle with the tank as evaporator, so the
    compressed mass flow must equal precool.propane_cycle_power's."""
    st = tank_liquid_state(PROPANE, 1.10e5)
    r = size_bog_reliquefaction(st, 2.0, condensing_T_K=318.15, interstage_cooling_to_K=None, margin=0.0)
    cyc = propane_cycle_power(r.heat_load_removed_kW, st.temperature_K, 318.15, 0.75)
    assert r.compressed_flow_kg_s == pytest.approx(cyc.refrigerant_mass_flow_kg_s, rel=0.01)
    assert r.condensing_P_Pa == pytest.approx(cyc.P_cond_Pa, rel=0.01)
    # 3-stage polytropic (0.78) without inter-cooling vs 1-stage isentropic (0.75)
    assert r.compressor.gas_power_kW_per_machine == pytest.approx(cyc.compressor_power_kW, rel=0.20)


def test_flash_fraction_is_about_half_for_propane_at_45C():
    st = tank_liquid_state(PROPANE, 1.10e5)
    r = size_bog_reliquefaction(st, 2.0)
    assert 0.40 < r.flash_fraction < 0.60
    assert r.recycle_factor == pytest.approx(1.0 / (1.0 - r.flash_fraction))
    assert r.compressed_flow_kg_s == pytest.approx(2.0 * r.recycle_factor)


def test_subcooling_cuts_flash_and_compressor_load_and_costs_a_subcooler():
    st = tank_liquid_state(PROPANE, 1.10e5)
    plain = size_bog_reliquefaction(st, 2.0)
    sub = size_bog_reliquefaction(st, 2.0, subcool_to_K=283.15)
    assert sub.flash_fraction < plain.flash_fraction
    assert sub.compressor.gas_power_kW_per_machine < plain.compressor.gas_power_kW_per_machine
    assert plain.subcooler_duty_kW == 0.0 and sub.subcooler_duty_kW > 0.0
    with pytest.raises(ValueError):
        size_bog_reliquefaction(st, 2.0, subcool_to_K=320.0)


def test_heat_rejection_is_compressor_work_plus_tank_load():
    st = tank_liquid_state(PROPANE, 1.10e5)
    r = size_bog_reliquefaction(st, 2.0, margin=0.0)
    assert r.total_heat_rejection_kW == pytest.approx(
        r.compressor.gas_power_kW_per_machine + r.bog_kg_s * st.latent_heat_J_kg / 1000.0, rel=1e-9)


def test_hot_condensing_pressure_is_flagged():
    st = tank_liquid_state(PROPANE, 1.10e5)
    r = size_bog_reliquefaction(st, 2.0, condensing_T_K=345.0)
    assert any("exceeds" in n for n in r.notes)


def test_heater_duty_is_sensible_and_flags_ice_risk_for_cold_product():
    h = size_lpg_heater(PROPANE, 20e5, 235.0, 278.15, 100.0)
    # ~ cp 2.3-2.6 kJ/kg-K x 43 K
    assert 9000.0 < h.duty_kW < 12000.0
    assert h.medium_flow_t_h * 1000 / 3600 * 3990.0 * h.medium_dT_K == pytest.approx(h.duty_kW * 1000, rel=1e-9)
    assert "glycol" in h.note
    assert size_lpg_heater(PROPANE, 20e5, 285.0, 300.0, 100.0).note == "OK"


def test_terminal_defaults_are_self_consistent(base):
    assert base.throughput_kg_s == pytest.approx(1e9 / (365.25 * 24 * 3600))
    assert base.tank_state.temperature_K - 273.15 == pytest.approx(-39.2, abs=1.0)   # 95/5 propane/butane at 1.1 bar
    assert base.bog_design.design_bog_kg_s > base.bog_holding.design_bog_kg_s
    assert base.reliquefaction.bog_kg_s == base.bog_design.design_bog_kg_s
    assert base.storage.net_volume_m3 > base.basis.cargo_m3
    assert base.installed_power_kW == pytest.approx(
        base.pump.shaft_kW + base.reliquefaction.compressor.installed_shaft_power_kW)
    assert base.pump.hydraulic_kW == pytest.approx(
        base.throughput_kg_s * (base.basis.delivery_pressure_Pa - base.basis.tank_pressure_Pa
                                - base.basis.tank_liquid_head_Pa) / base.tank_state.liquid_density_kg_m3 / 1000.0,
        rel=0.05)


def test_lpg_boil_off_is_smaller_than_lng_per_tank_volume(base):
    """~80 K vs ~195 K driving temperature difference and thinner insulation."""
    assert base.bog_holding.heat_ingress_kW / base.bog_holding.inventory_kg < 5e-3   # kW per kg of inventory
    assert base.bog_holding.boil_off_rate_static_percent_per_day < 0.15


def test_disclosed_conditions_appear_in_notes(base):
    assert any("glycol" in n for n in base.notes)


def test_vapor_return_reduces_design_bog_and_reliquefaction_load():
    hi = size_lpg_import_terminal(LPGTerminalBasis(vapor_return_fraction=1.0))
    lo = size_lpg_import_terminal(LPGTerminalBasis(vapor_return_fraction=0.0))
    assert hi.bog_design.design_bog_kg_s < lo.bog_design.design_bog_kg_s
    assert hi.reliquefaction.compressor.gas_power_kW_per_machine < lo.reliquefaction.compressor.gas_power_kW_per_machine


def test_butane_terminal_needs_a_much_smaller_reliquefaction_loop():
    but = size_lpg_import_terminal(LPGTerminalBasis(
        composition={"n-Butane": 0.9, "Isobutane": 0.1}, condensing_T_K=318.15))
    assert but.tank_state.temperature_K > 265.0          # butane is stored near 0 C, not -40 C
    assert but.reliquefaction.condensing_P_Pa < 6e5
    assert but.reliquefaction.compressor.n_stages <= 2
