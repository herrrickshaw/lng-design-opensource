"""NGL fractionation column conceptual sizing (distillate and bottoms
products, refrigerant-grade cuts).

An LNG plant fractionates the heavy ends taken out of the feed gas into a
train of columns, each making a light **distillate** (overhead) and passing
a **bottoms** to the next column:

    NGL -> deethanizer -> distillate: ethane (refrigerant / make-up)
             bottoms -> depropanizer -> distillate: propane (refrigerant)
                          bottoms -> debutanizer -> distillate: butanes (LPG)
                                        bottoms: C5+ condensate

This module sizes each column with the classical **Fenske-Underwood-
Gilliland (FUG)** shortcut, with the vapor-liquid equilibrium behind every
relative volatility taken from CoolProp's HEOS mixture EOS (bubble-point
K = y/x at the actual column-end composition and pressure) rather than from
Raoult's law or a fixed alpha.

Method, in the order it is applied
-----------------------------------
1. **Fenske** (Fenske 1932): minimum stages at total reflux from the
   key-component split,
   N_min = ln[(d_LK/b_LK)(b_HK/d_HK)] / ln(alpha_LK,HK);
   non-key distribution from d_i/b_i = (d_HK/b_HK) alpha_i,HK^N_min.
2. **Underwood** (Underwood 1948): minimum reflux from the root theta
   (alpha_HK < theta < alpha_LK) of sum(alpha_i z_i / (alpha_i - theta)) =
   1 - q, then R_min + 1 = sum(alpha_i x_D,i / (alpha_i - theta)). The feed
   thermal condition q comes from CoolProp enthalpies.
3. **Gilliland** in the Molokanov et al. (1972) closed form, with
   Y = (N - N_min)/(N + 1), X = (R - R_min)/(R + 1), at R = `reflux_factor`
   x R_min.
4. **Kirkbride** (1944) feed-stage location.
5. **O'Connell** (1946) overall tray efficiency from liquid viscosity and
   alpha, giving real trays.
6. **Hydraulics**: Souders-Brown flooding with a surface-tension (Fair)
   correction, evaluated at both column ends; diameter is the larger.
7. **Duties**: total condenser from CoolProp latent heat at column-top
   composition; reboiler from the overall enthalpy balance
   Q_r = Q_c + D h_D + B h_B - F h_F (all molar enthalpies from CoolProp).

The column pressure profile is solved self-consistently: bottom pressure =
top pressure + N_real x dP_tray, and N_real depends on the pressure
through alpha, so the calculation is iterated to convergence.

What FUG is and is not
----------------------
FUG assumes constant relative volatility and constant molar overflow, and
Gilliland is a curve fit; expect stage counts good to roughly +/-10-15 %
against a rigorous stage-by-stage model (tests/test_fractionation.py
quantifies the gap against an independent McCabe-Thiele stepping for an
ideal binary). It is a front-end sizing tool, not a replacement for a
rigorous column simulation, and it does not model azeotropes, non-key
distribution beyond Fenske, side draws, pumparounds, or vendor tray
ratings. Non-adjacent keys are rejected.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import CoolProp.CoolProp as CP
import numpy as np
from scipy.optimize import brentq

from .equipment_catalog import STANDARD_VESSEL_DIAMETERS_MM, match_standard_size

R_MIN_FLOOR = 1e-6
_FLOOR = 1e-6   # composition floor for trace components in CoolProp calls

# Approximate Souders-Brown flooding capacity factor vs tray spacing at low
# flow parameter and 20 mN/m surface tension, read off the Souders-Brown /
# Fair flooding chart (Perry's, distillation chapter). +/-20 %: a screening
# value - use the tray vendor's rating for detail.
_KSB_BY_SPACING = [(0.30, 0.070), (0.45, 0.095), (0.60, 0.115), (0.75, 0.130), (0.90, 0.140)]


def k_sb_for_spacing(spacing_m: float) -> float:
    xs = [a for a, _ in _KSB_BY_SPACING]
    ys = [b for _, b in _KSB_BY_SPACING]
    return float(np.interp(spacing_m, xs, ys))


# ---------------------------------------------------------------------
# CoolProp phase-equilibrium helpers (molar basis)
# ---------------------------------------------------------------------

def _state(comp: dict[str, float]) -> "CP.AbstractState":
    names = list(comp.keys())
    fr = np.array([max(comp[n], _FLOOR) for n in names])
    s = CP.AbstractState("HEOS", "&".join(names))
    s.set_mole_fractions(list(fr / fr.sum()))
    return s


def _frac(flows: dict[str, float]) -> dict[str, float]:
    tot = sum(flows.values())
    return {k: v / tot for k, v in flows.items()}


@dataclass
class _Bubble:
    T: float
    K: dict[str, float]
    y: dict[str, float]
    h_L: float          # J/mol
    rho_L: float        # kg/m3
    mu_L_cP: float
    MW_L: float         # g/mol


def _bubble(comp: dict[str, float], P: float) -> _Bubble:
    s = _state(comp)
    s.update(CP.PQ_INPUTS, P, 0.0)
    names = list(comp.keys())
    x = list(s.mole_fractions_liquid())
    y = list(s.mole_fractions_vapor())
    try:
        mu = s.viscosity() * 1000.0
        if not math.isfinite(mu):
            raise ValueError
    except Exception:
        mu = _mixture_viscosity_cP(names, x, s.T())
    return _Bubble(
        T=s.T(), K={n: yi / xi for n, xi, yi in zip(names, x, y)},
        y=dict(zip(names, y)), h_L=s.hmolar(), rho_L=s.rhomass(), mu_L_cP=mu,
        MW_L=s.molar_mass() * 1000.0,
    )


def _mixture_viscosity_cP(names, x, T) -> float:
    """Fallback (Arrhenius log-mixing of pure saturated-liquid viscosities)
    when CoolProp has no mixture viscosity for this blend."""
    ln_mu = 0.0
    for n, xi in zip(names, x):
        ln_mu += xi * math.log(CP.PropsSI("V", "T", T, "Q", 0, n))
    return math.exp(ln_mu) * 1000.0


@dataclass
class _Dew:
    T: float
    h_V: float
    rho_V: float
    MW_V: float


def _dew(comp: dict[str, float], P: float) -> _Dew:
    s = _state(comp)
    s.update(CP.PQ_INPUTS, P, 1.0)
    return _Dew(T=s.T(), h_V=s.hmolar(), rho_V=s.rhomass(), MW_V=s.molar_mass() * 1000.0)


def _alphas(comp: dict[str, float], P: float, hk: str) -> dict[str, float]:
    b = _bubble(comp, P)
    return {n: k / b.K[hk] for n, k in b.K.items()}


# ---------------------------------------------------------------------
# Shortcut equations (kept as small pure functions so the tests can hit
# them against closed-form limits, independent of CoolProp)
# ---------------------------------------------------------------------

def fenske_min_stages(d_lk: float, b_lk: float, d_hk: float, b_hk: float, alpha_lk_hk: float) -> float:
    return math.log((d_lk / b_lk) * (b_hk / d_hk)) / math.log(alpha_lk_hk)


def underwood_min_reflux(
    alpha: dict[str, float], z: dict[str, float], x_d: dict[str, float],
    q: float, lk: str, hk: str,
) -> tuple[float, float]:
    """Return (R_min, theta). Root theta is bracketed between alpha_HK and
    alpha_LK, which assumes no other component's alpha lies between them
    (adjacent keys - enforced by the caller)."""
    a_lk, a_hk = alpha[lk], alpha[hk]

    def f(theta):
        return sum(alpha[i] * z[i] / (alpha[i] - theta) for i in z) - (1.0 - q)

    eps = 1e-9 * (a_lk - a_hk)
    theta = brentq(f, a_hk + eps, a_lk - eps, xtol=1e-12)
    rmin = sum(alpha[i] * x_d[i] / (alpha[i] - theta) for i in x_d) - 1.0
    return rmin, theta


def gilliland_molokanov_Y(X: float) -> float:
    """Molokanov et al. (1972) analytic fit to Gilliland's correlation."""
    if X <= 0.0:
        return 1.0
    if X >= 1.0:
        return 0.0
    return 1.0 - math.exp((1.0 + 54.4 * X) / (11.0 + 117.2 * X) * (X - 1.0) / math.sqrt(X))


