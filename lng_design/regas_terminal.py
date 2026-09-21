"""LNG regasification (send-out) train conceptual sizing.

Chain, tank to pipeline:

    tank -> in-tank (LP) pump -> [recondenser] -> HP send-out pump
         -> vaporizer (ORV on seawater, SCV as cold-water/peak backup)
         -> metering -> pipeline

Everything thermodynamic is a CoolProp HEOS mixture calculation, so the
duty of heating LNG through its pseudo-critical region at pipeline
pressure comes from real enthalpies, not from a latent-plus-sensible
shortcut (which is wrong at 70-100 bar, where there is no latent heat).

* **Pumps** (`size_lng_pump`): isentropic head from CoolProp at constant
  entropy, divided by pump efficiency; the outlet enthalpy carries the
  hydraulic losses (the pump discharges warmer than isentropic).
* **Vaporizer duty** (`vaporizer_duty`, `heating_curve`): h(T_out, P) -
  h(T_in, P) on the mixture.
* **ORV** (`size_orv`): seawater flow from the duty and an allowed
  seawater temperature drop, unit count from a per-unit capacity with
  spare units. Published open-rack-vaporizer ratings are ~150-200 t/h per
  unit with 5,000-10,000 t/h of seawater and require warm (>= ~5 C)
  seawater (Applied Thermal Engineering papers on super-open-rack-
  vaporizer thermal performance - full titles in docs/METHODOLOGY.md) - so
  ORV is flagged unusable when seawater is colder than `min_seawater_C`.
* **SCV** (`size_scv`): fuel gas from duty / (thermal efficiency x LHV of
  the fuel). LHV from standard enthalpies of combustion (NIST/CRC).
* **BOG recondenser** (`size_recondenser`): mixes compressed BOG with
  sub-cooled LNG to a slightly subcooled liquid outlet; solves the
  LNG/BOG mass ratio from an enthalpy balance on the *mixed* composition
  (BOG is nitrogen-rich, so the mixture is not LNG composition), and from
  it the maximum BOG the recondenser can absorb at a given send-out rate.

Not modeled: vaporizer surface area (needs a vendor heat-transfer
coefficient for the panel/tube geometry - the ORV count is capacity-based,
as in a real front-end study), seawater intake/outfall hydraulics,
recondenser packed-bed/vessel hydraulics, and send-out metering.
"""
from __future__ import annotations

from dataclasses import dataclass

import CoolProp.CoolProp as CP
import numpy as np
from scipy.optimize import brentq

from .end_flash import _MW_G_MOL

CP_SEAWATER_J_KG_K = 3990.0   # 35 g/kg salinity, ~15-20 C (Sharqawy et al. 2010)
RHO_SEAWATER_KG_M3 = 1025.0

# Standard enthalpy of combustion (HHV, gas, 25 C), kJ/mol - NIST WebBook /
# CRC Handbook. LHV = HHV - n_H2O * 44.01 kJ/mol (water vaporization at 25 C).
_HHV_KJ_MOL = {
    "Methane": (890.6, 2), "Ethane": (1560.7, 3), "Propane": (2219.2, 4),
    "n-Butane": (2877.5, 5), "Isobutane": (2868.2, 5), "i-Butane": (2868.2, 5),
    "Nitrogen": (0.0, 0),
}
_H_VAP_WATER_KJ_MOL = 44.01


def lhv_MJ_per_kg(composition: dict[str, float]) -> float:
    """Lower heating value of a mole-fraction mixture, MJ/kg."""
    mol_kJ = 0.0
    mw = 0.0
    for name, x in composition.items():
        if name not in _HHV_KJ_MOL or name not in _MW_G_MOL:
            raise ValueError(f"No combustion data for '{name}' - add to _HHV_KJ_MOL")
        hhv, n_h2o = _HHV_KJ_MOL[name]
        mol_kJ += x * (hhv - n_h2o * _H_VAP_WATER_KJ_MOL)
        mw += x * _MW_G_MOL[name]
    return mol_kJ / (mw / 1000.0) / 1000.0  # kJ/mol / (kg/mol) -> kJ/kg -> MJ/kg


def _as(composition: dict[str, float]) -> "CP.AbstractState":
    names = [n for n, x in composition.items() if x > 1e-12]
    fr = np.array([composition[n] for n in names])
    s = CP.AbstractState("HEOS", "&".join(names))
    s.set_mole_fractions(list(fr / fr.sum()))
    return s


