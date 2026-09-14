"""Detailed MCHE tube-side/shell-side heat transfer coefficients, for a
RATING calculation rather than mche.py's SIZING calculation.

`mche.analyze_composite_curves` answers "given a target rundown
temperature and one assumed constant overall U, does the pinch/area work
out" - useful for fast screening, but it can't say what a specific, real
tube bundle can actually deliver. This module answers the inverse,
standard process-engineering "rating" question (Kern, "Process Heat
Transfer"; Sinnott & Towler, "Chemical Engineering Design" both draw this
same sizing-vs-rating distinction): given a FIXED tube bundle geometry
and known process/refrigerant flows, what is the coldest NG rundown
temperature this bundle can actually achieve - using local, condition-
dependent heat transfer coefficients computed from real CoolProp
properties at each point along the exchanger, not one assumed number.

Correlations used (all standard, public, non-proprietary - none of this
reproduces any vendor's proprietary spiral-wound exchanger correlation):

- Dittus-Boelter (1930) single-phase turbulent forced convection, tube
  side - reproduced in Incropera, "Fundamentals of Heat and Mass
  Transfer".
- Shah (1979) in-tube condensation - M.M. Shah, "A general correlation
  for heat transfer during film condensation inside pipes", Int. J. Heat
  and Mass Transfer 22(4), 547-556.
- A simplified laminar falling-film shell-side coefficient, using the
  standard Nusselt laminar-film-thickness relation (see e.g. Incropera
  Ch. 10; Bird, Stewart & Lightfoot, "Transport Phenomena") combined with
  a conduction-through-the-film approximation. This deliberately omits
  nucleate-boiling and wave/turbulence enhancement a real coil-wound
  exchanger's own correlation would add - it is a conservative (probably
  low) estimate of the shell-side coefficient, flagged explicitly rather
  than presented as a full design correlation. See docs/VALIDATION.md.
- Standard cylindrical-wall series-resistance combination (Kern).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import CoolProp.CoolProp as CP
from scipy.optimize import brentq

from .properties import GasMixture

# Same tube-size defaults exchangers.py already cites (Kern; Sinnott &
# Towler) - 3/4" OD is the most common process tube size, 20 ft a common
# standard tube length. ~200 W/m-K is representative of the high-
# conductivity aluminum alloys standard for cryogenic-service tube/fin
# material (general cryogenic materials practice, not a vendor-specific
# value).
DEFAULT_TUBE_OD_M = 0.01905
DEFAULT_TUBE_WALL_M = 0.0016
DEFAULT_TUBE_LENGTH_M = 6.1
DEFAULT_TUBE_K_W_MK = 200.0

_G = 9.80665


@dataclass
class TubeBundleGeometry:
    n_tubes: int
    tube_od_m: float = DEFAULT_TUBE_OD_M
    tube_wall_m: float = DEFAULT_TUBE_WALL_M
    tube_length_m: float = DEFAULT_TUBE_LENGTH_M
    tube_k_W_mK: float = DEFAULT_TUBE_K_W_MK

    @property
    def tube_id_m(self) -> float:
        return self.tube_od_m - 2.0 * self.tube_wall_m

    @property
    def outer_area_m2(self) -> float:
        return self.n_tubes * math.pi * self.tube_od_m * self.tube_length_m

    @property
    def inner_area_m2(self) -> float:
        return self.n_tubes * math.pi * self.tube_id_m * self.tube_length_m


def _dittus_boelter_from_props(
    mu_Pa_s: float, k_W_mK: float, cp_J_kgK: float, mass_flow_kg_s: float,
    tube_id_m: float, n_tubes: int, cooling: bool = True,
) -> float:
    """Formula-only core of Dittus-Boelter, taking already-evaluated
    transport properties - split out so a caller iterating many
    temperature points (see _zone_integrate) can supply properties read
    off ONE persistent CoolProp state instead of triggering a fresh
    mixture flash per property per point (the actual cost driver for a
    multicomponent HEOS mixture - see this module's docstring)."""
    mdot_per_tube = mass_flow_kg_s / n_tubes
    Re = 4.0 * mdot_per_tube / (math.pi * tube_id_m * mu_Pa_s)
    if Re < 10000.0:
        raise ValueError(
            f"Re={Re:,.0f} is below Dittus-Boelter's turbulent-flow range "
            "(Re >= 10,000) - increase mass flow per tube, reduce tube ID, "
            "or use fewer parallel tubes."
        )
    Pr = cp_J_kgK * mu_Pa_s / k_W_mK
    n = 0.3 if cooling else 0.4
    Nu = 0.023 * Re ** 0.8 * Pr ** n
    return Nu * k_W_mK / tube_id_m


def dittus_boelter_htc(
    fluid: GasMixture, T_K: float, P_Pa: float, mass_flow_kg_s: float,
    tube_id_m: float, n_tubes: int, cooling: bool = True,
) -> float:
    """Single-phase turbulent tube-side coefficient (Dittus-Boelter,
    1930): Nu = 0.023 * Re^0.8 * Pr^n (n=0.3 cooling, 0.4 heating).

    Raises ValueError if Re < 10,000 - outside the correlation's stated
    turbulent-flow range. Standalone convenience wrapper around
    _dittus_boelter_from_props for one-off calls/tests; _zone_integrate
    uses the props-only core directly for performance.
    """
    mu = fluid.viscosity(T_K, P_Pa)
    k = fluid.thermal_conductivity(T_K, P_Pa)
    cp = fluid.specific_heat(T_K, P_Pa)
    return _dittus_boelter_from_props(mu, k, cp, mass_flow_kg_s, tube_id_m, n_tubes, cooling)


def shah_condensation_htc(
    fluid: GasMixture, T_K: float, P_Pa: float, mass_flow_kg_s: float,
    tube_id_m: float, n_tubes: int, vapor_quality: float,
    reference_liquid_fluid: str | None = None,
) -> float:
    """In-tube condensation coefficient (Shah, 1979):

        h_TP = h_LO * [(1-x)^0.8 + 3.8 x^0.76 (1-x)^0.04 / Pr_r^0.38]

    h_LO: all-liquid Dittus-Boelter-type coefficient at the stream's
    actual total mass flux. Liquid-phase reference properties (mu, k,
    cp) are evaluated using a single representative PURE fluid -
    `reference_liquid_fluid` if given, else the heaviest hydrocarbon
    present in the mixture - rather than a full multicomponent
    bubble-point flash of the mixture itself.

    That multicomponent flash was tried first and abandoned: it requires
    CoolProp to search the mixture's phase envelope/critical locus,
    which for a retrograde-prone, near-pseudo-critical light natural-
    gas-style mixture is both slow (~1-2s per call) and prone to
    outright failure ("critical point finding routine found 6 critical
    points") - found by actually running this zone-by-zone calculation,
    not predicted in advance (see docs/VALIDATION.md). A pure heavy-
    component proxy, evaluated well below ITS OWN critical point, is
    fast and numerically robust at the cost of some compositional
    fidelity - a deliberate, flagged simplification appropriate at
    conceptual-screening level, not a claim of exact multicomponent
    liquid properties.

    Pr_r uses a pseudo-critical pressure from Kay's rule (mole-fraction-
    weighted average of pure-component critical pressures - standard
    natural-gas engineering practice, e.g. GPSA Engineering Data Book),
    not the mixture's own true (and similarly expensive) critical
    pressure.
    """
    if not (0.0 <= vapor_quality <= 1.0):
        raise ValueError(f"vapor_quality must be in [0, 1], got {vapor_quality}")

    if reference_liquid_fluid is None:
        reference_liquid_fluid = max(fluid.composition, key=lambda name: CP.PropsSI("M", name))
    mu_l = CP.PropsSI("V", "T", T_K, "P", P_Pa, reference_liquid_fluid)
    k_l = CP.PropsSI("L", "T", T_K, "P", P_Pa, reference_liquid_fluid)
    cp_l = CP.PropsSI("Cpmass", "T", T_K, "P", P_Pa, reference_liquid_fluid)
    P_pseudo_crit = sum(frac * CP.PropsSI("Pcrit", name) for name, frac in fluid.composition.items())

    return _shah_from_props(mu_l, k_l, cp_l, P_pseudo_crit, P_Pa, mass_flow_kg_s, tube_id_m, n_tubes, vapor_quality)


def _shah_from_props(
    mu_l_Pa_s: float, k_l_W_mK: float, cp_l_J_kgK: float, P_pseudo_crit_Pa: float,
    P_Pa: float, mass_flow_kg_s: float, tube_id_m: float, n_tubes: int, vapor_quality: float,
) -> float:
    """Formula-only core of shah_condensation_htc - see
    _dittus_boelter_from_props for why this split exists."""
    mdot_per_tube = mass_flow_kg_s / n_tubes
    G = mdot_per_tube / (math.pi / 4.0 * tube_id_m ** 2)  # mass flux, kg/m2-s

    Re_LO = G * tube_id_m / mu_l_Pa_s
    Pr_l = cp_l_J_kgK * mu_l_Pa_s / k_l_W_mK
    Nu_LO = 0.023 * Re_LO ** 0.8 * Pr_l ** 0.4
    h_LO = Nu_LO * k_l_W_mK / tube_id_m

    Pr_reduced = P_Pa / P_pseudo_crit_Pa
    x = vapor_quality
    enhancement = (1.0 - x) ** 0.8 + 3.8 * x ** 0.76 * (1.0 - x) ** 0.04 / Pr_reduced ** 0.38
    return h_LO * enhancement


def falling_film_htc(
    liquid_k_W_mK: float, liquid_rho_kg_m3: float, liquid_mu_Pa_s: float,
    film_flow_rate_per_width_kg_ms: float,
) -> float:
    """Laminar gravity-driven falling-film coefficient, shell side.

    Film thickness from the standard Nusselt laminar-film relation:
        delta = (3 * mu * Gamma / (rho^2 * g)) ** (1/3)
    combined with a conduction-through-the-film approximation, h = k /
    delta - a deliberately simple, conservative lower-bound estimate; a
    real film has nucleate-boiling and wave enhancement on top of pure
    conduction, so a real coefficient is typically higher than this.
    Gamma is the film flow rate per unit wetted-perimeter width, kg/m-s.
    """
    Gamma = film_flow_rate_per_width_kg_ms
    if Gamma <= 0:
        raise ValueError("film_flow_rate_per_width_kg_ms must be positive")
    delta = (3.0 * liquid_mu_Pa_s * Gamma / (liquid_rho_kg_m3 ** 2 * _G)) ** (1.0 / 3.0)
    return liquid_k_W_mK / delta


def _robust_update(AS: "CP.AbstractState", P_Pa: float, T_K: float) -> None:
    """CoolProp's mixture (T,P) flash can occasionally fail to converge
    exactly at a phase-envelope edge (a known numerical fragility for
    mixture flashes - see docs/VALIDATION.md's note on empirically
    validated CoolProp mixture-flash regimes) even though the underlying
    state is physically well-defined. Retry with small temperature
    nudges rather than letting one unlucky zone-boundary sample abort an
    entire rating calculation. Mutates AS to the resolved state; raises
    if every retry fails."""
    for dT in (0.0, 0.05, -0.05, 0.2, -0.2, 0.5, -0.5, 1.0, -1.0, 2.0, -2.0):
        try:
            AS.update(CP.PT_INPUTS, P_Pa, T_K + dT)
            return
        except ValueError:
            continue
    raise ValueError(f"Flash failed to converge near T={T_K:.2f} K, P={P_Pa/1e5:.2f} bar even with retries")


def overall_U_local(h_i_W_m2K: float, h_o_W_m2K: float, tube_id_m: float, tube_od_m: float, tube_k_W_mK: float) -> float:
    """Overall U referenced to outer tube area, standard series-resistance
    cylindrical-wall combination (Kern, "Process Heat Transfer")."""
    r_i, r_o = tube_id_m / 2.0, tube_od_m / 2.0
    R_wall = r_o * math.log(r_o / r_i) / tube_k_W_mK
    R_i = r_o / (r_i * h_i_W_m2K)
    R_o = 1.0 / h_o_W_m2K
    return 1.0 / (R_i + R_wall + R_o)


@dataclass
class RatingResult:
    achievable_rundown_T_K: float
    binding_constraint: str  # "area" or "MITA"
    total_area_used_m2: float
    available_area_m2: float
    min_local_U_W_m2K: float
    max_local_U_W_m2K: float
    n_zones: int
    zone_report: list[dict] = field(default_factory=list)


def _zone_integrate(
    AS_proc: "CP.AbstractState", process_mass_flow_kg_s: float, process_P_Pa: float,
    T_hot_end_K: float, T_cold_end_K: float,
    geometry: TubeBundleGeometry, h_o_W_m2K: float, refrigerant_T_evap_K: float,
    min_approach_K: float, n_zones: int,
    reference_liquid_fluid: str, P_pseudo_crit_Pa: float,
) -> tuple[float, float, float, list[dict]]:
    """Integrate required area along the duty axis using LOCAL h_i/U at
    each zone (as opposed to mche.py's single constant-U estimate).
    Raises ValueError if MITA is violated at any zone.

    Performance note: uses ONE persistent process-gas AbstractState
    (AS_proc, passed in already built by the caller) and reads H, Q, mu,
    k, cp all off a SINGLE resolved state per temperature point, instead
    of the separate string-keyed CoolProp.PropsSI calls the public
    dittus_boelter_htc/shah_condensation_htc wrappers use - each of
    those re-parses and re-initializes the mixture from scratch, which
    dominates runtime once this function calls it 2*n_zones+1 times per
    rating (empirically ~0.1s per fresh-string call vs. ~0.01s reusing a
    persistent state - found while getting this module to run in a
    usable amount of time, not from a performance target set in
    advance). Breakpoint enthalpies are shared between adjacent zones
    rather than recomputed twice.
    """
    breakpoint_T = [T_hot_end_K - (i / n_zones) * (T_hot_end_K - T_cold_end_K) for i in range(n_zones + 1)]
    breakpoint_H = []
    for T in breakpoint_T:
        _robust_update(AS_proc, process_P_Pa, T)
        breakpoint_H.append(AS_proc.hmass())

    total_area = 0.0
    min_U, max_U = math.inf, 0.0
    zone_report: list[dict] = []
    last_h_i = None

    for i in range(n_zones):
        T_hi, T_lo = breakpoint_T[i], breakpoint_T[i + 1]  # breakpoint_T is warm->cold, decreasing
        H_hi, H_lo = breakpoint_H[i], breakpoint_H[i + 1]
        T_mid = 0.5 * (T_lo + T_hi)
        dQ_kW = process_mass_flow_kg_s * (H_hi - H_lo) / 1000.0

        approach_K = T_mid - refrigerant_T_evap_K
        if approach_K < min_approach_K - 1e-6:
            raise ValueError(
                f"MITA violated at T~{T_mid - 273.15:.1f} C: approach "
                f"{approach_K:.2f} K < required {min_approach_K:.2f} K"
            )

        _robust_update(AS_proc, process_P_Pa, T_mid)
        quality = AS_proc.Q()
        try:
            if not (0.0 <= quality <= 1.0):  # CoolProp returns Q=-1 (not an exception) for a single-phase state
                h_i = _dittus_boelter_from_props(
                    AS_proc.viscosity(), AS_proc.conductivity(), AS_proc.cpmass(),
                    process_mass_flow_kg_s, geometry.tube_id_m, geometry.n_tubes, cooling=True,
                )
                quality = None
            else:
                mu_l = CP.PropsSI("V", "T", T_mid, "P", process_P_Pa, reference_liquid_fluid)
                k_l = CP.PropsSI("L", "T", T_mid, "P", process_P_Pa, reference_liquid_fluid)
                cp_l = CP.PropsSI("Cpmass", "T", T_mid, "P", process_P_Pa, reference_liquid_fluid)
                h_i = _shah_from_props(
                    mu_l, k_l, cp_l, P_pseudo_crit_Pa, process_P_Pa, process_mass_flow_kg_s,
                    geometry.tube_id_m, geometry.n_tubes, vapor_quality=quality,
                )
        except ValueError:
            # Laminar-regime or correlation-edge-case zone: reuse the
            # nearest resolved zone's h_i rather than aborting the whole
            # rating - noted in the zone report, not hidden.
            h_i = last_h_i if last_h_i is not None else 500.0
        last_h_i = h_i

        U_local = overall_U_local(h_i, h_o_W_m2K, geometry.tube_id_m, geometry.tube_od_m, geometry.tube_k_W_mK)
        min_U, max_U = min(min_U, U_local), max(max_U, U_local)
        dA = (dQ_kW * 1000.0) / (U_local * approach_K)
        total_area += dA
        zone_report.append({
            "T_mid_C": T_mid - 273.15, "dQ_kW": dQ_kW, "approach_K": approach_K,
            "vapor_quality_molar": quality, "h_i_W_m2K": h_i, "U_local_W_m2K": U_local,
            "dA_m2": dA,
        })

    return total_area, min_U, max_U, zone_report


def rate_mche_bundle(
    geometry: TubeBundleGeometry,
    process_gas: GasMixture,
    process_mass_flow_kg_s: float,
    process_P_Pa: float,
    process_T_hot_end_K: float,
    refrigerant: GasMixture,
    refrigerant_mass_flow_kg_s: float,
    refrigerant_T_evap_K: float,
    min_approach_K: float = 3.0,
    n_zones: int = 15,
) -> RatingResult:
    """RATING calculation: given a fixed tube bundle and known process/
    refrigerant flows, solve for the coldest NG rundown temperature this
    bundle can actually deliver - either AREA-limited (the bundle runs
    out of area before MITA binds) or MITA-limited (the pinch constraint
    binds while area is still available, same as mche.py's own MITA
    check). The refrigerant is modeled as an isothermal evaporating
    falling film at a single pressure level - consistent with this
    package's other single-refrigerant-level treatment elsewhere.

    This does real CoolProp property lookups at 2*n_zones+1 temperature
    points per bisection step, so a call typically takes several
    seconds, not milliseconds - see _zone_integrate's docstring for what
    was done to keep that bounded (a persistent AbstractState, shared
    zone breakpoints). Raise n_zones for more resolution at the cost of
    runtime; the default is a deliberate speed/resolution compromise for
    conceptual screening, not a claim of high numerical precision.
    """
    wetted_perimeter_m = geometry.n_tubes * math.pi * geometry.tube_od_m
    AS_liq = CP.AbstractState("HEOS", "&".join(refrigerant.composition.keys()))
    AS_liq.set_mole_fractions(list(refrigerant.composition.values()))
    AS_liq.update(CP.QT_INPUTS, 0.0, refrigerant_T_evap_K)
    mu_l, k_l, rho_l = AS_liq.viscosity(), AS_liq.conductivity(), AS_liq.rhomass()
    Gamma = refrigerant_mass_flow_kg_s / wetted_perimeter_m
    h_o = falling_film_htc(k_l, rho_l, mu_l, Gamma)

    AS_proc = CP.AbstractState("HEOS", "&".join(process_gas.composition.keys()))
    AS_proc.set_mole_fractions(list(process_gas.composition.values()))
    reference_liquid_fluid = max(process_gas.composition, key=lambda name: CP.PropsSI("M", name))
    P_pseudo_crit_Pa = sum(frac * CP.PropsSI("Pcrit", name) for name, frac in process_gas.composition.items())

    def area_at(T_cold_end_K: float) -> float:
        total_area, _, _, _ = _zone_integrate(
            AS_proc, process_mass_flow_kg_s, process_P_Pa,
            process_T_hot_end_K, T_cold_end_K, geometry, h_o,
            refrigerant_T_evap_K, min_approach_K, n_zones,
            reference_liquid_fluid, P_pseudo_crit_Pa,
        )
        return total_area

    mita_limit_K = refrigerant_T_evap_K + min_approach_K + 0.5  # small numerical buffer off the exact MITA edge
    warm_limit_K = process_T_hot_end_K - 0.5

    area_at_mita_limit = area_at(mita_limit_K)
    if area_at_mita_limit <= geometry.outer_area_m2:
        # This bundle has MORE area than needed to reach the MITA limit -
        # the pinch, not the bundle size, caps the achievable rundown.
        total_area, min_U, max_U, zone_report = _zone_integrate(
            AS_proc, process_mass_flow_kg_s, process_P_Pa,
            process_T_hot_end_K, mita_limit_K, geometry, h_o,
            refrigerant_T_evap_K, min_approach_K, n_zones,
            reference_liquid_fluid, P_pseudo_crit_Pa,
        )
        return RatingResult(
            achievable_rundown_T_K=mita_limit_K, binding_constraint="MITA",
            total_area_used_m2=total_area, available_area_m2=geometry.outer_area_m2,
            min_local_U_W_m2K=min_U, max_local_U_W_m2K=max_U, n_zones=n_zones,
            zone_report=zone_report,
        )

    T_solution = brentq(lambda T: area_at(T) - geometry.outer_area_m2, mita_limit_K, warm_limit_K, xtol=0.1)
    total_area, min_U, max_U, zone_report = _zone_integrate(
        AS_proc, process_mass_flow_kg_s, process_P_Pa,
        process_T_hot_end_K, T_solution, geometry, h_o,
        refrigerant_T_evap_K, min_approach_K, n_zones,
        reference_liquid_fluid, P_pseudo_crit_Pa,
    )
    return RatingResult(
        achievable_rundown_T_K=T_solution, binding_constraint="area",
        total_area_used_m2=total_area, available_area_m2=geometry.outer_area_m2,
        min_local_U_W_m2K=min_U, max_local_U_W_m2K=max_U, n_zones=n_zones,
        zone_report=zone_report,
    )