def gilliland_stages(n_min: float, r: float, r_min: float) -> float:
    X = (r - r_min) / (r + 1.0)
    Y = gilliland_molokanov_Y(X)
    if 1.0 - Y < 1e-12:      # R at (or below) R_min: infinite stages
        return math.inf
    return (n_min + Y) / (1.0 - Y)


def kirkbride_ratio(z_hk: float, z_lk: float, B: float, D: float, x_b_lk: float, x_d_hk: float) -> float:
    """N_rectifying / N_stripping (Kirkbride 1944)."""
    return ((z_hk / z_lk) * (B / D) * (x_b_lk / x_d_hk) ** 2) ** 0.206


def oconnell_efficiency(mu_cP: float, alpha: float) -> float:
    """Overall tray efficiency, O'Connell (1946): Eo[%] = 51 - 32.5 log10(mu*alpha),
    mu = liquid viscosity at average column T in mPa.s, alpha = LK/HK.
    Clipped to 0.3-0.9 (outside the correlation's data)."""
    eo = (51.0 - 32.5 * math.log10(mu_cP * alpha)) / 100.0
    return min(max(eo, 0.30), 0.90)


# ---------------------------------------------------------------------
# Column specification and result
# ---------------------------------------------------------------------

@dataclass
class ColumnSpec:
    name: str
    light_key: str
    heavy_key: str
    top_pressure_Pa: float
    lk_recovery_to_distillate: float = 0.99
    hk_recovery_to_bottoms: float = 0.99
    reflux_factor: float = 1.2            # R / R_min; commonly quoted design range 1.1-1.5
    tray_spacing_m: float = 0.60
    pressure_drop_per_tray_Pa: float = 700.0    # ~0.1 psi/tray, a typical valve/sieve-tray figure
    flooding_fraction: float = 0.80
    downcomer_area_fraction: float = 0.12       # of total column area; assumption
    tray_efficiency: float | None = None        # None -> O'Connell
    K_SB: float | None = None                   # None -> by tray spacing
    bottoms_residence_min: float = 5.0
    top_allowance_m: float = 1.5
    bottom_allowance_m: float = 1.2
    cooling_medium_T_K: float = 308.15          # air/cooling-water supply
    cooling_approach_K: float = 10.0            # condensing T must clear this above supply


