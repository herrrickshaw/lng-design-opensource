"""Three-loop cascade refrigeration system: NG loop, Refrigerant (LRC)
loop, and PMR (pre-cooling mixed refrigerant) loop.

This models the structural pattern behind Linde's MFC (Mixed Fluid
Cascade) process - see `mche_vendor_selection.py` for the APCI-vs-Linde
background this is built on:

- **NG loop**: the natural gas process stream. Its total cooling duty
  splits into a precool portion (ambient down to an intermediate
  temperature) and a liquefaction portion (intermediate down to LNG
  temperature).
- **PMR loop** (pre-cooling mixed refrigerant): rejects heat to ambient
  (cooling water/air), same as `precool.py`'s propane cycle. Its
  evaporator absorbs heat from TWO sources - the NG precool duty AND the
  Refrigerant/LRC loop's condensing duty. This second source is the
  defining "cascade" link: each cycle pre-cools the next one down the
  temperature ladder, refrigerant cooling refrigerant, not just
  refrigerant cooling process gas.
- **Refrigerant (LRC) loop**: a light mixed-refrigerant blend that
  absorbs the NG liquefaction duty at cryogenic temperature, then -
  unlike a single-cycle precool loop - REJECTS its condensing heat to
  the PMR loop's cold duty rather than to ambient directly.

**PMR: pure propane by default, or a DMR-style mixed-refrigerant blend**:
`mixed_refrigerant_cycle` is general-purpose - it works for ANY
composition/temperature combination that is physically achievable, not
just cold-condensing. What does NOT work is a mismatch between blend and
target: an empirical check (see docs/VALIDATION.md) found that a light,
methane/nitrogen-rich blend suitable for the cryogenic LRC evaporator has
NO valid bubble point anywhere near ambient temperature at achievable
pressures (a composition light enough to evaporate at -100°C can't also
condense at +40°C without being much heavier) - CoolProp's mixture flash
solver fails outright on that mismatch rather than converging to a wrong
answer, which is itself useful (a loud failure, not silent nonsense). A
heavier blend (e.g. ethane/propane) DOES condense near ambient while
evaporating meaningfully colder than pure propane's ~-42°C atmospheric
floor - exactly the mechanism behind DMR's reported efficiency advantage
over a single-component C3 precool (see `process_selection.py`). By
default `three_loop_cascade`'s PMR loop reuses `precool.py`'s proven
pure-propane cycle (the simplest, most-proven baseline); pass
`pmr_refrigerant` to instead run it through `mixed_refrigerant_cycle`
with a heavier blend for the DMR-style comparison.

**A single mixed_refrigerant_cycle call cannot span the full precool-to-
LNG-rundown range**: found by running examples/full_train_worked_example.py
end to end, not predicted in advance. The example's LRC_BLEND (5/30/35/30
mol% N2/CH4/C2H6/C3H8) validates cleanly down to about -100°C, but the
isentropic-compression step fails to converge if pushed to span the full
-40°C-to--159°C liquefaction+subcooling range in one stage - too large a
compression ratio/temperature lift for this blend in a single step. Real
MFC/DMR designs use multiple refrigerant pressure levels (and, for MFC,
a third, lighter "SRC" subcooling cycle beyond the two refrigerant loops
this module models) for exactly this reason. Model a large span as
multiple sequential `mixed_refrigerant_cycle` calls at different
temperature levels rather than one call across the whole range.
"""
from __future__ import annotations

from dataclasses import dataclass

import CoolProp.CoolProp as CP

from .precool import PrecoolCycleResult, propane_cycle_power
from .properties import GasMixture


@dataclass
class MixedRefrigerantCycleResult:
    T_evap_K: float
    T_cond_K: float
    P_evap_Pa: float
    P_cond_Pa: float
    refrigerant_mass_flow_kg_s: float
    compressor_power_kW: float
    condensing_duty_kW: float


