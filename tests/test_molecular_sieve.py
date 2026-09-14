import pytest

from lng_design.molecular_sieve import size_molecular_sieve_bed
from lng_design.equipment_catalog import STANDARD_VESSEL_DIAMETERS_MM

# Verified (by running the function) to produce a bed above the minimum
# practical depth at the module's other defaults - a smaller flow and/or
# richer wet gas than the pathological case tested separately below.
MDOT, PPM = 20.0, 800.0


def test_water_removed_matches_manual_calc():
    hours = 8.0
    result = size_molecular_sieve_bed(MDOT, 25.0, PPM, adsorption_time_h=hours)
    expected = MDOT * 3600.0 * hours * PPM * 1e-6
    assert result.water_removed_per_cycle_kg == pytest.approx(expected, rel=1e-9)


def test_bed_mass_scales_inversely_with_working_capacity():
    # Richer wet gas so both capacity levels clear the minimum bed depth.
    low_cap = size_molecular_sieve_bed(MDOT, 25.0, 1200.0, working_capacity_wt_pct=8.0)
    high_cap = size_molecular_sieve_bed(MDOT, 25.0, 1200.0, working_capacity_wt_pct=16.0)
    assert low_cap.bed_mass_kg == pytest.approx(2 * high_cap.bed_mass_kg, rel=1e-6)


def test_standard_diameter_from_catalog():
    result = size_molecular_sieve_bed(MDOT, 25.0, PPM)
    assert result.standard_diameter_mm in STANDARD_VESSEL_DIAMETERS_MM


def test_two_beds_when_regen_and_cooldown_fit_in_adsorption_window():
    result = size_molecular_sieve_bed(
        MDOT, 25.0, PPM, adsorption_time_h=8.0, regen_time_h=4.0, cooldown_time_h=1.0,
    )
    assert result.n_beds == 2


def test_three_beds_when_regen_and_cooldown_exceed_adsorption_window():
    result = size_molecular_sieve_bed(
        MDOT, 25.0, PPM, adsorption_time_h=8.0, regen_time_h=6.0, cooldown_time_h=3.0,
    )
    assert result.n_beds == 3


def test_regen_heater_duty_positive_and_scales_with_flow():
    small = size_molecular_sieve_bed(20.0, 25.0, 800.0)
    large = size_molecular_sieve_bed(40.0, 25.0, 800.0)
    assert large.regen_heater_duty_kW == pytest.approx(2 * small.regen_heater_duty_kW, rel=1e-6)


def test_rejects_non_positive_water_content():
    with pytest.raises(ValueError):
        size_molecular_sieve_bed(MDOT, 25.0, 0.0)


def test_rejects_pancake_bed_high_flow_low_water_content():
    # High gas flow (large velocity-sized diameter) with low water content
    # (small water-duty-sized adsorbent volume) gives an unrealistically
    # shallow bed that can't develop a proper mass-transfer zone - this
    # exact combination was caught by actually running the Streamlit app,
    # not written from a formula in advance.
    with pytest.raises(ValueError, match="mass-transfer zone"):
        size_molecular_sieve_bed(50.0, 25.0, 100.0)
