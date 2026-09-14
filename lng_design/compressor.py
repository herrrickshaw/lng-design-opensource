"""Centrifugal compressor conceptual sizing.

Method: polytropic head / polytropic efficiency approach as given in the
GPSA Engineering Data Book (Ch. 13, "Compressors") and standard turbomachinery
references (e.g. Boyce, "Gas Turbine Engineering Handbook", compressor
chapter). This is the same method vendors use for a first-pass frame
selection before a certified performance curve exists - i.e. it is meant to
be checked against a real curve (see amine_absorber.py's Kremser-based
absorber for the analogous relationship on the separations side).

Governing relations
--------------------
Polytropic exponent from polytropic efficiency and isentropic exponent k:
    (n-1)/n = (k-1)/(k * eta_p)

Polytropic head (per unit mass):
    H_p = Z_avg * (R/MW) * T_in * (n/(n-1)) * [(P_out/P_in)**((n-1)/n) - 1]

Gas power:
    P_gas = mdot * H_p / eta_p

All energy quantities in SI (J, W); head in J/kg (equivalent to m^2/s^2,
sometimes reported as m via /g -- we keep J/kg to stay unit-unambiguous).

Real, named centrifugal-compressor OEMs in LNG refrigerant service
(docs/VENDOR_REFERENCE.md): Baker Hughes' own investor press release
confirms a real, quantified order for "Qatar North Field East" -- 4
mega-trains, 6 centrifugal compressors per train -- the SAME project
`examples/gem_upcoming_projects_sizing.py` already sizes (8.0 MTPA/train
average, independently sourced from the Global Energy Monitor tracker).
Neither source publishes individual compressor MW ratings, so this is a
project-identity/train-count cross-check, not a numeric validation of
this module's own computed power output.
"""
from __future__ import annotations

from dataclasses import dataclass

from .equipment_catalog import CompressorFrame, select_compressor_frame
from .properties import GasMixture, R_UNIVERSAL


@dataclass
class CompressorStageResult:
    T_in: float
    P_in: float
    T_out_ideal: float
    polytropic_exponent: float
    polytropic_head_J_per_kg: float
    gas_power_kW: float
    pressure_ratio: float
    Z_avg: float
    k_avg: float


def size_centrifugal_stage(
    gas: GasMixture,
    T_in_K: float,
    P_in_Pa: float,
    P_out_Pa: float,
    mass_flow_kg_s: float,
    polytropic_efficiency: float = 0.78,
) -> CompressorStageResult:
    """Size a single centrifugal compressor stage (or a stage treated as a
    single polytropic step; for multi-stage machines, call once per stage
    with that stage's suction/discharge conditions).

    polytropic_efficiency default of 0.78 is a typical mid-range value for
    a well-designed centrifugal stage (GPSA Ch. 13 quotes 70-80% as typical
    for multistage centrifugal compressors); override with vendor data when
    available.
    """
    if not (0.0 < polytropic_efficiency <= 1.0):
        raise ValueError("polytropic_efficiency must be in (0, 1]")
    if P_out_Pa <= P_in_Pa:
        raise ValueError("P_out must exceed P_in for a compression stage")

    MW = gas.molecular_weight() / 1000.0  # kg/mol
    k_in = gas.cp_over_cv(T_in_K, P_in_Pa)
    Z_in = gas.compressibility(T_in_K, P_in_Pa)

    n = 1.0 / (1.0 - (k_in - 1.0) / (k_in * polytropic_efficiency))
    pressure_ratio = P_out_Pa / P_in_Pa

    # First-pass discharge temperature from the polytropic relation, then
    # re-evaluate Z and k at the mean of inlet/outlet to refine head (one
    # fixed-point iteration is enough for the modest T-dependence typical
    # of light hydrocarbon/refrigerant mixtures over a single stage).
    T_out_ideal = T_in_K * pressure_ratio ** ((n - 1.0) / n)
    T_avg = 0.5 * (T_in_K + T_out_ideal)
    P_avg = 0.5 * (P_in_Pa + P_out_Pa)
    Z_avg = 0.5 * (Z_in + gas.compressibility(T_out_ideal, P_out_Pa))
    k_avg = 0.5 * (k_in + gas.cp_over_cv(T_avg, P_avg))
    n = 1.0 / (1.0 - (k_avg - 1.0) / (k_avg * polytropic_efficiency))

    R_specific = R_UNIVERSAL / MW  # J/kg-K
    head = (
        Z_avg
        * R_specific
        * T_in_K
        * (n / (n - 1.0))
        * (pressure_ratio ** ((n - 1.0) / n) - 1.0)
    )
    power_W = mass_flow_kg_s * head / polytropic_efficiency

    return CompressorStageResult(
        T_in=T_in_K,
        P_in=P_in_Pa,
        T_out_ideal=T_out_ideal,
        polytropic_exponent=n,
        polytropic_head_J_per_kg=head,
        gas_power_kW=power_W / 1000.0,
        pressure_ratio=pressure_ratio,
        Z_avg=Z_avg,
        k_avg=k_avg,
    )