def mixed_refrigerant_cycle(
    refrigerant: GasMixture,
    duty_kW: float,
    T_evap_K: float,
    T_cond_K: float,
    isentropic_efficiency: float = 0.75,
) -> MixedRefrigerantCycleResult:
    """Single mixed-refrigerant vapor-compression cycle, validated for a
    COLD-condensing regime (T_cond well below ambient - the LRC/cascade
    use case). For an ambient-condensing precool cycle, use
    `precool.propane_cycle_power` (or another pure-fluid cycle) instead -
    see this module's docstring for why.
    """
    if T_cond_K <= T_evap_K:
        raise ValueError("T_cond_K must exceed T_evap_K")

    names = list(refrigerant.composition.keys())
    fracs = list(refrigerant.composition.values())
    fluid_string = "&".join(names)

    def _state():
        AS = CP.AbstractState("HEOS", fluid_string)
        AS.set_mole_fractions(fracs)
        return AS

    try:
        evap = _state()
        evap.update(CP.QT_INPUTS, 1.0, T_evap_K)  # dew point: evaporator outlet
        cond = _state()
        cond.update(CP.QT_INPUTS, 0.0, T_cond_K)  # bubble point: condenser outlet
    except ValueError as e:
        raise ValueError(
            f"No physically valid dew/bubble point for this refrigerant "
            f"composition at T_evap={T_evap_K:.1f} K / T_cond={T_cond_K:.1f} K. "
            "This usually means the blend is too light to condense at the "
            "target T_cond (e.g. an LRC-style blend used with an "
            "ambient-temperature T_cond) - try a colder T_cond or a heavier "
            "composition. See this module's docstring."
        ) from e

    P_evap, P_cond = evap.p(), cond.p()
    if P_cond <= P_evap:
        raise ValueError(
            f"Resolved condenser pressure ({P_cond/1e5:.2f} bar) does not "
            f"exceed evaporator pressure ({P_evap/1e5:.2f} bar) - infeasible cycle."
        )

    h1, s1 = evap.hmass(), evap.smass()
    h3 = cond.hmass()

    comp_state = _state()
    try:
        comp_state.update(CP.PSmass_INPUTS, P_cond, s1)
    except ValueError as e:
        raise ValueError(
            f"Isentropic compression from T_evap={T_evap_K:.1f} K to P_cond "
            f"({P_cond/1e5:.1f} bar) did not converge to a physical state for this "
            f"composition - found by actually running "
            "examples/full_train_worked_example.py, not predicted in advance (see "
            "docs/VALIDATION.md). This typically means the compression ratio/"
            "temperature lift is too large for a single stage with this blend "
            "(e.g. spanning the full precool-to-LNG-rundown range in one step, "
            "rather than the multiple refrigerant pressure levels a real MFC/DMR "
            "design would use). Try a smaller T_evap-to-T_cond span, or model "
            "the duty as two sequential mixed_refrigerant_cycle calls at "
            "different temperature levels instead of one."
        ) from e
    h2s = comp_state.hmass()
    h2 = h1 + (h2s - h1) / isentropic_efficiency

    refrig_effect = h1 - h3
    if refrig_effect <= 0:
        raise ValueError("Non-physical cycle: condenser enthalpy exceeds evaporator enthalpy")
    mdot = duty_kW * 1000.0 / refrig_effect
    power_kW = mdot * (h2 - h1) / 1000.0
    condensing_duty_kW = duty_kW + power_kW  # energy balance: Q_reject = Q_evap + W_compressor

    return MixedRefrigerantCycleResult(
        T_evap_K=T_evap_K, T_cond_K=T_cond_K, P_evap_Pa=P_evap, P_cond_Pa=P_cond,
        refrigerant_mass_flow_kg_s=mdot, compressor_power_kW=power_kW,
        condensing_duty_kW=condensing_duty_kW,
    )


@dataclass
class CascadeResult:
    lrc: MixedRefrigerantCycleResult
    pmr: PrecoolCycleResult
    pmr_total_duty_kW: float
    total_compressor_power_kW: float


