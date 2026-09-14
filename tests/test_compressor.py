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


def test_matches_published_gpsa_worked_example():
    """External validation against a freely published worked example:
    "Centrifugal Compressor Head and Power Calculations" (cheresources.com
    preview PDF), whose gas property table is sourced from the GPSA
    Engineering Data Book, 11th Ed.-SI (1998). This is independent of
    lng_design's own docstring citations - a real published input/output
    pair, not a self-consistency check.

    Published inputs: 5/80/15 mol% ethane/propane/n-butane, P1=2.068 bara,
    T1=40 C, P2=6.89 bara, M=136,078 kg/h, eta_poly=77%.
    Published outputs: Z_avg=0.956, H_poly=71,971 N-m/kg, T2=99.9 C,
    gas power=3,533.1 kW.

    lng_design.compressor evaluates kappa at the mean of inlet/outlet
    conditions rather than fixing it at the inlet value (as the published
    method does) - the source material itself notes the polytropic head
    equation is insensitive to kappa within its normal range of variation,
    so a small deviation is expected. Discharge temperature is the most
    kappa-sensitive output (it appears in the (n-1)/n exponent), hence its
    larger tolerance below.
    """
    gas = GasMixture({"Ethane": 0.05, "Propane": 0.80, "n-Butane": 0.15})
    result = size_centrifugal_stage(
        gas, T_in_K=40 + 273.15, P_in_Pa=2.068e5, P_out_Pa=6.89e5,
        mass_flow_kg_s=136078.0 / 3600.0, polytropic_efficiency=0.77,
    )

    assert result.Z_avg == pytest.approx(0.956, abs=0.001)
    assert result.pressure_ratio == pytest.approx(3.33, rel=0.01)
    assert result.polytropic_head_J_per_kg == pytest.approx(71971.0, rel=0.01)  # within 1%
    assert result.gas_power_kW == pytest.approx(3533.1, rel=0.01)  # within 1%
    assert (result.T_out_ideal - 273.15) == pytest.approx(99.9, abs=4.0)  # within 4 C
