import math

import CoolProp.CoolProp as CP
import pytest

from lng_design.fractionation import (
    ColumnSpec, fenske_min_stages, gilliland_molokanov_Y, gilliland_stages,
    kirkbride_ratio, oconnell_efficiency, size_column, size_fractionation_train,
    underwood_min_reflux,
)

NGL = {"Ethane": 320, "Propane": 300, "Isobutane": 60, "n-Butane": 100,
       "Isopentane": 50, "Pentane": 50, "Hexane": 40}


# ---- closed-form limits of the shortcut equations (no CoolProp) ----------

def test_fenske_matches_hand_calc():
    # alpha=2, 99 % / 99 % recoveries: N_min = ln(99*99)/ln(2)
    n = fenske_min_stages(d_lk=99, b_lk=1, d_hk=1, b_hk=99, alpha_lk_hk=2.0)
    assert n == pytest.approx(math.log(99 * 99) / math.log(2), rel=1e-12)


@pytest.mark.parametrize("alpha,xF,xD", [(2.5, 0.5, 0.99), (1.5, 0.4, 0.98), (4.0, 0.3, 0.995)])
def test_underwood_binary_reduces_to_closed_form(alpha, xF, xD):
    # Saturated-liquid binary feed: R_min = [xD/xF - a(1-xD)/(1-xF)] / (a-1)
    closed = (xD / xF - alpha * (1 - xD) / (1 - xF)) / (alpha - 1)
    rmin, theta = underwood_min_reflux(
        {"L": alpha, "H": 1.0}, {"L": xF, "H": 1 - xF}, {"L": xD, "H": 1 - xD}, 1.0, "L", "H")
    assert rmin == pytest.approx(closed, rel=1e-9)
    assert 1.0 < theta < alpha


def test_gilliland_limits():
    assert gilliland_molokanov_Y(0.0) == 1.0        # R = R_min -> infinite stages
    assert gilliland_molokanov_Y(1.0) == 0.0        # R = inf  -> N_min
    assert gilliland_stages(10.0, r=1e6, r_min=1.0) == pytest.approx(10.0, rel=1e-3)
    assert gilliland_stages(10.0, r=1.0000001, r_min=1.0) > 1e3
    ys = [gilliland_molokanov_Y(x / 10) for x in range(1, 10)]
    assert ys == sorted(ys, reverse=True)           # monotone decreasing


def _mccabe_thiele_stages(alpha, xF, xD, xB, R):
    """Independent exact stage stepping: ideal binary, constant molar
    overflow, saturated-liquid feed, total condenser; count includes the
    reboiler stage (same convention as N_theoretical)."""
    D = (xF - xB) / (xD - xB); B = 1 - D
    L = R * D; V = L + D; Lb = L + 1.0; Vb = Lb - B
    y, n = xD, 0
    while n < 500:
        x = y / (alpha - (alpha - 1) * y)
        n += 1
        if x <= xB:
            return n
        y = (L * x + D * xD) / V if x > xF else (Lb * x - B * xB) / Vb
    raise AssertionError


@pytest.mark.parametrize("alpha,xF,xD,xB,f", [
    (2.5, 0.5, 0.99, 0.01, 1.2), (2.5, 0.5, 0.99, 0.01, 1.5),
    (1.5, 0.4, 0.98, 0.02, 1.3), (4.0, 0.3, 0.995, 0.005, 1.2),
])
def test_fug_stage_count_within_15pct_of_exact_stepping(alpha, xF, xD, xB, f):
    rmin = (xD / xF - alpha * (1 - xD) / (1 - xF)) / (alpha - 1)
    nmin = math.log((xD / (1 - xD)) * ((1 - xB) / xB)) / math.log(alpha)
    n_fug = gilliland_stages(nmin, f * rmin, rmin)
    n_exact = _mccabe_thiele_stages(alpha, xF, xD, xB, f * rmin)
    assert abs(n_fug - n_exact) / n_exact < 0.15


def test_kirkbride_symmetric_case_is_unity():
    assert kirkbride_ratio(0.5, 0.5, 1.0, 1.0, 0.01, 0.01) == pytest.approx(1.0)


def test_oconnell_lower_for_viscous_liquid():
    assert oconnell_efficiency(0.05, 2.0) > oconnell_efficiency(0.5, 2.0)


# ---- CoolProp-integrated columns and train -------------------------------

