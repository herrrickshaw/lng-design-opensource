"""Boil-off gas (BOG) compressor conceptual sizing.

The BOG compressor takes the tank vapor header (cold, ~-140 to -120 C,
~1.1 bara, nitrogen-rich - see `tank_bog.py`) up to the recondenser
pressure (~7-10 bara) or, for the direct-to-pipeline case, on to send-out
pressure. This module wraps the package's polytropic-head method
(`compressor.py`, GPSA Ch. 13) with the things that are specific to
cryogenic BOG duty:

* **Gas is the real BOG, not LNG.** Composition comes from
  `tank_bog.TankLiquidState.bog_mole_fractions`. A nitrogen-rich BOG has a
  lower molecular weight and different k than the liquid it came from, and
  head scales inversely with molecular weight, so sizing on LNG
  composition undersizes the driver.
* **Cold suction.** Polytropic head is proportional to suction temperature
  (H_p ~ Z R T_in ...), so a -130 C suction needs roughly half the power
  per kg of the same duty at +25 C. This is the whole reason BOG is
  compressed cold rather than warmed first (regression test in
  tests/test_bog_compressor.py checks the T-scaling against the
  closed-form ideal-gas result).
* **Stage count from a maximum pressure ratio per stage**, not a fixed
  number: n = ceil(ln(PR) / ln(PR_stage_max)).
* **Design flow = design BOG x margin**, split over `n_operating`
  machines with `n_spare` standbys (2x100 % and 3x50 % are the two common
  arrangements; caller chooses).
* **Turndown**: holding-mode BOG is a small fraction of unloading-mode
  BOG, so the smallest stable flow of the machine matters as much as its
  rated flow; `turndown_check` flags it.

Machine-type guidance is deliberately coarse: below the smallest centrifugal
frame in `equipment_catalog.COMPRESSOR_FRAMES` the result says a
positive-displacement (reciprocating) machine is the usual choice, above
the largest it says add parallel machines. Vendor curves supersede the
frame table.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .compressor import CompressorStageResult, size_multistage
from .equipment_catalog import COMPRESSOR_FRAMES, CompressorFrame, select_compressor_frame
from .properties import GasMixture


@dataclass
class BOGCompressorResult:
    design_flow_kg_s: float
    flow_per_machine_kg_s: float
    n_operating: int
    n_spare: int
    n_stages: int
    stage_pressure_ratio: float
    suction_T_K: float
    suction_P_Pa: float
    suction_density_kg_m3: float
    inlet_volume_flow_per_machine_m3_h: float
    stages: list[CompressorStageResult]
    gas_power_kW_per_machine: float
    shaft_power_kW_per_machine: float
    installed_shaft_power_kW: float
    discharge_T_K: float
    specific_power_kWh_per_t: float
    frame: CompressorFrame | None
    machine_note: str
    bog_molecular_weight_g_mol: float


def _clean(comp: dict[str, float]) -> dict[str, float]:
    kept = {k: v for k, v in comp.items() if v > 1e-10}
    tot = sum(kept.values())
    return {k: v / tot for k, v in kept.items()}


def size_bog_compressor(
    bog_composition: dict[str, float],
    design_bog_kg_s: float,
    suction_P_Pa: float,
    discharge_P_Pa: float,
    suction_T_K: float = 143.15,
    margin: float = 0.10,
    n_operating: int = 1,
    n_spare: int = 1,
    max_stage_ratio: float = 2.5,
    polytropic_efficiency: float = 0.78,
    mechanical_efficiency: float = 0.97,
    interstage_cooling_to_K: float | None = None,
) -> BOGCompressorResult:
    """Size the BOG compressor bank.

    suction_P_Pa: at the compressor flange (tank pressure minus header/K.O.
    drum loss - subtract it yourself; a few kPa matters at 1.1 bara).
    suction_T_K: 143 K (-130 C) is a mid-range header temperature that
    includes heat pick-up along the vapor line; it is an input, not a
    derived value. Must sit above the BOG dew point at suction_P.
    max_stage_ratio: 2.5 per stage is an assumption typical of multistage
    centrifugal machines in this duty; vendor-specific.
    """
    if n_operating < 1 or n_spare < 0:
        raise ValueError("n_operating must be >= 1 and n_spare >= 0")
    if discharge_P_Pa <= suction_P_Pa:
        raise ValueError("discharge pressure must exceed suction pressure")
    gas = GasMixture(_clean(bog_composition))

    dew = None
    try:
        import CoolProp.CoolProp as CP
        s = CP.AbstractState("HEOS", "&".join(gas.composition.keys()))
        s.set_mole_fractions(list(gas.composition.values()))
        s.update(CP.PQ_INPUTS, suction_P_Pa, 1.0)
        dew = s.T()
    except Exception:  # dew point is a guard, not the result
        pass
    if dew is not None and suction_T_K <= dew + 1.0:
        raise ValueError(
            f"Suction T {suction_T_K:.1f} K is within 1 K of the BOG dew point "
            f"({dew:.1f} K) at {suction_P_Pa/1e5:.2f} bar - liquid carry-over risk."
        )

    flow = design_bog_kg_s * (1.0 + margin)
    per_machine = flow / n_operating
    pr = discharge_P_Pa / suction_P_Pa
    n_stages = max(1, math.ceil(math.log(pr) / math.log(max_stage_ratio)))

    stages = size_multistage(
        gas, suction_T_K, suction_P_Pa, discharge_P_Pa, per_machine, n_stages,
        polytropic_efficiency, interstage_cooling_to_K,
    )
    gas_kW = sum(s.gas_power_kW for s in stages)
    shaft_kW = gas_kW / mechanical_efficiency

    rho = gas.density(suction_T_K, suction_P_Pa)
    q_m3_h = per_machine / rho * 3600.0

    frame: CompressorFrame | None = None
    if q_m3_h < COMPRESSOR_FRAMES[0].inlet_volume_flow_m3_h_min:
        note = (f"Inlet {q_m3_h:,.0f} m3/h is below the smallest centrifugal frame "
                f"({COMPRESSOR_FRAMES[0].inlet_volume_flow_m3_h_min:,.0f} m3/h): "
                "a positive-displacement (reciprocating) machine is the usual choice.")
    elif q_m3_h > COMPRESSOR_FRAMES[-1].inlet_volume_flow_m3_h_max:
        note = (f"Inlet {q_m3_h:,.0f} m3/h exceeds the largest frame: add parallel "
                "machines (raise n_operating).")
    else:
        frame = select_compressor_frame(q_m3_h)
        note = f"Centrifugal frame {frame.name} covers {q_m3_h:,.0f} m3/h."

    # Last stage discharge T: with interstage cooling the last stage's own
    # T_out_ideal is already what the polytropic relation gives.
    t_out = stages[-1].T_out_ideal
    return BOGCompressorResult(
        design_flow_kg_s=flow, flow_per_machine_kg_s=per_machine,
        n_operating=n_operating, n_spare=n_spare, n_stages=n_stages,
        stage_pressure_ratio=pr ** (1.0 / n_stages),
        suction_T_K=suction_T_K, suction_P_Pa=suction_P_Pa,
        suction_density_kg_m3=rho, inlet_volume_flow_per_machine_m3_h=q_m3_h,
        stages=stages, gas_power_kW_per_machine=gas_kW,
        shaft_power_kW_per_machine=shaft_kW,
        installed_shaft_power_kW=shaft_kW * (n_operating + n_spare),
        discharge_T_K=t_out,
        specific_power_kWh_per_t=shaft_kW * n_operating / (flow * 3.6),
        frame=frame, machine_note=note,
        bog_molecular_weight_g_mol=gas.molecular_weight(),
    )


def turndown_check(
    min_bog_kg_s: float,
    rated_flow_per_machine_kg_s: float,
    n_running: int = 1,
    min_stable_fraction: float = 0.60,
) -> tuple[float, bool]:
    """(fraction of rated flow at minimum BOG, ok?). min_stable_fraction
    0.60 is an assumed centrifugal turndown with inlet guide vanes; use the
    vendor's surge line. If not ok, the difference must be recycled
    (cooled back to suction) or the machine swapped for a reciprocating
    unit with step unloading."""
    frac = min_bog_kg_s / (rated_flow_per_machine_kg_s * n_running)
    return frac, frac >= min_stable_fraction
