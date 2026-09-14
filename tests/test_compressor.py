"""Validate the compressor module's thermodynamic consistency.

Primary check: in the ideal-gas / low-pressure limit (Z -> 1, k constant),
the polytropic-head formula used in compressor.py must collapse to the
textbook ideal-gas polytropic work formula (any thermodynamics text, e.g.
Cengel & Boles "Thermodynamics: An Engineering Approach", compression work
chapter):

    w = (n/(n-1)) * R_specific * T_in * [(P_out/P_in)^((n-1)/n) - 1]

We use nitrogen at low pressure (near-ideal-gas conditions) as the test
fluid so CoolProp's real-gas Z stays within ~0.1% of 1, isolating the
compressor module's formula from real-gas effects for this check.
"""
import math

import pytest

from lng_design.compressor import size_centrifugal_stage, size_multistage
from lng_design.properties import GasMixture, R_UNIVERSAL


def test_ideal_gas_limit_matches_textbook_polytropic_work():
    n2 = GasMixture({"Nitrogen": 1.0})
    T_in, P_in, P_out = 300.0, 1.5e5, 3.0e5  # low pressure -> near-ideal
    mdot = 1.0
    eta_p = 0.80

    result = size_centrifugal_stage(n2, T_in, P_in, P_out, mdot, eta_p)

    k = n2.cp_over_cv(T_in, P_in)
    n = 1.0 / (1.0 - (k - 1.0) / (k * eta_p))
    MW = n2.molecular_weight() / 1000.0
    R_spec = R_UNIVERSAL / MW
    ratio = P_out / P_in
    head_ideal = R_spec * T_in * (n / (n - 1.0)) * (ratio ** ((n - 1.0) / n) - 1.0)

    assert result.Z_avg == pytest.approx(1.0, abs=0.01)
    assert result.polytropic_head_J_per_kg == pytest.approx(head_ideal, rel=0.02)


def test_power_increases_monotonically_with_pressure_ratio():
    n2 = GasMixture({"Nitrogen": 1.0})
    powers = []
    for P_out in (2e5, 3e5, 4e5, 5e5):
        r = size_centrifugal_stage(n2, 300.0, 1.5e5, P_out, 1.0, 0.8)
        powers.append(r.gas_power_kW)
    assert powers == sorted(powers)


def test_higher_efficiency_reduces_power_for_same_duty():
    n2 = GasMixture({"Nitrogen": 1.0})
    low_eta = size_centrifugal_stage(n2, 300.0, 1.5e5, 3.0e5, 1.0, 0.65)
    high_eta = size_centrifugal_stage(n2, 300.0, 1.5e5, 3.0e5, 1.0, 0.85)
    assert high_eta.gas_power_kW < low_eta.gas_power_kW


def test_multistage_reproduces_overall_pressure_ratio():
    n2 = GasMixture({"Nitrogen": 1.0})
    stages = size_multistage(n2, 300.0, 1.0e5, 8.0e5, 1.0, n_stages=3,
                              interstage_cooling_to_K=300.0)
    overall_ratio = 1.0
    for s in stages:
        overall_ratio *= s.pressure_ratio
    assert overall_ratio == pytest.approx(8.0, rel=1e-6)


def test_rejects_non_physical_compression():
    n2 = GasMixture({"Nitrogen": 1.0})
    with pytest.raises(ValueError):
        size_centrifugal_stage(n2, 300.0, 3.0e5, 1.5e5, 1.0, 0.8)  # P_out < P_in
