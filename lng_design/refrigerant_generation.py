"""Refrigerant generation: from fractionator distillates to make-up
refrigerant.

An LNG train's refrigerant loops (`precool.py` propane, `cascade_loops.py`
mixed refrigerant) lose inventory continuously (seal leakage, vents,
sampling) and need make-up. Rather than buy it, the plant makes it from its
own NGL: ethane from the deethanizer distillate, propane from the
depropanizer distillate (`fractionation.py`), nitrogen and methane from
feed gas / fuel gas / nitrogen system. This module closes that loop:

* `check_product_spec` - does a column's distillate meet a refrigerant
  purity spec? Specs are `ProductSpec` objects of per-component minimum
  and maximum MOLE fractions that YOU supply from your licensor's
  refrigerant requirement (there is no single universal refrigerant-grade
  number; the values in the worked example are assumptions).
* `blend_mixed_refrigerant` - given a target mixed-refrigerant (MR)
  composition and the available source streams, find non-negative source
  flows that reproduce it. Linear blending on a mole basis is exact (no
  reaction, ideal mixing of amounts), so this is a non-negative
  least-squares problem (scipy `nnls`); the residual tells you whether the
  target is reachable from the sources (e.g. you cannot make an MR with
  ethane if no source contains it).
* `makeup_rate` - annual inventory-loss fraction x charge -> make-up rate
  and the fractionator distillate rate needed to cover it, so you can see
  at a glance whether a column that is sized for product recovery is
  vastly oversized for refrigerant duty (it usually is: the make-up is a
  small side stream and most distillate is sold as product).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import nnls


@dataclass
class ProductSpec:
    name: str
    min_mole_frac: dict[str, float] = field(default_factory=dict)
    max_mole_frac: dict[str, float] = field(default_factory=dict)


@dataclass
class SpecCheck:
    name: str
    passed: bool
    violations: list[str]


def check_product_spec(composition: dict[str, float], spec: ProductSpec) -> SpecCheck:
    """Compare a mole-fraction composition to a spec; missing components
    count as 0."""
    tot = sum(composition.values())
    if abs(tot - 1.0) > 1e-6:
        raise ValueError(f"Mole fractions must sum to 1.0, got {tot}")
    bad: list[str] = []
    for comp, lo in spec.min_mole_frac.items():
        v = composition.get(comp, 0.0)
        if v < lo:
            bad.append(f"{comp} {v:.4f} < minimum {lo:.4f}")
    for comp, hi in spec.max_mole_frac.items():
        v = composition.get(comp, 0.0)
        if v > hi:
            bad.append(f"{comp} {v:.4f} > maximum {hi:.4f}")
    return SpecCheck(spec.name, not bad, bad)


@dataclass
class BlendResult:
    source_kmol_per_kmol_mr: dict[str, float]
    achieved: dict[str, float]
    target: dict[str, float]
    max_abs_error: float
    reachable: bool


def blend_mixed_refrigerant(
    target: dict[str, float],
    sources: dict[str, dict[str, float]],
    tolerance: float = 1e-3,
) -> BlendResult:
    """Source flows (kmol per kmol of MR) that best reproduce `target`.

    sources: name -> mole-fraction composition of that stream.
    Solves min ||A s - t|| with s >= 0 and the closure sum(s) = 1 enforced
    as a heavily weighted extra equation. `reachable` is True when the
    worst per-component error is below `tolerance` (mole fraction).
    """
    if abs(sum(target.values()) - 1.0) > 1e-6:
        raise ValueError("target mole fractions must sum to 1.0")
    comps = sorted(set(target) | {c for s in sources.values() for c in s})
    names = list(sources)
    A = np.array([[sources[n].get(c, 0.0) for n in names] for c in comps])
    t = np.array([target.get(c, 0.0) for c in comps])
    W = 1e3
    A_aug = np.vstack([A, W * np.ones(len(names))])
    t_aug = np.append(t, W)
    s, _ = nnls(A_aug, t_aug)
    got = A @ s
    err = np.abs(got - t)
    return BlendResult(
        source_kmol_per_kmol_mr=dict(zip(names, s)),
        achieved=dict(zip(comps, got)),
        target={c: target.get(c, 0.0) for c in comps},
        max_abs_error=float(err.max()),
        reachable=bool(err.max() < tolerance),
    )


@dataclass
class MakeupResult:
    makeup_kmol_h: float
    makeup_kg_h: float
    by_source_kmol_h: dict[str, float]


def makeup_rate(
    charge_kmol: float,
    annual_loss_fraction: float,
    blend: BlendResult,
    mr_molecular_weight_g_mol: float,
) -> MakeupResult:
    """Steady make-up = charge x annual loss / 8,760 h, split over sources
    per the blend. annual_loss_fraction is a plant-specific input."""
    if not (0.0 <= annual_loss_fraction <= 1.0):
        raise ValueError("annual_loss_fraction must be in [0, 1]")
    m = charge_kmol * annual_loss_fraction / 8760.0
    return MakeupResult(
        makeup_kmol_h=m, makeup_kg_h=m * mr_molecular_weight_g_mol,
        by_source_kmol_h={k: v * m for k, v in blend.source_kmol_per_kmol_mr.items()},
    )