# Offsets (K) tried in turn when CoolProp's mixture PT flash returns a
# non-physical state. The bad windows are not all 1e-6 K wide (a second one
# near 125.69 K at 85 bar survived eight 1e-5 K nudges), so the sequence
# grows geometrically to 0.1 K; the property error from moving 0.1 K on a
# liquid/dense fluid is ~0.3 kJ/kg (~0.05 % of a 700 kJ/kg duty).
_NUDGES_K = (0.0, 1e-5, -1e-5, 1e-4, -1e-4, 1e-3, -1e-3, 1e-2, -1e-2, 0.1, -0.1)


def _dense_pressure_Pa(state: "CP.AbstractState") -> float:
    """Pressure above which every mixture of these components is a dense
    supercritical fluid at any temperature: 1.3 x the largest component
    critical pressure (LNG-range mixture critical pressures stay below
    ~60 bar; the largest pure Pc here is 48.7 bar for ethane)."""
    names = state.fluid_names()
    return 1.3 * max(CP.PropsSI("Pcrit", n) for n in names)


def _update_PT(state: "CP.AbstractState", P: float, T: float) -> None:
    """(T, P) update that skips CoolProp's phase-stability analysis when the
    answer is known - the analysis is what misfires. Above `_dense_pressure`
    the fluid is supercritical, so that phase is imposed; the scan in
    docs/VALIDATION.md shows 0 bad points out of 248 with the imposed phase
    vs 3 out of 248 with automatic detection, on the 85 bar LNG isobar."""
    state.unspecify_phase()
    if P >= _dense_pressure_Pa(state):
        state.specify_phase(CP.iphase_supercritical)
    state.update(CP.PT_INPUTS, P, T)


def _h_PT(state: "CP.AbstractState", P: float, T: float, h_prev: float | None = None) -> float:
    """Enthalpy at (T, P), guarded against a CoolProp mixture-flash flake.

    Found by running the app: for this 5-component LNG at 85 bar,
    PT_INPUTS at exactly T = 136.435 K returns a "gas" state with
    h = -40,000 kJ/kg (correct: ~71 kJ/kg) while 1e-6 K away it is fine.
    Along an isobar h must rise with T, so when the caller supplies the
    previous point's enthalpy a non-increasing result is treated as the
    flake and re-evaluated a hair away (`_NUDGES_K`).
    """
    for dT in _NUDGES_K:
        try:
            _update_PT(state, P, T + dT)
            h = state.hmass()
        except ValueError:
            continue
        if h_prev is None or (h_prev < h < h_prev + 5e6):
            return h
    raise ValueError(
        f"CoolProp returned a non-physical enthalpy near T={T:.3f} K, P={P/1e5:.1f} bar "
        "(mixture flash failure); nudge the temperature by ~0.01 K."
    )


def _norm(comp: dict[str, float]) -> dict[str, float]:
    tot = sum(comp.values())
    if abs(tot - 1.0) > 1e-6:
        raise ValueError(f"Mole fractions must sum to 1.0, got {tot}")
    return comp


# ---------------------------------------------------------------------
# Pumps
# ---------------------------------------------------------------------

@dataclass
class PumpResult:
    hydraulic_kW: float
    shaft_kW: float
    outlet_T_K: float
    temperature_rise_K: float
    liquid_density_kg_m3: float
    volumetric_flow_m3_h: float
    differential_head_m: float