@dataclass
class ColumnResult:
    name: str
    N_min: float
    R_min: float
    R: float
    N_theoretical: float
    N_real: int
    feed_tray_from_top: int
    tray_efficiency: float
    q: float
    theta: float
    P_top_Pa: float
    P_bottom_Pa: float
    T_top_K: float
    T_bottom_K: float
    condenser_duty_kW: float
    reboiler_duty_kW: float
    condenser_service: str
    min_pressure_for_cooling_water_Pa: float | None
    diameter_m: float
    diameter_top_m: float
    diameter_bottom_m: float
    height_m: float
    distillate_kmol_h: dict[str, float]
    bottoms_kmol_h: dict[str, float]
    distillate_kg_h: float
    bottoms_kg_h: float
    bottoms_bubble_h_J_mol: float
    flooding_governs: str
    alpha_lk_hk: float
    notes: list[str] = field(default_factory=list)

    @property
    def distillate_mole_fractions(self) -> dict[str, float]:
        return _frac(self.distillate_kmol_h)

    @property
    def bottoms_mole_fractions(self) -> dict[str, float]:
        return _frac(self.bottoms_kmol_h)


_MW = {
    "Methane": 16.043, "Ethane": 30.070, "Propane": 44.097, "n-Butane": 58.123,
    "Isobutane": 58.123, "Isopentane": 72.150, "n-Pentane": 72.150, "Pentane": 72.150,
    "Hexane": 86.177, "n-Hexane": 86.177, "Nitrogen": 28.013, "Propylene": 42.081,
}


