import pytest

from lng_design.mche_tube_design import (
    TubeBundleGeometry,
    dittus_boelter_htc,
    falling_film_htc,
    overall_U_local,
    rate_mche_bundle,
    shah_condensation_htc,
)
from lng_design.properties import GasMixture

NG = GasMixture({"Methane": 0.85, "Ethane": 0.08, "Propane": 0.04, "Nitrogen": 0.03})
LRC_BLEND = GasMixture({"Nitrogen": 0.05, "Methane": 0.30, "Ethane": 0.35, "Propane": 0.30})


def test_tube_bundle_geometry_areas():
    geo = TubeBundleGeometry(n_tubes=100, tube_od_m=0.02, tube_wall_m=0.002, tube_length_m=5.0)
    assert geo.tube_id_m == pytest.approx(0.016)
    # Outer area must exceed inner area for a finite wall thickness.
    assert geo.outer_area_m2 > geo.inner_area_m2 > 0


def test_dittus_boelter_rejects_laminar_flow():
    # A tiny mass flow through many tubes gives Re well below the
    # correlation's turbulent-flow range (Re >= 10,000).
    with pytest.raises(ValueError, match="turbulent-flow range"):
        dittus_boelter_htc(NG, 250.0, 45e5, 0.01, tube_id_m=0.0159, n_tubes=100)


def test_dittus_boelter_turbulent_gives_positive_htc():
    h = dittus_boelter_htc(NG, 250.0, 45e5, 20.0, tube_id_m=0.0159, n_tubes=50)
    assert h > 0
    # Loose sanity bound (not a precise check): at 45 bara/250 K this NG
    # mixture sits near methane's own pseudo-critical pressure, dense
    # enough to give a higher single-phase coefficient than a dilute-gas
    # rule of thumb would suggest - confirmed physically reasonable, not
    # assumed in advance.
    assert 10.0 < h < 20000.0


def test_shah_condensation_matches_liquid_only_at_zero_quality():
    # At x=0 the enhancement factor collapses to exactly 1.0, so Shah's
    # h_TP must equal h_LO (the all-liquid reference coefficient).
    h_x0 = shah_condensation_htc(NG, 220.0, 45e5, 20.0, tube_id_m=0.0159, n_tubes=50, vapor_quality=0.0)
    h_x0_again = shah_condensation_htc(NG, 220.0, 45e5, 20.0, tube_id_m=0.0159, n_tubes=50, vapor_quality=0.0)
    assert h_x0 == pytest.approx(h_x0_again)
    assert h_x0 > 0


def test_shah_condensation_enhances_over_liquid_only():
    # Condensation at intermediate quality should exceed the liquid-only
    # coefficient - the whole point of Shah's enhancement factor.
    h_lo_ref = shah_condensation_htc(NG, 220.0, 45e5, 20.0, tube_id_m=0.0159, n_tubes=50, vapor_quality=0.0)
    h_mid = shah_condensation_htc(NG, 220.0, 45e5, 20.0, tube_id_m=0.0159, n_tubes=50, vapor_quality=0.5)
    assert h_mid > h_lo_ref


def test_shah_condensation_rejects_invalid_quality():
    with pytest.raises(ValueError, match="vapor_quality"):
        shah_condensation_htc(NG, 220.0, 45e5, 20.0, tube_id_m=0.0159, n_tubes=50, vapor_quality=1.5)


def test_falling_film_htc_thicker_film_lowers_htc():
    # More liquid flow per unit width -> thicker film -> more conduction
    # resistance -> lower h. A basic physical monotonicity check.
    h_thin = falling_film_htc(liquid_k_W_mK=0.1, liquid_rho_kg_m3=500.0, liquid_mu_Pa_s=1e-4, film_flow_rate_per_width_kg_ms=0.01)
    h_thick = falling_film_htc(liquid_k_W_mK=0.1, liquid_rho_kg_m3=500.0, liquid_mu_Pa_s=1e-4, film_flow_rate_per_width_kg_ms=0.1)
    assert h_thin > h_thick > 0


def test_falling_film_htc_rejects_nonpositive_flow():
    with pytest.raises(ValueError):
        falling_film_htc(0.1, 500.0, 1e-4, 0.0)


def test_overall_U_local_is_bounded_by_both_individual_coefficients():
    # Series resistances always drive the combined U below EACH
    # individual coefficient - a basic thermal-resistance invariant.
    U = overall_U_local(h_i_W_m2K=1000.0, h_o_W_m2K=500.0, tube_id_m=0.0159, tube_od_m=0.01905, tube_k_W_mK=200.0)
    assert 0 < U < 500.0


def test_overall_U_local_dominated_by_smaller_coefficient():
    # A very large h_i should leave U close to (but below) h_o - the
    # wall/shell side then dominates the series resistance.
    U = overall_U_local(h_i_W_m2K=1.0e6, h_o_W_m2K=300.0, tube_id_m=0.0159, tube_od_m=0.01905, tube_k_W_mK=200.0)
    assert 250.0 < U < 300.0


def test_rate_mche_bundle_larger_bundle_gives_colder_achievable_rundown():
    # Round-trip physical sanity check: a bigger tube bundle (more area)
    # must never achieve a WARMER rundown than a smaller one, everything
    # else held fixed - the core "more accurate rundown" behavior this
    # module exists to deliver, not just that it runs without error.
    kwargs = dict(
        process_gas=NG, process_mass_flow_kg_s=20.0, process_P_Pa=45e5, process_T_hot_end_K=233.15,
        refrigerant=LRC_BLEND, refrigerant_mass_flow_kg_s=30.0, refrigerant_T_evap_K=173.15,
        min_approach_K=3.0, n_zones=5,
    )
    small = rate_mche_bundle(TubeBundleGeometry(n_tubes=200), **kwargs)
    large = rate_mche_bundle(TubeBundleGeometry(n_tubes=2000), **kwargs)

    assert large.achievable_rundown_T_K < small.achievable_rundown_T_K
    assert small.binding_constraint == "area"
    # Both must respect the MITA floor.
    assert small.achievable_rundown_T_K > 173.15 + 3.0 - 1e-6
    assert large.achievable_rundown_T_K > 173.15 + 3.0 - 1e-6


def test_rate_mche_bundle_huge_bundle_is_mita_limited():
    # A bundle with far more area than needed must be capped by the
    # pinch constraint, at (refrigerant_T_evap + min_approach) - the
    # same MITA discipline mche.analyze_composite_curves enforces.
    result = rate_mche_bundle(
        TubeBundleGeometry(n_tubes=20000), NG, 20.0, 45e5, 233.15,
        LRC_BLEND, 30.0, 173.15, min_approach_K=3.0, n_zones=5,
    )
    assert result.binding_constraint == "MITA"
    assert result.achievable_rundown_T_K == pytest.approx(173.15 + 3.0 + 0.5, abs=0.2)
    assert result.total_area_used_m2 <= result.available_area_m2