def size_lng_pump(
    composition: dict[str, float],
    T_in_K: float,
    P_in_Pa: float,
    P_out_Pa: float,
    mass_flow_kg_s: float,
    efficiency: float = 0.75,
) -> PumpResult:
    """Cryogenic centrifugal pump: isentropic head from CoolProp, real
    outlet state from hydraulic efficiency. T_in/P_in must be a compressed
    (sub-cooled) liquid state - a saturated suction cavitates."""
    _norm(composition)
    if not (0.0 < efficiency <= 1.0):
        raise ValueError("efficiency must be in (0, 1]")
    if P_out_Pa <= P_in_Pa:
        raise ValueError("P_out must exceed P_in for a pump")
    s1 = _as(composition)
    s1.update(CP.PT_INPUTS, P_in_Pa, T_in_K)
    if s1.phase() not in (CP.iphase_liquid, CP.iphase_supercritical_liquid):
        raise ValueError("Pump suction is not a sub-cooled liquid (raise P_in or cool T_in)")
    h1, s, rho = s1.hmass(), s1.smass(), s1.rhomass()

    # Solve the outlet temperature by root-finding on (T, P) states rather
    # than CoolProp's PS/HP flash: for a dense multicomponent liquid at
    # 85 bar the mixture PS flash intermittently fails to converge
    # ("misclassifying the phase"), found while testing this module (see
    # docs/VALIDATION.md). The (T, P) liquid state is always robust.
    st_out = _as(composition)

    def _val(prop: str, T: float, ref: float, span: float) -> float:
        """Property at (T, P_out), rejecting CoolProp's mixture-flash flake
        (see `_h_PT`): a value further from `ref` than any physical pump
        step can be is re-evaluated a hair away."""
        for dT in _NUDGES_K:
            try:
                st_out.unspecify_phase()
                if P_out_Pa >= _dense_pressure_Pa(st_out):
                    st_out.specify_phase(CP.iphase_supercritical)
                else:
                    st_out.specify_phase(CP.iphase_liquid)   # compressed liquid at pump outlet
                st_out.update(CP.PT_INPUTS, P_out_Pa, T + dT)
                v = getattr(st_out, prop)()
            except ValueError:
                continue
            if abs(v - ref) < span:
                return v
        raise ValueError(
            f"CoolProp mixture flash failed near T={T:.3f} K, P={P_out_Pa/1e5:.1f} bar; "
            "nudge the suction temperature by ~0.01 K.")

    def _T_where(prop: str, target: float, ref: float, span: float) -> float:
        # Bracket: a pump warms the liquid by a few K at most; staying well
        # under the bubble point keeps every trial state a compressed liquid.
        return brentq(lambda T: _val(prop, T, ref, span) - target,
                      T_in_K - 2.0, T_in_K + 15.0, xtol=1e-9)

    # Spans: 1e6 J/kg of enthalpy and 1e4 J/kg-K of entropy dwarf any real
    # step over the 17 K bracket (~1e5 J/kg, ~4e2 J/kg-K) but exclude the
    # garbage values (1e9) the flake returns.
    T_s = _T_where("smass", s, s, 1e4)
    dh_s = _val("hmass", T_s, h1, 1e6) - h1
    shaft = mass_flow_kg_s * dh_s / efficiency
    T_out = _T_where("hmass", h1 + dh_s / efficiency, h1, 1e6)
    return PumpResult(
        hydraulic_kW=mass_flow_kg_s * dh_s / 1000.0, shaft_kW=shaft / 1000.0,
        outlet_T_K=T_out, temperature_rise_K=T_out - T_in_K,
        liquid_density_kg_m3=rho, volumetric_flow_m3_h=mass_flow_kg_s / rho * 3600.0,
        differential_head_m=dh_s / 9.80665,
    )


# ---------------------------------------------------------------------
# Vaporizer duty
# ---------------------------------------------------------------------

def vaporizer_duty(
    composition: dict[str, float], P_Pa: float, T_in_K: float, T_out_K: float,
    mass_flow_kg_s: float,
) -> float:
    """Heat needed to take LNG at (T_in, P) to gas at (T_out, P), kW."""
    _norm(composition)
    st = _as(composition)
    h_in = _h_PT(st, P_Pa, T_in_K)
    h_out = _h_PT(st, P_Pa, T_out_K, h_in)
    return mass_flow_kg_s * (h_out - h_in) / 1000.0


def heating_curve(
    composition: dict[str, float], P_Pa: float, T_in_K: float, T_out_K: float,
    mass_flow_kg_s: float, n_points: int = 60,
) -> tuple[np.ndarray, np.ndarray]:
    """(T [K], cumulative duty [kW]) along the heating path - shows the
    pseudo-critical heat-capacity spike that dictates where the vaporizer
    panel/tube is thermally hardest."""
    T = np.linspace(T_in_K, T_out_K, n_points)
    s = _as(composition)
    h0 = _h_PT(s, P_Pa, T_in_K)
    Q, h_prev = [0.0], h0
    for t in T[1:]:
        h_prev = _h_PT(s, P_Pa, float(t), h_prev)
        Q.append(mass_flow_kg_s * (h_prev - h0) / 1000.0)
    return T, np.array(Q)


# ---------------------------------------------------------------------
# ORV / SCV
# ---------------------------------------------------------------------

@dataclass
class ORVResult:
    duty_kW: float
    seawater_flow_t_h: float
    seawater_flow_m3_h: float
    seawater_outlet_C: float
    n_operating: int
    n_spare: int
    usable: bool
    note: str