@pytest.fixture(scope="module")
def train():
    specs = [
        ColumnSpec("deethanizer", "Ethane", "Propane", 26e5, 0.98, 0.995),
        ColumnSpec("depropanizer", "Propane", "Isobutane", 17e5, 0.985, 0.98),
        ColumnSpec("debutanizer", "n-Butane", "Isopentane", 6e5, 0.98, 0.98),
    ]
    return size_fractionation_train(NGL, specs)


def test_train_closes_mole_balance(train):
    assert train.mass_balance_error < 1e-9


def test_key_recoveries_are_honored(train):
    de = train.columns[0]
    assert de.distillate_kmol_h["Ethane"] == pytest.approx(0.98 * NGL["Ethane"], rel=1e-9)
    assert de.bottoms_kmol_h["Propane"] == pytest.approx(0.995 * NGL["Propane"], rel=1e-9)


def test_stage_counts_are_ordered_and_sane(train):
    for c in train.columns:
        assert c.N_min < c.N_theoretical < 200
        assert c.R > c.R_min > 0
        assert c.N_real >= c.N_theoretical - 1
        assert 1 <= c.feed_tray_from_top < c.N_real
        assert c.P_bottom_Pa > c.P_top_Pa
        assert c.T_bottom_K > c.T_top_K


def test_deethanizer_condenser_needs_refrigeration_and_says_why(train):
    de = train.columns[0]
    assert "refrigerated" in de.condenser_service
    # Ethane's critical temperature (305 K) is below 318 K air/CW-plus-approach
    assert de.min_pressure_for_cooling_water_Pa is None
    assert any("critical" in n for n in de.notes)


def test_debutanizer_condenser_is_water_or_air_cooled(train):
    assert "cooling" in train.columns[2].condenser_service


def test_condenser_duty_matches_pure_component_latent_heat(train):
    """Deethanizer distillate is ~99.5 % ethane, so Q_c ~ V x h_fg(ethane)
    at the top temperature - an independent pure-fluid CoolProp route."""
    de = train.columns[0]
    D = sum(de.distillate_kmol_h.values())
    V = D * (de.R + 1.0)
    hfg = (CP.PropsSI("Hmolar", "T", de.T_top_K, "Q", 1, "Ethane")
           - CP.PropsSI("Hmolar", "T", de.T_top_K, "Q", 0, "Ethane"))     # J/mol
    q_pure = V * 1000.0 * hfg / 3600.0 / 1000.0
    assert de.condenser_duty_kW == pytest.approx(q_pure, rel=0.03)


def test_reboiler_exceeds_condenser_less_cold_feed_credit(train):
    for c in train.columns:
        assert c.reboiler_duty_kW > 0 and c.condenser_duty_kW > 0


def test_higher_reflux_factor_trades_stages_for_duty():
    base = dict(name="dp", light_key="Propane", heavy_key="Isobutane", top_pressure_Pa=17e5,
                lk_recovery_to_distillate=0.985, hk_recovery_to_bottoms=0.98)
    feed = {"Propane": 300, "Isobutane": 60, "n-Butane": 100, "Isopentane": 50}
    lo = size_column(feed, ColumnSpec(**base, reflux_factor=1.15))
    hi = size_column(feed, ColumnSpec(**base, reflux_factor=1.6))
    assert hi.N_theoretical < lo.N_theoretical
    assert hi.condenser_duty_kW > lo.condenser_duty_kW


def test_diameter_grows_with_feed_rate():
    sp = ColumnSpec("dp", "Propane", "Isobutane", 17e5, 0.985, 0.98)
    small = size_column({"Propane": 100, "Isobutane": 20, "n-Butane": 30}, sp)
    big = size_column({"Propane": 400, "Isobutane": 80, "n-Butane": 120}, sp)
    assert big.diameter_top_m > small.diameter_top_m


def test_non_adjacent_keys_rejected():
    sp = ColumnSpec("bad", "Propane", "n-Butane", 10e5)
    with pytest.raises(ValueError, match="not adjacent"):
        size_column({"Propane": 100, "Isobutane": 30, "n-Butane": 50}, sp)


def test_swapped_keys_rejected():
    sp = ColumnSpec("bad", "n-Butane", "Propane", 10e5)
    with pytest.raises(ValueError):
        size_column({"Propane": 100, "n-Butane": 50}, sp)


def test_missing_key_rejected():
    with pytest.raises(ValueError, match="both be in the feed"):
        size_column({"Propane": 100}, ColumnSpec("x", "Propane", "n-Butane", 10e5))