def _surface_tension(comp: dict[str, float], T: float) -> float:
    """Mole-fraction-weighted pure-component surface tension, N/m (CoolProp
    has no mixture surface tension - approximation, adequate because the
    diameter goes as sigma^-0.1 through the Fair correction)."""
    tot = 0.0
    for n, x in comp.items():
        try:
            tot += x * CP.PropsSI("I", "T", min(T, CP.PropsSI("Tcrit", n) * 0.98), "Q", 0, n)
        except Exception:
            tot += x * 0.010
    return tot


def _flood_diameter(
    V_kmol_h: float, L_kmol_h: float, vapor_comp: dict[str, float], liq_comp: dict[str, float],
    T: float, P: float, spec: ColumnSpec,
) -> float:
    dew = _dew(vapor_comp, P)
    bub = _bubble(liq_comp, P)
    sigma = _surface_tension(liq_comp, bub.T)
    mV = V_kmol_h * dew.MW_V          # kg/h
    mL = L_kmol_h * bub.MW_L
    F_lv = (mL / mV) * math.sqrt(dew.rho_V / bub.rho_L)
    k = spec.K_SB if spec.K_SB is not None else k_sb_for_spacing(spec.tray_spacing_m)
    if spec.K_SB is None and F_lv > 0.1:
        # Flooding capacity falls with rising liquid/vapor loading (the
        # downward trend of the Fair chart at high flow parameter); an
        # empirical trend, not a chart digitization.
        k *= (0.1 / F_lv) ** 0.3
    k *= (sigma / 0.020) ** 0.2
    u_flood = k * math.sqrt((bub.rho_L - dew.rho_V) / dew.rho_V)
    u_des = spec.flooding_fraction * u_flood
    A_net = (mV / 3600.0 / dew.rho_V) / u_des        # vapor m3/s / allowable velocity
    A_tot = A_net / (1.0 - spec.downcomer_area_fraction)
    return math.sqrt(4.0 * A_tot / math.pi)