def size_multistage(
    gas: GasMixture,
    T_in_K: float,
    P_in_Pa: float,
    P_out_Pa: float,
    mass_flow_kg_s: float,
    n_stages: int,
    polytropic_efficiency: float = 0.78,
    interstage_cooling_to_K: float | None = None,
) -> list[CompressorStageResult]:
    """Split an overall pressure ratio evenly (log-basis, the standard
    "equal pressure ratio per stage" heuristic - GPSA Ch. 13) across
    n_stages, optionally with interstage cooling back to a fixed
    temperature (typical for process gas compressors feeding a cooler
    between casings).
    """
    overall_ratio = P_out_Pa / P_in_Pa
    stage_ratio = overall_ratio ** (1.0 / n_stages)

    results = []
    P_stage_in = P_in_Pa
    T_stage_in = T_in_K
    for _ in range(n_stages):
        P_stage_out = P_stage_in * stage_ratio
        res = size_centrifugal_stage(
            gas, T_stage_in, P_stage_in, P_stage_out, mass_flow_kg_s,
            polytropic_efficiency,
        )
        results.append(res)
        P_stage_in = P_stage_out
        T_stage_in = (
            interstage_cooling_to_K
            if interstage_cooling_to_K is not None
            else res.T_out_ideal
        )
    return results


def match_frame_for_stage(
    gas: GasMixture, T_in_K: float, P_in_Pa: float, mass_flow_kg_s: float,
) -> tuple[CompressorFrame, float]:
    """Match a compressor stage's inlet conditions against the standard
    frame table in `equipment_catalog.py` (GPSA-style frame selection -
    see docs/VALIDATION.md for the published worked example this table is
    validated against).

    T_in_K/P_in_Pa must describe a SINGLE-PHASE state - safe for a real
    process gas stream (normally well above its dew point), but NOT for a
    refrigeration cycle's own saturated suction conditions (T_evap,
    P_evap sit exactly on that fluid's saturation curve by definition, so
    a plain T,P density lookup is ambiguous there and CoolProp will raise
    rather than guess liquid vs. vapor - found by running
    examples/full_train_worked_example.py, see docs/VALIDATION.md). For a
    refrigerant compressor's own suction, get the vapor density directly
    via CoolProp's quality input (Q=1) instead of calling this function
    with the cycle's (T_evap, P_evap).

    Returns (matched_frame, inlet_volume_flow_m3_h).
    """
    density = gas.density(T_in_K, P_in_Pa)
    inlet_vol_flow_m3_h = (mass_flow_kg_s / density) * 3600.0
    frame = select_compressor_frame(inlet_vol_flow_m3_h)
    return frame, inlet_vol_flow_m3_h
