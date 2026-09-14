import CoolProp.CoolProp as CP
import pytest

from lng_design.nitrogen_system import size_purge, size_nitrogen_supply, size_ln2_vaporizer


def test_purge_volume_matches_manual_calc():
    result = size_purge(vessel_free_volume_m3=50.0, n_volume_exchanges=4.0)
    assert result.purge_volume_Nm3 == pytest.approx(200.0, rel=1e-9)


def test_nitrogen_supply_aggregates_blanketing_and_purge():
    result = size_nitrogen_supply(
        blanketing_flow_Nm3_h=20.0, purge_events_per_day=2.0,
        purge_volume_per_event_Nm3=200.0, design_margin=0.25,
    )
    expected_purge_h = (2.0 * 200.0) / 24.0
    assert result.total_demand_Nm3_h == pytest.approx(20.0 + expected_purge_h, rel=1e-9)
    assert result.generator_capacity_Nm3_h == pytest.approx(result.total_demand_Nm3_h * 1.25, rel=1e-9)


def test_ln2_vaporizer_duty_matches_independent_coolprop_calc():
    mdot, P = 0.5, 5e5
    result = size_ln2_vaporizer(mdot, supply_pressure_Pa=P)
    h_liq = CP.PropsSI("H", "P", P, "Q", 0, "Nitrogen")
    h_vap = CP.PropsSI("H", "P", P, "Q", 1, "Nitrogen")
    expected_duty_kW = mdot * (h_vap - h_liq) / 1000.0
    assert result.vaporizer_duty_kW == pytest.approx(expected_duty_kW, rel=1e-9)
    assert result.latent_heat_J_kg > 0


def test_ln2_vaporizer_duty_scales_with_flow():
    small = size_ln2_vaporizer(0.1)
    large = size_ln2_vaporizer(1.0)
    assert large.vaporizer_duty_kW == pytest.approx(10 * small.vaporizer_duty_kW, rel=1e-6)
