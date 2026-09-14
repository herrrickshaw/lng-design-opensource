"""Validate the composite-curve / MITA check, including the internal
(non-terminal) pinch violation case that a naive terminal-only check would
miss - this is the specific failure mode the module's docstring calls out.
"""
import pytest

from lng_design.mche import StreamSegment, analyze_composite_curves


def test_simple_two_stream_case_no_violation():
    hot = [StreamSegment(T_start_K=300.0, T_end_K=250.0, duty_kW=1000.0)]
    cold = [StreamSegment(T_start_K=245.0, T_end_K=295.0, duty_kW=1000.0)]
    result = analyze_composite_curves(hot, cold, min_approach_K=3.0)
    assert result.min_approach_K >= 3.0
    assert result.total_duty_kW == pytest.approx(1000.0)
    assert result.ua_estimate_kW_per_K > 0
    assert result.area_estimate_m2 > 0


def test_terminal_ok_but_internal_pinch_violation_is_caught():
    # Two hot sub-streams with very different duty/temperature slopes create
    # a narrow internal approach even though the terminal temperatures look
    # fine - the exact trap this module's docstring warns about.
    hot = [
        StreamSegment(T_start_K=300.0, T_end_K=280.0, duty_kW=50.0),   # shallow slope
        StreamSegment(T_start_K=280.0, T_end_K=250.0, duty_kW=950.0),  # steep slope
    ]
    cold = [StreamSegment(T_start_K=248.0, T_end_K=297.0, duty_kW=1000.0)]
    with pytest.raises(ValueError, match="MITA violated"):
        analyze_composite_curves(hot, cold, min_approach_K=3.0)


def test_larger_min_approach_reduces_estimated_area():
    hot = [StreamSegment(T_start_K=300.0, T_end_K=250.0, duty_kW=1000.0)]
    cold_tight = [StreamSegment(T_start_K=246.0, T_end_K=296.0, duty_kW=1000.0)]
    cold_loose = [StreamSegment(T_start_K=230.0, T_end_K=280.0, duty_kW=1000.0)]
    tight = analyze_composite_curves(hot, cold_tight, min_approach_K=3.0)
    loose = analyze_composite_curves(hot, cold_loose, min_approach_K=3.0)
    # loose approach (bigger driving force) needs less area for the same duty
    assert loose.area_estimate_m2 < tight.area_estimate_m2
