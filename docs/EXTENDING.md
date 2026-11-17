# Extending toward rigorous optimization

Moved verbatim from the README.

## Extending toward rigorous optimization

`lng_design/optimize.py` wraps [pymoo](https://pymoo.org/)'s NSGA-II for
multi-objective trade-offs (power vs. exergy, matching the approach used in
published C3MR optimization studies). For equation-oriented, gradient-based
optimization at flowsheet scale, install the `advanced` extra:

```bash
pip install -e ".[advanced]"   # pyomo + idaes-pse
```

and use [IDAES-PSE](https://idaes-pse.readthedocs.io/)'s `PySMO`/`ALAMOPy`/
`OMLT` surrogate-modeling tools to fit fast surrogates around any of this
package's sizing functions for use inside a larger NLP.
