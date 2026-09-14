"""Validate the amine absorber module against the analytic Kremser
equation limits (McCabe, Smith & Harriott, "Unit Operations of Chemical
Engineering", absorption chapter) and basic flooding-correlation physics.
"""
import math

import pytest

from lng_design.amine_absorber import size_packed_absorber, _kremser_stages


def test_kremser_A_equals_1_limit_matches_closed_form():
    # Textbook A->1 limit: N = (y_in - y_out) / (y_out - m*x_in)
    y_in, y_out, m, x_in = 0.05, 0.001, 0.5, 0.0
    N = _kremser_stages(y_in, y_out, m, x_in, absorption_factor=1.0)
    expected = (y_in - y_out) / (y_out - m * x_in)
    assert N == pytest.approx(expected, rel=1e-3)


def test_kremser_more_stages_needed_for_deeper_removal():
    N_shallow = _kremser_stages(0.05, 0.01, 0.5, 0.0, absorption_factor=1.5)
    N_deep = _kremser_stages(0.05, 0.001, 0.5, 0.0, absorption_factor=1.5)
    assert N_deep > N_shallow


def test_kremser_rejects_unachievable_target():
    # target below the equilibrium floor m*x_in is thermodynamically impossible
    with pytest.raises(ValueError):
        _kremser_stages(0.05, 0.0, 0.5, 0.1, absorption_factor=1.5)  # m*x_in = 0.05 > y_out


def test_absorber_sizing_runs_and_gives_sane_column():
    result = size_packed_absorber(
        gas_volumetric_flow_m3_s=5.0,
        gas_density_kg_m3=25.0,   # typical high-pressure sour gas order of magnitude
        liquid_density_kg_m3=1010.0,  # typical aqueous amine solution
        y_in_mole_frac=0.03,
        y_out_target_mole_frac=0.0005,
        x_in_mole_frac=0.001,
        equilibrium_slope_m=0.4,
        liquid_to_gas_molar_ratio=25.0,
        K_SB=0.04,
        design_fraction_of_flood=0.75,
        hetp_m=0.5,
    )
    assert result.diameter_m > 0
    assert result.n_theoretical_stages > 0
    assert result.packed_height_m > 0
    # design point must sit below the flooding velocity by construction
    assert result.superficial_gas_velocity_m_s < result.flooding_velocity_m_s


def test_flooding_velocity_scales_with_density_difference():
    # Souders-Brown: v_flood ~ sqrt((rho_L - rho_V)/rho_V) - larger density
    # difference (lower-pressure gas) should give a higher flooding velocity
    hi_dp = size_packed_absorber(
        5.0, 5.0, 1010.0, 0.03, 0.0005, 0.001, 0.4, 25.0,
    )
    lo_dp = size_packed_absorber(
        5.0, 60.0, 1010.0, 0.03, 0.0005, 0.001, 0.4, 25.0,
    )
    assert hi_dp.flooding_velocity_m_s > lo_dp.flooding_velocity_m_s