def size_orv(
    duty_kW: float,
    lng_flow_kg_s: float,
    seawater_in_C: float,
    seawater_dT_K: float = 5.0,
    unit_capacity_t_h: float = 180.0,
    n_spare: int = 1,
    min_seawater_C: float = 5.0,
) -> ORVResult:
    """Open-rack vaporizer bank.

    seawater_dT_K: allowed seawater temperature drop, set by the outfall
    environmental limit (~5 K is a common permit value; a site input).
    unit_capacity_t_h: 180 t/h sits mid-range of the published 150-200 t/h
    ORV/SuperORV rating; replace with the vendor's figure.
    min_seawater_C: below this the panels ice - use the SCV instead.
    """
    if seawater_dT_K <= 0:
        raise ValueError("seawater_dT_K must be positive")
    m_sw = duty_kW * 1000.0 / (CP_SEAWATER_J_KG_K * seawater_dT_K)  # kg/s
    n_op = int(np.ceil(lng_flow_kg_s * 3.6 / unit_capacity_t_h))
    T_out = seawater_in_C - seawater_dT_K
    usable = seawater_in_C >= min_seawater_C
    note = "OK" if usable else (
        f"Seawater {seawater_in_C:.1f} C is below the ~{min_seawater_C:.0f} C ORV limit "
        "(ice on the panels): size the SCV bank for this duty instead."
    )
    return ORVResult(
        duty_kW=duty_kW, seawater_flow_t_h=m_sw * 3.6,
        seawater_flow_m3_h=m_sw / RHO_SEAWATER_KG_M3 * 3600.0,
        seawater_outlet_C=T_out, n_operating=n_op, n_spare=n_spare,
        usable=usable, note=note,
    )


@dataclass
class SCVResult:
    duty_kW: float
    fuel_gas_kg_s: float
    fuel_fraction_of_sendout: float
    n_operating: int
    n_spare: int


def size_scv(
    duty_kW: float,
    sendout_gas: dict[str, float],
    lng_flow_kg_s: float,
    thermal_efficiency: float = 0.98,
    unit_capacity_t_h: float = 100.0,
    n_spare: int = 1,
) -> SCVResult:
    """Submerged-combustion vaporizer: burns part of the send-out gas.
    thermal_efficiency (LHV basis) 0.98 and 100 t/h/unit are ASSUMED
    screening values (not from a cited source) - replace with vendor data."""
    lhv = lhv_MJ_per_kg(sendout_gas) * 1000.0  # kJ/kg
    fuel = duty_kW / (thermal_efficiency * lhv)
    return SCVResult(
        duty_kW=duty_kW, fuel_gas_kg_s=fuel, fuel_fraction_of_sendout=fuel / lng_flow_kg_s,
        n_operating=int(np.ceil(lng_flow_kg_s * 3.6 / unit_capacity_t_h)), n_spare=n_spare,
    )


# ---------------------------------------------------------------------
# BOG recondenser
# ---------------------------------------------------------------------

@dataclass
class RecondenserResult:
    lng_to_bog_mass_ratio: float
    lng_required_kg_s: float
    outlet_T_K: float
    outlet_composition: dict[str, float]
    max_recondensable_bog_kg_s: float
    recondensed_bog_kg_s: float
    excess_bog_kg_s: float


def _mass_to_mole(comp_mass: dict[str, float]) -> dict[str, float]:
    n = {k: v / _MW_G_MOL[k] for k, v in comp_mass.items()}
    tot = sum(n.values())
    return {k: v / tot for k, v in n.items()}


def _mole_to_mass_flow(comp: dict[str, float], mdot: float) -> dict[str, float]:
    w = {k: x * _MW_G_MOL[k] for k, x in comp.items()}
    tot = sum(w.values())
    return {k: mdot * v / tot for k, v in w.items()}


