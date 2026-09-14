"""Validate CoolProp-backed properties against published reference constants.

These are not internal-consistency checks - they compare against
independently published physical constants, so a regression here means the
underlying equation of state or fluid selection has actually broken.
"""
import CoolProp.CoolProp as CP
import pytest

from lng_design.properties import GasMixture


def test_propane_normal_boiling_point():
    # NIST WebBook / CRC Handbook: propane NBP = -42.1 C
    T = CP.PropsSI("T", "P", 101325, "Q", 0, "Propane") - 273.15
    assert T == pytest.approx(-42.1, abs=0.1)


def test_methane_critical_temperature():
    # NIST WebBook: methane Tc = -82.6 C (190.56 K)
    Tc = CP.PropsSI("Tcrit", "Methane") - 273.15
    assert Tc == pytest.approx(-82.6, abs=0.1)


def test_gas_mixture_molecular_weight_matches_component_average():
    mix = GasMixture({"Methane": 0.9, "Ethane": 0.1})
    mw_expected = 0.9 * 16.04246 + 0.1 * 30.06904  # published component MW (g/mol)
    assert mix.molecular_weight() == pytest.approx(mw_expected, rel=1e-3)


def test_mixture_composition_must_sum_to_one():
    with pytest.raises(ValueError):
        GasMixture({"Methane": 0.5, "Ethane": 0.4})