def size_column(
    feed_kmol_h: dict[str, float],
    spec: ColumnSpec,
    feed_T_K: float | None = None,
    feed_h_J_mol: float | None = None,
) -> ColumnResult:
    """Size one column. Feed thermal condition: give `feed_h_J_mol` (best
    - exact for a flashed let-down stream), or `feed_T_K` for a
    single-phase feed, or neither for saturated liquid (q = 1)."""
    feed = {k: v for k, v in feed_kmol_h.items() if v > 0}
    lk, hk = spec.light_key, spec.heavy_key
    if lk not in feed or hk not in feed:
        raise ValueError("light_key and heavy_key must both be in the feed")
    if spec.reflux_factor <= 1.0:
        raise ValueError("reflux_factor must exceed 1.0 (R at or below R_min needs infinite stages)")
    for r in (spec.lk_recovery_to_distillate, spec.hk_recovery_to_bottoms):
        if not (0.5 < r < 1.0):
            raise ValueError("recoveries must be in (0.5, 1.0)")
    F = sum(feed.values())
    z = _frac(feed)
    notes: list[str] = []

    d = {k: 0.0 for k in feed}
    b = {k: 0.0 for k in feed}
    d[lk] = spec.lk_recovery_to_distillate * feed[lk]; b[lk] = feed[lk] - d[lk]
    b[hk] = spec.hk_recovery_to_bottoms * feed[hk];    d[hk] = feed[hk] - b[hk]

    n_real = 30
    P_bot = spec.top_pressure_Pa + n_real * spec.pressure_drop_per_tray_Pa
    for _ in range(12):
        # inner loop: alpha at top/bottom compositions -> Fenske distribution
        alpha_g = None
        for _ in range(10):
            xd = _frac({k: max(v, 1e-12) for k, v in d.items()}) if sum(d.values()) > 0 else z
            xb = _frac({k: max(v, 1e-12) for k, v in b.items()}) if sum(b.values()) > 0 else z
            a_top = _alphas(xd, spec.top_pressure_Pa, hk)
            a_bot = _alphas(xb, P_bot, hk)
            alpha = {k: math.sqrt(a_top[k] * a_bot[k]) for k in feed}
            if alpha[lk] <= 1.0:
                raise ValueError(f"alpha_LK/HK = {alpha[lk]:.3f} <= 1: {lk} is not more volatile than {hk} here")
            between = [k for k in feed if k not in (lk, hk) and alpha[hk] < alpha[k] < alpha[lk]]
            if between:
                raise ValueError(f"Keys not adjacent: {between} have volatility between {lk} and {hk}")
            n_min = fenske_min_stages(d[lk], b[lk], d[hk], b[hk], alpha[lk])
            ratio_hk = d[hk] / b[hk]
            d_new, b_new = {}, {}
            for k in feed:
                if k in (lk, hk):
                    d_new[k], b_new[k] = d[k], b[k]
                    continue
                rr = ratio_hk * alpha[k] ** n_min
                d_new[k] = feed[k] * rr / (1.0 + rr)
                b_new[k] = feed[k] - d_new[k]
            change = max(abs(d_new[k] - d[k]) for k in feed) / F
            d, b = d_new, b_new
            alpha_g = alpha
            if change < 1e-7:
                break
        alpha = alpha_g
        D, B = sum(d.values()), sum(b.values())
        x_d, x_b = _frac(d), _frac(b)

        P_feed = 0.5 * (spec.top_pressure_Pa + P_bot)
        bub_f, dew_f = _bubble(z, P_feed), _dew(z, P_feed)
        if feed_h_J_mol is not None:
            h_f = feed_h_J_mol
        elif feed_T_K is not None:
            sf = _state(z); sf.update(CP.PT_INPUTS, P_feed, feed_T_K); h_f = sf.hmolar()
        else:
            h_f = bub_f.h_L
        q = (dew_f.h_V - h_f) / (dew_f.h_V - bub_f.h_L)

        r_min, theta = underwood_min_reflux(alpha, z, x_d, q, lk, hk)
        r_min = max(r_min, R_MIN_FLOOR)
        R = spec.reflux_factor * r_min
        n_th = gilliland_stages(n_min, R, r_min)

        eo = spec.tray_efficiency
        if eo is None:
            bub_avg = _bubble(z, P_feed)
            eo = oconnell_efficiency(bub_avg.mu_L_cP, alpha[lk])
        n_new = max(2, math.ceil((n_th - 1.0) / eo))
        P_bot_new = spec.top_pressure_Pa + n_new * spec.pressure_drop_per_tray_Pa
        done = abs(P_bot_new - P_bot) < 100.0 and n_new == n_real
        n_real, P_bot = n_new, P_bot_new
        if done:
            break
    else:
        notes.append("Pressure/tray-count iteration hit its limit; result approximate.")

    # Kirkbride
    ratio = kirkbride_ratio(z[hk], z[lk], B, D, x_b[lk], max(x_d[hk], 1e-12))
    feed_tray = max(1, min(n_real - 1, round(n_real * ratio / (1.0 + ratio))))

    # Duties
    top_bub, top_dew = _bubble(x_d, spec.top_pressure_Pa), _dew(x_d, spec.top_pressure_Pa)
    bot_bub = _bubble(x_b, P_bot)
    V = D * (R + 1.0)                      # kmol/h condensed
    Q_c = V * 1000.0 * (top_dew.h_V - top_bub.h_L) / 3600.0 / 1000.0   # kW
    Q_r = Q_c + (D * top_bub.h_L + B * bot_bub.h_L - F * h_f) * 1000.0 / 3600.0 / 1000.0

    # Condenser service class + the pressure that would make it water/air-coolable
    t_needed = spec.cooling_medium_T_K + spec.cooling_approach_K
    service = ("cooling water / air" if top_bub.T >= t_needed
               else "refrigerated (propane/ethylene-class refrigerant)")
    p_cw = None
    if top_bub.T < t_needed:
        try:
            sp = _state(x_d); sp.update(CP.QT_INPUTS, 0.0, t_needed); p_cw = sp.p()
        except Exception:
            notes.append(
                f"No bubble point at {t_needed:.0f} K for the distillate (above its critical "
                "temperature): a water/air-cooled total condenser is not possible at any pressure."
            )

    # Hydraulics: top and bottom sections
    L_top = D * R
    V_top = V
    d_top = _flood_diameter(V_top, L_top, x_d, x_d, top_bub.T, spec.top_pressure_Pa, spec)
    V_bot = V - (1.0 - q) * F
    L_bot = V_bot + B
    y_b = bot_bub.y
    d_bot = _flood_diameter(V_bot, L_bot, y_b, x_b, bot_bub.T, P_bot, spec)
    d_req = max(d_top, d_bot)
    try:
        d_std = match_standard_size(d_req * 1000.0, STANDARD_VESSEL_DIAMETERS_MM) / 1000.0
    except ValueError:
        d_std = math.ceil(d_req * 10.0) / 10.0
        notes.append("Diameter exceeds the standard-vessel series: rounded up to 0.1 m (custom-fabricated shell).")

    area = math.pi / 4.0 * d_std ** 2
    b_vol_m3_s = B * bot_bub.MW_L / 3600.0 / bot_bub.rho_L
    h_sump = b_vol_m3_s * spec.bottoms_residence_min * 60.0 / area
    height = (n_real - 1) * spec.tray_spacing_m + spec.top_allowance_m + spec.bottom_allowance_m + h_sump
    if height / d_std > 30.0:
        notes.append(f"Height/diameter = {height/d_std:.0f} > 30: consider splitting into two shells.")

    MW_d = sum(x_d[k] * _MW[k] for k in x_d) if all(k in _MW for k in x_d) else top_bub.MW_L
    MW_b = sum(x_b[k] * _MW[k] for k in x_b) if all(k in _MW for k in x_b) else bot_bub.MW_L

    return ColumnResult(
        name=spec.name, N_min=n_min, R_min=r_min, R=R, N_theoretical=n_th, N_real=n_real,
        feed_tray_from_top=feed_tray, tray_efficiency=eo, q=q, theta=theta,
        P_top_Pa=spec.top_pressure_Pa, P_bottom_Pa=P_bot, T_top_K=top_bub.T, T_bottom_K=bot_bub.T,
        condenser_duty_kW=Q_c, reboiler_duty_kW=Q_r, condenser_service=service,
        min_pressure_for_cooling_water_Pa=p_cw, diameter_m=d_std,
        diameter_top_m=d_top, diameter_bottom_m=d_bot, height_m=height,
        distillate_kmol_h=d, bottoms_kmol_h=b,
        distillate_kg_h=D * MW_d, bottoms_kg_h=B * MW_b, bottoms_bubble_h_J_mol=bot_bub.h_L,
        flooding_governs="top" if d_top >= d_bot else "bottom",
        alpha_lk_hk=alpha[lk], notes=notes,
    )


