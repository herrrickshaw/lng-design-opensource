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


def test_ideal_gas_limit_for_methane():
    # rho = P M / (R T) = 1e5 x 0.016043 / (8.314462618 x 300) = 0.64318 kg/m3 (Z ~ 0.998)
    m = GasMixture({"Methane": 1.0})
    assert m.density(300.0, 1e5) == pytest.approx(0.64318, rel=3e-3)
    assert m.compressibility(300.0, 1e5) == pytest.approx(1.0, abs=3e-3)


def test_methane_Z_close_to_hand_peng_robinson():
    # PR by hand: Tc 190.564 K, Pc 45.992 bar, w 0.01142, 250 K / 50 bar
    # kappa = 0.39222, alpha = 0.57938 -> A = 0.25683, B = 0.064472
    # largest root of Z^3 - (1-B)Z^2 + (A-3B^2-2B)Z - (AB-B^2-B^3) = 0.81177
    # (PR under-predicts methane Z by ~1-2 % vs. a reference EOS)
    z = GasMixture({"Methane": 1.0}).compressibility(250.0, 50e5)
    assert z == pytest.approx(0.81177, rel=0.03)


LEAN_NG = {"Methane": 0.85, "Ethane": 0.08, "Propane": 0.04, "Nitrogen": 0.03}


@pytest.mark.parametrize("P_bar,T_K", [(90.0, 150.0), (95.0, 140.0)])
def test_dense_lng_density_has_no_isolated_flash_garbage(P_bar, T_K):
    """Compressed LNG well above its cricondenbar: density must fall smoothly with T.

    CoolProp's unconstrained HEOS (T, P) mixture flash returns a spurious
    'gas' root at isolated points here (e.g. 151.6 kg/m3 at 90 bar / 150 K,
    where its neighbours 5 K either side are ~433 and ~418 kg/m3).
    """
    g = GasMixture(LEAN_NG)
    P = P_bar * 1e5
    lo, mid, hi = (g.density(T_K - 5.0, P), g.density(T_K, P), g.density(T_K + 5.0, P))
    assert lo > mid > hi
    assert mid > 380.0