def size_recondenser(
    lng_composition: dict[str, float],
    lng_T_K: float,
    bog_composition: dict[str, float],
    bog_T_K: float,
    bog_flow_kg_s: float,
    pressure_Pa: float,
    available_lng_kg_s: float,
    outlet_subcooling_K: float = 2.0,
) -> RecondenserResult:
    """Energy balance BOG + LNG -> subcooled liquid at `pressure_Pa`.

    Solved for the LNG/BOG mass ratio r by root-finding, with the outlet
    composition recomputed from the mixed mass flows at each trial r.
    `available_lng_kg_s` is the send-out LNG passing the recondenser; if
    BOG exceeds what that flow can absorb, the excess must go to a
    direct-to-pipeline compressor (or flare) - reported as excess_bog.
    """
    _norm(lng_composition); _norm(bog_composition)
    species = sorted(set(lng_composition) | set(bog_composition))
    lng = {k: lng_composition.get(k, 0.0) for k in species}
    bog = {k: bog_composition.get(k, 0.0) for k in species}

    # Reused states (constructing a mixture is ~0.1 s; re-setting is cheap).
    # Zero fractions are floored so every species stays in the state.
    st_a = CP.AbstractState("HEOS", "&".join(species))
    st_b = CP.AbstractState("HEOS", "&".join(species))

    def _set(state, comp):
        v = np.array([max(comp[k], 1e-10) for k in species])
        state.set_mole_fractions(list(v / v.sum()))

    def h_stream(comp, T):
        _set(st_a, comp); st_a.update(CP.PT_INPUTS, pressure_Pa, T)
        return st_a.hmass()

    h_lng = h_stream(lng, lng_T_K)
    h_bog = h_stream(bog, bog_T_K)
    lng_mass = _mole_to_mass_flow(lng, 1.0)
    bog_mass = _mole_to_mass_flow(bog, 1.0)

    def mixed(r):
        m = {k: r * lng_mass[k] + bog_mass[k] for k in species}
        return _mass_to_mole(m)

    def residual(r):
        x = mixed(r)
        _set(st_a, x); st_a.update(CP.PQ_INPUTS, pressure_Pa, 0.0)
        Tb = st_a.T()
        _set(st_b, x); st_b.update(CP.PT_INPUTS, pressure_Pa, Tb - outlet_subcooling_K)
        return (h_bog + r * h_lng) - (1.0 + r) * st_b.hmass()

    # Typical r is 3-10 kg LNG per kg BOG: try a tight bracket first (each
    # residual evaluation is a ~0.1 s mixture flash), widen only if needed.
    for lo, hi in ((1.0, 40.0), (0.05, 200.0)):
        f_lo, f_hi = residual(lo), residual(hi)
        if f_lo * f_hi < 0:
            break
    else:
        raise ValueError(
            "Recondenser energy balance has no solution in r = 0.05..200 - the "
            "LNG is too warm (or the recondenser pressure too low) to condense this BOG."
        )
    r = brentq(residual, lo, hi, xtol=1e-7, rtol=1e-8)
    x_out = mixed(r)
    _set(st_a, x_out); st_a.update(CP.PQ_INPUTS, pressure_Pa, 0.0)
    T_out = st_a.T() - outlet_subcooling_K

    max_bog = available_lng_kg_s / r
    recond = min(bog_flow_kg_s, max_bog)
    return RecondenserResult(
        lng_to_bog_mass_ratio=r, lng_required_kg_s=r * bog_flow_kg_s, outlet_T_K=T_out,
        outlet_composition=x_out, max_recondensable_bog_kg_s=max_bog,
        recondensed_bog_kg_s=recond, excess_bog_kg_s=bog_flow_kg_s - recond,
    )


# ---------------------------------------------------------------------
# Whole send-out train
# ---------------------------------------------------------------------

@dataclass
class RegasTrainResult:
    lp_pump: PumpResult
    hp_pump: PumpResult
    duty_kW: float
    duty_kJ_per_kg: float
    orv: ORVResult
    scv: SCVResult
    total_pump_shaft_kW: float


def size_regas_train(
    composition: dict[str, float],
    sendout_kg_s: float,
    tank_pressure_Pa: float,
    tank_T_K: float,
    lp_discharge_Pa: float,
    sendout_pressure_Pa: float,
    sendout_T_K: float = 278.15,
    seawater_in_C: float = 20.0,
    tank_liquid_head_Pa: float = 1.5e5,
    lp_efficiency: float = 0.70,
    hp_efficiency: float = 0.75,
    **orv_kwargs,
) -> RegasTrainResult:
    """Tank -> LP pump -> HP pump -> vaporizer, on one mass flow.

    tank_liquid_head_Pa is the static head above the in-tank pump suction
    that keeps its suction sub-cooled (1.5 bar ~ 33 m of LNG); the suction
    temperature is the tank bubble point, so it enters as a compressed
    liquid. sendout_T_K default 5 C is a common minimum pipeline delivery
    temperature.
    """
    lp = size_lng_pump(composition, tank_T_K, tank_pressure_Pa + tank_liquid_head_Pa,
                       lp_discharge_Pa, sendout_kg_s, lp_efficiency)
    hp = size_lng_pump(composition, lp.outlet_T_K, lp_discharge_Pa,
                       sendout_pressure_Pa, sendout_kg_s, hp_efficiency)
    duty = vaporizer_duty(composition, sendout_pressure_Pa, hp.outlet_T_K, sendout_T_K, sendout_kg_s)
    orv = size_orv(duty, sendout_kg_s, seawater_in_C, **orv_kwargs)
    scv = size_scv(duty, composition, sendout_kg_s)
    return RegasTrainResult(
        lp_pump=lp, hp_pump=hp, duty_kW=duty, duty_kJ_per_kg=duty / sendout_kg_s,
        orv=orv, scv=scv, total_pump_shaft_kW=lp.shaft_kW + hp.shaft_kW,
    )