# ---------------------------------------------------------------------
# Train
# ---------------------------------------------------------------------

@dataclass
class TrainResult:
    columns: list[ColumnResult]
    feed_kmol_h: dict[str, float]

    @property
    def mass_balance_error(self) -> float:
        """Relative mole-flow closure of (all distillates + last bottoms) vs feed."""
        tot = sum(sum(c.distillate_kmol_h.values()) for c in self.columns)
        tot += sum(self.columns[-1].bottoms_kmol_h.values())
        f = sum(self.feed_kmol_h.values())
        return abs(tot - f) / f


def size_fractionation_train(
    feed_kmol_h: dict[str, float],
    specs: list[ColumnSpec],
    feed_T_K: float | None = None,
) -> TrainResult:
    """Series train: each column's bottoms feeds the next. The bottoms of
    column i leaves at its bubble point at its bottom pressure and is let
    down isenthalpically into column i+1 (its enthalpy sets q there)."""
    cols: list[ColumnResult] = []
    feed = dict(feed_kmol_h)
    h_feed = None
    for i, sp in enumerate(specs):
        res = size_column(feed, sp, feed_T_K=feed_T_K if i == 0 else None, feed_h_J_mol=h_feed)
        cols.append(res)
        feed = {k: v for k, v in res.bottoms_kmol_h.items() if v > 1e-9}
        h_feed = res.bottoms_bubble_h_J_mol
    return TrainResult(columns=cols, feed_kmol_h=dict(feed_kmol_h))
