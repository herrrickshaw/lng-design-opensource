"""Multi-objective optimization helpers (NSGA-II via pymoo).

The C3MR LNG-process optimization literature (e.g. multi-objective
propane-precooled mixed-refrigerant studies published in Energy /
Applied Thermal Engineering) consistently uses NSGA-II to trade off
compressor power against exergy efficiency or capital-cost proxies. This
module provides a thin, reusable wrapper so any sizing function in this
package (precool, compressor, absorber) can be dropped into the same
multi-objective search pattern without re-deriving the pymoo boilerplate
each time.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
from pymoo.core.problem import ElementwiseProblem
from pymoo.algorithms.moo.nsga2 import NSGA2
from pymoo.optimize import minimize as pymoo_minimize


@dataclass
class ParetoResult:
    X: np.ndarray  # decision variables on the Pareto front
    F: np.ndarray  # objective values on the Pareto front


def optimize_pareto(
    objective_fn: Callable[[np.ndarray], tuple[float, ...]],
    n_var: int,
    n_obj: int,
    xl: list[float],
    xu: list[float],
    constraint_fn: Callable[[np.ndarray], list[float]] | None = None,
    n_constr: int = 0,
    pop_size: int = 40,
    n_gen: int = 60,
    seed: int = 1,
) -> ParetoResult:
    """Run NSGA-II over `objective_fn(x) -> tuple of n_obj values to
    minimize`, with optional `constraint_fn(x) -> list of n_constr values
    that must be <= 0 to be feasible` (standard pymoo constraint
    convention).
    """

    class _Problem(ElementwiseProblem):
        def __init__(self):
            super().__init__(
                n_var=n_var, n_obj=n_obj, n_constr=n_constr,
                xl=np.array(xl, dtype=float), xu=np.array(xu, dtype=float),
            )

        def _evaluate(self, x, out, *args, **kwargs):
            out["F"] = list(objective_fn(x))
            if n_constr > 0:
                out["G"] = list(constraint_fn(x))

    algorithm = NSGA2(pop_size=pop_size)
    res = pymoo_minimize(_Problem(), algorithm, ("n_gen", n_gen), seed=seed, verbose=False)
    return ParetoResult(X=res.X, F=res.F)
