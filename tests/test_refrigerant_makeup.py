import pytest

from lng_design.refrigerant_makeup import size_refrigerant_storage
from lng_design.equipment_catalog import STANDARD_VESSEL_DIAMETERS_MM


def test_required_liquid_volume_matches_manual_calc():
    charge_kg, density, reserve = 50000.0, 500.0, 0.2
    result = size_refrigerant_storage(charge_kg, density, reserve_fraction=reserve)
    expected = (charge_kg * (1 + reserve)) / density
    assert result.required_liquid_volume_m3 == pytest.approx(expected, rel=1e-9)


def test_vessel_volume_exceeds_required_liquid_volume():
    result = size_refrigerant_storage(50000.0, 500.0, max_fill_fraction=0.85)
    assert result.vessel_volume_m3 > result.required_liquid_volume_m3
    assert result.required_liquid_volume_m3 / result.vessel_volume_m3 == pytest.approx(0.85, rel=1e-6)


def test_standard_diameter_from_catalog():
    result = size_refrigerant_storage(50000.0, 500.0)
    assert result.standard_diameter_mm in STANDARD_VESSEL_DIAMETERS_MM


def test_rejects_invalid_fill_fraction():
    with pytest.raises(ValueError):
        size_refrigerant_storage(50000.0, 500.0, max_fill_fraction=1.0)
    with pytest.raises(ValueError):
        size_refrigerant_storage(50000.0, 500.0, max_fill_fraction=0.0)


def test_larger_charge_needs_bigger_vessel():
    small = size_refrigerant_storage(10000.0, 500.0)
    large = size_refrigerant_storage(40000.0, 500.0)
    assert large.vessel_volume_m3 > small.vessel_volume_m3


def test_oversized_charge_correctly_signals_multiple_vessels_needed():
    # A 100-tonne single charge at these defaults needs a vessel bigger
    # than any single standard size (~4.5 m required vs. 4.27 m largest
    # standard diameter) - the catalog correctly refuses rather than
    # silently returning an undersized "closest" match; the real answer
    # is multiple parallel vessels, which is the caller's job to arrange.
    with pytest.raises(ValueError, match="parallel units"):
        size_refrigerant_storage(100000.0, 500.0)
