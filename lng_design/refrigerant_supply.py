"""Refrigerant storage and on-site refrigerant production.

An LNG train's refrigerants - propane for the precool loop, a mixed
refrigerant (nitrogen / methane / ethane / propane, sometimes butane) for
the liquefaction loops - are made from the plant's own NGL and held in
storage so a loop can be filled, drained for maintenance and refilled. This
module sizes both halves on one basis:

1. **Demand and storage.** `refrigerant_demand` totals every loop's
   inventory by component (plus a period of make-up losses). Storage for
   each liquid component (ethane, propane, butanes) is sized to hold
   `storage_factor` x that demand - 2.5 to 3 times, the range asked for -
   as pressurized bullets at the maximum fill fraction, using the same
   vessel-count logic as `refrigerant_makeup.py` (parallel vessels when one
   standard shell is not enough). Design pressure comes from CoolProp vapor
   pressure at the design temperature:

   * propane and butanes are stored at ambient (propane ~15 bar at 45 C);
   * **ethane cannot be stored at ambient**: its critical temperature is
     305 K (32 C), so above that no liquid exists at any pressure. It is
     stored cold-pressurized (default -15 C, ~16 bar) and the design
     pressure is that of the temperature it could warm to if refrigeration
     is lost (default +20 K, ~27 bar) - the module reports that it needs
     refrigeration rather than pretending a pressure exists at ambient;
   * methane and nitrogen are not stored here (fuel gas / nitrogen system).

2. **Fractionation to fill it.** A dedicated deethanizer / depropanizer /
   debutanizer train (`fractionation.py`) makes ethane, propane and butane
   distillates from an NGL feed. The feed is scaled so the scarcest of the
   three products fills its storage within `fill_days`, and the columns are
   re-sized at that scaled feed. Each product is checked against a
   `ProductSpec` (assumed limits - use your licensor's). Because refrigerant
   duty is a small fraction of a plant's NGL, the result also reports what
   share of the available NGL the train would use.

Everything that is a policy choice (2.5-3x factor, 12 months of make-up,
60-day fill, the ethane storage temperature, product specs) is an input, not
buried in the math.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import CoolProp.CoolProp as CP

from .fractionation import ColumnSpec, TrainResult, size_fractionation_train
from .refrigerant_generation import ProductSpec, SpecCheck, check_product_spec
from .refrigerant_makeup import RefrigerantStorageResult, size_refrigerant_storage

STORABLE = ("Ethane", "Propane", "n-Butane", "Isobutane")
NOT_STORED = {"Methane": "fuel gas / feed gas", "Nitrogen": "nitrogen system"}
BUTANES = ("n-Butane", "Isobutane")


def _mw_kg_kmol(name: str) -> float:
    return CP.PropsSI("M", name) * 1000.0


# ---------------------------------------------------------------------
# Demand
# ---------------------------------------------------------------------

@dataclass
class RefrigerantLoop:
    """One refrigerant inventory. Give `charge_kmol` with a mole-fraction
    `composition` (mixed refrigerant) or `charge_kg` of a single pure
    component (e.g. the propane precool loop: composition {'Propane': 1})."""

    name: str
    composition: dict[str, float]
    charge_kmol: float | None = None
    charge_kg: float | None = None


@dataclass
class DemandResult:
    by_component_kg: dict[str, float]
    by_component_kmol: dict[str, float]
    charge_kg: dict[str, float]
    makeup_kg: dict[str, float]
    total_kg: float


def refrigerant_demand(
    loops: list[RefrigerantLoop], annual_loss_fraction: float = 0.10, makeup_years: float = 1.0,
) -> DemandResult:
    """Total demand by component = initial charge of every loop + make-up for
    `makeup_years` at `annual_loss_fraction` of the charge (a plant input;
    10 %/yr is an assumption)."""
    if not loops:
        raise ValueError("at least one refrigerant loop is required")
    charge: dict[str, float] = {}
    for lp in loops:
        tot = sum(lp.composition.values())
        if abs(tot - 1.0) > 1e-6:
            raise ValueError(f"{lp.name}: mole fractions sum to {tot}, not 1")
        if (lp.charge_kmol is None) == (lp.charge_kg is None):
            raise ValueError(f"{lp.name}: give exactly one of charge_kmol / charge_kg")
        if lp.charge_kmol is not None:
            kmol = lp.charge_kmol
        else:
            mw_mix = sum(x * _mw_kg_kmol(c) for c, x in lp.composition.items())
            kmol = lp.charge_kg / mw_mix
        for c, x in lp.composition.items():
            charge[c] = charge.get(c, 0.0) + kmol * x * _mw_kg_kmol(c)
    makeup = {c: kg * annual_loss_fraction * makeup_years for c, kg in charge.items()}
    total = {c: charge[c] + makeup[c] for c in charge}
    return DemandResult(
        by_component_kg=total,
        by_component_kmol={c: kg / _mw_kg_kmol(c) for c, kg in total.items()},
        charge_kg=charge, makeup_kg=makeup, total_kg=sum(total.values()),
    )


# ---------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------

@dataclass
class ComponentStorage:
    component: str
    demand_kg: float
    capacity_kg: float
    storage_T_K: float
    design_T_K: float
    design_pressure_Pa: float
    liquid_density_kg_m3: float
    n_vessels: int
    vessel: RefrigerantStorageResult
    total_volume_m3: float
    needs_refrigeration: bool
    capacity_range_kg: tuple[float, float]


def size_component_storage(
    component: str,
    demand_kg: float,
    storage_factor: float,
    storage_T_K: float,
    design_T_K: float,
    pressure_margin: float = 0.10,
    needs_refrigeration: bool = False,
    factor_range: tuple[float, float] = (2.5, 3.0),
) -> ComponentStorage:
    """Bullets sized to hold `storage_factor` x demand.

    The liquid density is at `storage_T_K`; the design pressure is the vapor
    pressure at `design_T_K` (the hottest the contents can get) plus a margin.
    Raises if `design_T_K` is above the fluid's critical temperature - no
    liquid storage pressure exists there, which is the ethane-at-ambient case.
    """
    if component not in STORABLE:
        raise ValueError(f"{component} is not a storable liquid refrigerant here "
                         f"(storable: {STORABLE})")
    tc = CP.PropsSI("Tcrit", component)
    if design_T_K >= tc - 1.0:
        raise ValueError(
            f"{component}: design temperature {design_T_K - 273.15:.0f} C is at/above its critical "
            f"temperature ({tc - 273.15:.0f} C); it cannot be stored as a liquid at that temperature "
            "at any pressure - refrigerate the storage.")
    rho = CP.PropsSI("D", "T", storage_T_K, "Q", 0, component)
    p_design = (1.0 + pressure_margin) * CP.PropsSI("P", "T", design_T_K, "Q", 0, component)
    capacity = storage_factor * demand_kg
    n = 1
    while True:
        try:
            v = size_refrigerant_storage(capacity / n, rho, reserve_fraction=0.0)
            break
        except ValueError:
            n += 1
            if n > 500:
                raise ValueError(f"{component}: needs more than 500 parallel vessels")
    return ComponentStorage(
        component=component, demand_kg=demand_kg, capacity_kg=capacity, storage_T_K=storage_T_K,
        design_T_K=design_T_K, design_pressure_Pa=p_design, liquid_density_kg_m3=rho,
        n_vessels=n, vessel=v, total_volume_m3=n * v.vessel_volume_m3,
        needs_refrigeration=needs_refrigeration,
        capacity_range_kg=(factor_range[0] * demand_kg, factor_range[1] * demand_kg),
    )


# ---------------------------------------------------------------------
# Whole supply system
# ---------------------------------------------------------------------

DEFAULT_NGL_KMOL_H = {"Ethane": 320.0, "Propane": 300.0, "Isobutane": 60.0, "n-Butane": 100.0,
                      "Isopentane": 50.0, "Pentane": 50.0, "Hexane": 40.0}

# ASSUMED refrigerant-grade limits (mole fractions) - replace with the
# licensor's requirement. No universal refrigerant-grade number exists.
DEFAULT_SPECS = {
    "ethane": ProductSpec("ethane refrigerant", {"Ethane": 0.97}, {"Propane": 0.03}),
    "propane": ProductSpec("propane refrigerant", {"Propane": 0.95},
                           {"Ethane": 0.02, "Isobutane": 0.03, "n-Butane": 0.03}),
    "butane": ProductSpec("butane", {}, {"Propane": 0.05, "Isopentane": 0.02, "Pentane": 0.02}),
}


def default_column_specs() -> list[ColumnSpec]:
    """Deethanizer / depropanizer / debutanizer; ethane recovery is set high
    (0.995) so ethane slip into the propane cut stays inside its spec."""
    return [
        ColumnSpec("deethanizer", "Ethane", "Propane", 26e5, 0.995, 0.995),
        ColumnSpec("depropanizer", "Propane", "Isobutane", 17e5, 0.985, 0.98),
        ColumnSpec("debutanizer", "n-Butane", "Isopentane", 6e5, 0.98, 0.98),
    ]


@dataclass
class RefrigerantSupplyBasis:
    loops: list[RefrigerantLoop]
    storage_factor: float = 2.75                 # within the requested 2.5-3x
    annual_loss_fraction: float = 0.10           # ASSUMED
    makeup_years: float = 1.0                    # ASSUMED
    ambient_design_T_K: float = 318.15           # hottest contents for ambient storage
    ambient_storage_T_K: float = 308.15
    ethane_storage_T_K: float = 258.15           # -15 C, cold-pressurized
    ethane_upset_rise_K: float = 20.0            # warming if refrigeration is lost
    fill_days: float = 60.0                      # ASSUMED time to fill storage
    feed_margin: float = 0.10
    ngl_feed_kmol_h: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_NGL_KMOL_H))
    column_specs: list[ColumnSpec] | None = None
    product_specs: dict[str, ProductSpec] | None = None
    ngl_available_kmol_h: float | None = None    # plant NGL available, for the share check


@dataclass
class ProductionResult:
    product: str
    component_kg_h: float
    required_kg_h: float
    coverage: float
    spec: SpecCheck


@dataclass
class RefrigerantSupplyDesign:
    basis: RefrigerantSupplyBasis
    demand: DemandResult
    storage: dict[str, ComponentStorage]
    train: TrainResult
    scaled_feed_kmol_h: dict[str, float]
    feed_scale: float
    production: dict[str, ProductionResult]
    fill_days_achieved: dict[str, float]
    notes: list[str] = field(default_factory=list)

    @property
    def total_storage_m3(self) -> float:
        return sum(s.total_volume_m3 for s in self.storage.values())

    @property
    def total_capacity_kg(self) -> float:
        return sum(s.capacity_kg for s in self.storage.values())

    def flowsheet_state(self) -> dict[str, dict[str, str]]:
        """Display strings for the flowsheet's refrigerant-storage nodes
        (`ref_storage_ethane|propane|butane`) and the makeup vessel. Butane
        is n- plus iso-butane; a component with no demand shows "none"."""
        def one(comps: tuple[str, ...]) -> dict[str, str]:
            ss = [self.storage[c] for c in comps if c in self.storage]
            if not ss:
                return {"Storage": "none (no demand)"}
            cap = sum(x.capacity_kg for x in ss)
            n = sum(x.n_vessels for x in ss)
            v = ss[0].vessel
            out = {"Capacity": f"{cap / 1000:,.1f} t",
                   "Vessels": f"{n} x {v.standard_diameter_mm:,.0f} mm x {v.vessel_length_m:.1f} m",
                   "Design": f"{max(x.design_pressure_Pa for x in ss) / 1e5:.1f} bar"}
            if any(x.needs_refrigeration for x in ss):
                out["Note"] = "refrigerated"
            return out
        f = self.basis.storage_factor
        return {
            "ref_storage_ethane": one(("Ethane",)),
            "ref_storage_propane": one(("Propane",)),
            "ref_storage_butane": one(BUTANES),
            "refrigerant_makeup": {"Storage": f"{self.total_storage_m3:,.0f} m3",
                                   "Capacity": f"{self.total_capacity_kg / 1000:,.0f} t ({f:.2f}x demand)"},
        }


def size_refrigerant_supply(basis: RefrigerantSupplyBasis) -> RefrigerantSupplyDesign:
    b = basis
    notes: list[str] = []
    lo, hi = 2.5, 3.0
    if not (lo <= b.storage_factor <= hi):
        notes.append(f"storage_factor {b.storage_factor} is outside the requested {lo}-{hi}x range.")

    demand = refrigerant_demand(b.loops, b.annual_loss_fraction, b.makeup_years)

    storage: dict[str, ComponentStorage] = {}
    for comp, kg in demand.by_component_kg.items():
        if comp in NOT_STORED:
            notes.append(f"{comp} ({kg / 1000:,.1f} t of demand) is not stored here: "
                         f"supplied from the {NOT_STORED[comp]}.")
            continue
        if comp == "Ethane":
            storage[comp] = size_component_storage(
                comp, kg, b.storage_factor, b.ethane_storage_T_K,
                b.ethane_storage_T_K + b.ethane_upset_rise_K, needs_refrigeration=True)
            notes.append(
                f"Ethane cannot be stored at ambient (critical temperature 32 C): stored at "
                f"{b.ethane_storage_T_K - 273.15:.0f} C and "
                f"{storage[comp].design_pressure_Pa / 1e5:.0f} bar design, needing refrigeration to hold it.")
        else:
            storage[comp] = size_component_storage(
                comp, kg, b.storage_factor, b.ambient_storage_T_K, b.ambient_design_T_K)

    # ---- fractionation train sized to fill the storage in fill_days
    specs = b.column_specs or default_column_specs()
    if len(specs) != 3:
        raise ValueError("column_specs must be [deethanizer, depropanizer, debutanizer]")
    product_specs = b.product_specs or DEFAULT_SPECS

    required_kg_h = {
        "ethane": storage["Ethane"].capacity_kg if "Ethane" in storage else 0.0,
        "propane": storage["Propane"].capacity_kg if "Propane" in storage else 0.0,
        "butane": sum(storage[c].capacity_kg for c in BUTANES if c in storage),
    }
    required_kg_h = {k: v / (b.fill_days * 24.0) for k, v in required_kg_h.items()}

    def rates(train: TrainResult) -> dict[str, float]:
        de, dp, db = train.columns
        return {
            "ethane": de.distillate_kmol_h.get("Ethane", 0.0) * _mw_kg_kmol("Ethane"),
            "propane": dp.distillate_kmol_h.get("Propane", 0.0) * _mw_kg_kmol("Propane"),
            "butane": sum(db.distillate_kmol_h.get(c, 0.0) * _mw_kg_kmol(c) for c in BUTANES),
        }

    base = size_fractionation_train(b.ngl_feed_kmol_h, specs)
    avail = rates(base)
    scale = 0.0
    for k, need in required_kg_h.items():
        if need > 0:
            if avail[k] <= 0:
                raise ValueError(f"the NGL feed produces no {k}; cannot fill its storage")
            scale = max(scale, need / avail[k])
    scale *= 1.0 + b.feed_margin
    if scale <= 0:
        raise ValueError("no refrigerant demand to produce")
    scaled = {k: v * scale for k, v in b.ngl_feed_kmol_h.items()}
    train = size_fractionation_train(scaled, specs)
    got = rates(train)

    dists = {"ethane": train.columns[0], "propane": train.columns[1], "butane": train.columns[2]}
    production: dict[str, ProductionResult] = {}
    fill_days: dict[str, float] = {}
    for k, col in dists.items():
        chk = check_product_spec(col.distillate_mole_fractions, product_specs[k])
        cap = required_kg_h[k] * b.fill_days * 24.0
        production[k] = ProductionResult(
            product=k, component_kg_h=got[k], required_kg_h=required_kg_h[k],
            coverage=got[k] / required_kg_h[k] if required_kg_h[k] else float("inf"), spec=chk)
        fill_days[k] = cap / (got[k] * 24.0) if got[k] else float("inf")
        if not chk.passed:
            notes.append(f"{k} product fails its (assumed) spec: " + "; ".join(chk.violations))
    limiting = max(required_kg_h, key=lambda k: required_kg_h[k] / max(avail[k], 1e-12))
    notes.append(f"Feed scaled x{scale:.3f} ({sum(scaled.values()):,.1f} kmol/h): {limiting} is the "
                 f"limiting product for a {b.fill_days:.0f}-day fill.")
    if b.ngl_available_kmol_h is not None:
        share = sum(scaled.values()) / b.ngl_available_kmol_h
        notes.append(f"This train would use {share * 100:.1f}% of the {b.ngl_available_kmol_h:,.0f} "
                     "kmol/h of NGL available.")
        if share > 1.0:
            notes.append("The available NGL cannot fill the storage in the requested time: "
                         "lengthen fill_days or reduce storage_factor.")
    for c in train.columns:
        notes.extend(f"{c.name}: {n}" for n in c.notes)

    return RefrigerantSupplyDesign(
        basis=b, demand=demand, storage=storage, train=train, scaled_feed_kmol_h=scaled,
        feed_scale=scale, production=production, fill_days_achieved=fill_days, notes=notes)