def three_loop_cascade(
    ng_precool_duty_kW: float,
    ng_liquefaction_duty_kW: float,
    pmr_T_evap_K: float,
    pmr_T_cond_K: float,
    lrc_refrigerant: GasMixture,
    lrc_T_evap_K: float,
    lrc_T_cond_K: float,
    pmr_isentropic_efficiency: float = 0.75,
    lrc_isentropic_efficiency: float = 0.75,
    mita_K: float = 3.0,
    pmr_refrigerant: GasMixture | None = None,
) -> CascadeResult:
    """Solve the three-loop cascade for a fixed set of temperature levels
    (design conditions) - duties chain forward: the LRC loop's condensing
    heat rejection becomes an ADDITIONAL load on the PMR loop, on top of
    the NG precool duty. This is a direct (non-iterative) calculation
    because temperature levels are inputs here rather than solved for; a
    real MFC design would jointly optimize both, which is beyond a
    conceptual screening tool.

    The LRC loop condenses against the PMR loop's evaporating duty, not
    ambient - so heat must actually flow from the (warmer) LRC condenser
    to the (colder) PMR evaporator: this function enforces
    `lrc_T_cond_K >= pmr_T_evap_K + mita_K`, the same MITA discipline
    `mche.py` applies to the main cryogenic exchanger - a zero (or
    negative) approach here would need infinite heat-transfer area,
    exactly the mistake `mche.py`'s docstring warns about for the main
    exchanger.

    pmr_refrigerant: by default (None) the PMR loop uses
    `precool.propane_cycle_power` (pure propane, condensing at ambient,
    limited to roughly propane's -42 C atmospheric-pressure floor). Pass
    a GasMixture (e.g. a heavier ethane/propane blend) to instead run the
    PMR loop through `mixed_refrigerant_cycle` - the DMR-style precool
    option, which can evaporate meaningfully colder than pure propane
    while still condensing at ambient (verified empirically - see
    docs/VALIDATION.md - for e.g. a 30/70 mol% ethane/propane blend down
    to at least -60 C at 40 C ambient condensing, vs. propane's ~-42 C
    limit), at the cost of a second refrigerant inventory/composition to
    manage instead of pure propane.
    """
    if lrc_T_cond_K < pmr_T_evap_K + mita_K:
        raise ValueError(
            f"MITA violated between loops: LRC condenses at {lrc_T_cond_K:.1f} K but "
            f"PMR only evaporates at {pmr_T_evap_K:.1f} K (margin "
            f"{lrc_T_cond_K - pmr_T_evap_K:.1f} K, need >= {mita_K:.1f} K). Heat must "
            "flow from the LRC condenser to the PMR evaporator - raise lrc_T_cond_K, "
            "lower pmr_T_evap_K, or reduce mita_K if it was set unrealistically high."
        )

    lrc = mixed_refrigerant_cycle(
        lrc_refrigerant, ng_liquefaction_duty_kW, lrc_T_evap_K, lrc_T_cond_K,
        lrc_isentropic_efficiency,
    )

    pmr_total_duty = ng_precool_duty_kW + lrc.condensing_duty_kW
    if pmr_refrigerant is None:
        pmr = propane_cycle_power(pmr_total_duty, pmr_T_evap_K, pmr_T_cond_K, pmr_isentropic_efficiency)
    else:
        mr_result = mixed_refrigerant_cycle(
            pmr_refrigerant, pmr_total_duty, pmr_T_evap_K, pmr_T_cond_K, pmr_isentropic_efficiency,
        )
        pmr = PrecoolCycleResult(
            T_evap_K=pmr_T_evap_K, T_cond_K=pmr_T_cond_K,
            P_evap_Pa=mr_result.P_evap_Pa, P_cond_Pa=mr_result.P_cond_Pa,
            refrigerant_mass_flow_kg_s=mr_result.refrigerant_mass_flow_kg_s,
            compressor_power_kW=mr_result.compressor_power_kW,
            cop=pmr_total_duty / mr_result.compressor_power_kW,
        )

    return CascadeResult(
        lrc=lrc, pmr=pmr, pmr_total_duty_kW=pmr_total_duty,
        total_compressor_power_kW=lrc.compressor_power_kW + pmr.compressor_power_kW,
    )
