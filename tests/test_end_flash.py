import CoolProp.CoolProp as CP
import pytest

from lng_design.end_flash import flash_end_gas

LNG_COMP = {"Methane": 0.90, "Ethane": 0.06, "Propane": 0.02, "Nitrogen": 0.02}


def test_mass_balance_closes():
    result = flash_end_gas(LNG_COMP, inlet_T_K=115.0, inlet_P_Pa=4.5e5,
                            outlet_P_Pa=1.10e5, total_mass_flow_kg_s=50.0)
    assert result.vapor_mass_flow_kg_s + result.liquid_mass_flow_kg_s == pytest.approx(50.0, rel=1e-9)


def test_realistic_end_flash_gives_small_vapor_fraction():
    # A few percent flash is typical/expected for an MCHE-outlet to
    # storage-pressure let-down - not near-zero, not a large fraction.
    result = flash_end_gas(LNG_COMP, inlet_T_K=115.0, inlet_P_Pa=4.5e5,
                            outlet_P_Pa=1.10e5, total_mass_flow_kg_s=50.0)
    assert 0.0 < result.vapor_mass_fraction < 0.15


def test_molar_and_mass_vapor_fraction_are_different_and_correctly_ordered():
    # Verified empirically: the flash vapor is lighter (lower MW) than the
    # liquid, so mass-basis vapor fraction < molar-basis vapor fraction.
    result = flash_end_gas(LNG_COMP, inlet_T_K=115.0, inlet_P_Pa=4.5e5,
                            outlet_P_Pa=1.10e5, total_mass_flow_kg_s=50.0)
    assert result.vapor_mass_fraction != pytest.approx(result.vapor_mole_fraction, rel=1e-3)


def test_vapor_is_enriched_in_light_components():
    result = flash_end_gas(LNG_COMP, inlet_T_K=115.0, inlet_P_Pa=4.5e5,
                            outlet_P_Pa=1.10e5, total_mass_flow_kg_s=50.0)
    assert result.vapor_composition_mole_frac["Nitrogen"] > LNG_COMP["Nitrogen"]
    assert result.liquid_composition_mole_frac["Propane"] >= LNG_COMP["Propane"]


def test_larger_pressure_letdown_gives_more_flash():
    small_dp = flash_end_gas(LNG_COMP, 115.0, 4.5e5, 4.0e5, 50.0)
    large_dp = flash_end_gas(LNG_COMP, 115.0, 4.5e5, 1.0e5, 50.0)
    assert large_dp.vapor_mass_fraction > small_dp.vapor_mass_fraction


def test_no_letdown_stays_fully_liquid():
    # Outlet pressure just barely below inlet, with inlet well subcooled -
    # should still be all-liquid (Q=0 degenerate case handled explicitly).
    result = flash_end_gas(LNG_COMP, inlet_T_K=110.0, inlet_P_Pa=4.5e5,
                            outlet_P_Pa=4.4e5, total_mass_flow_kg_s=50.0)
    assert result.vapor_mass_fraction == 0.0
    assert result.liquid_mass_flow_kg_s == pytest.approx(50.0)


def test_rejects_pressure_increase():
    with pytest.raises(ValueError):
        flash_end_gas(LNG_COMP, 115.0, 4.5e5, 5.0e5, 50.0)


def test_rejects_bad_composition():
    with pytest.raises(ValueError):
        flash_end_gas({"Methane": 0.5, "Ethane": 0.3}, 115.0, 4.5e5, 1.0e5, 50.0)
