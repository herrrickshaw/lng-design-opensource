import pytest

from lng_design.equipment_catalog import (
    COMPRESSOR_FRAMES,
    match_standard_size,
    select_compressor_frame,
)
from lng_design.compressor import match_frame_for_stage
from lng_design.mche import classify_mche_type
from lng_design.properties import GasMixture


def test_match_standard_size_rounds_up():
    assert match_standard_size(500.0, [400.0, 600.0, 800.0]) == 600.0


def test_match_standard_size_exact_hit():
    assert match_standard_size(600.0, [400.0, 600.0, 800.0]) == 600.0


def test_match_standard_size_rejects_oversized_request():
    with pytest.raises(ValueError):
        match_standard_size(900.0, [400.0, 600.0, 800.0])


def test_select_compressor_frame_matches_published_worked_example():
    # docs/VALIDATION.md's GPSA worked example selects Frame C for its
    # ~36,581 m3/h inlet volume flow - reproduced here as a regression
    # check on the frame table itself.
    frame = select_compressor_frame(36581.45)
    assert frame.name == "C"


def test_select_compressor_frame_smaller_flow_smaller_frame():
    small = select_compressor_frame(5000.0)
    large = select_compressor_frame(100000.0)
    assert COMPRESSOR_FRAMES.index(small) < COMPRESSOR_FRAMES.index(large)


def test_select_compressor_frame_rejects_flow_beyond_largest_frame():
    with pytest.raises(ValueError):
        select_compressor_frame(1_000_000.0)


def test_match_frame_for_stage_end_to_end():
    gas = GasMixture({"Ethane": 0.05, "Propane": 0.80, "n-Butane": 0.15})
    frame, vol_flow = match_frame_for_stage(gas, T_in_K=313.15, P_in_Pa=2.068e5, mass_flow_kg_s=37.8)
    assert vol_flow == pytest.approx(36581.45, rel=0.01)
    assert frame.name == "C"


def test_classify_mche_type_small_vs_large():
    small = classify_mche_type(0.5)
    large = classify_mche_type(5.0)
    assert "plate-fin" in small["typical_technology"]
    assert "coil-wound" in large["typical_technology"]
