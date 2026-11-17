"""Characterisation tests: pin size_column and size_liquefaction_train outputs before/after the
pass-2 split into helpers. Golden values were captured from the pre-split code (CoolProp mixtures)."""
import dataclasses
import json
import math
from pathlib import Path

import pytest

from lng_design.fractionation import ColumnSpec, size_column
from lng_design.liquefaction import LiquefactionBasis, size_liquefaction_train

GOLDEN = Path(__file__).parent / "golden" / "pass2_characterisation.json"
NGL = {"Ethane": 320.0, "Propane": 300.0, "Isobutane": 60.0, "n-Butane": 100.0,
       "Isopentane": 50.0, "Pentane": 50.0, "Hexane": 40.0}


def _plain(obj):
    """Dataclass/dict/list tree -> JSON-able tree of floats, strings and ints."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _plain(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, dict):
        return {str(k): _plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_plain(v) for v in obj]
    if isinstance(obj, (int, float, str, bool)) or obj is None:
        return obj
    return repr(obj)


def _cases():
    deeth = ColumnSpec("deethanizer", "Ethane", "Propane", 26e5, 0.98, 0.995)
    deprop = ColumnSpec("depropanizer", "Propane", "Isobutane", 17e5, 0.985, 0.98)
    debut = ColumnSpec("debutanizer", "n-Butane", "Isopentane", 6e5, 0.98, 0.98)
    low_p = ColumnSpec("lowP", "Ethane", "Propane", 8e5, 0.98, 0.99, tray_efficiency=0.7)
    frac = LiquefactionBasis(
        ngl_feed_kmol_h=NGL, fractionation_specs=[deeth, deprop, debut],
        mr_target={"Nitrogen": 0.05, "Methane": 0.40, "Ethane": 0.45, "Propane": 0.10})
    return {
        "col_deeth": lambda: size_column(NGL, deeth),
        "col_deprop_feedT": lambda: size_column(NGL, deprop, feed_T_K=300.0),
        "col_debut_feedh": lambda: size_column(NGL, debut, feed_h_J_mol=-9000.0),
        "col_lowP_fixedEo": lambda: size_column(NGL, low_p),
        "liq_default": lambda: size_liquefaction_train(),
        "liq_frac_mr_supply": lambda: size_liquefaction_train(dataclasses.replace(
            frac, include_refrigerant_supply=True)),
    }


def _close(a, b, path=""):
    if isinstance(a, float) or isinstance(b, float):
        assert a == pytest.approx(b, rel=1e-9, abs=1e-12), path
    elif isinstance(a, dict):
        assert a.keys() == b.keys(), path
        for k in a:
            _close(a[k], b[k], f"{path}.{k}")
    elif isinstance(a, list):
        assert len(a) == len(b), path
        for i, (x, y) in enumerate(zip(a, b)):
            _close(x, y, f"{path}[{i}]")
    else:
        assert a == b, path


@pytest.mark.parametrize("name", list(_cases()))
def test_matches_golden(name):
    golden = json.loads(GOLDEN.read_text())
    got = json.loads(json.dumps(_plain(_cases()[name]()), allow_nan=True))
    _close(got, golden[name], name)


@pytest.mark.parametrize("spec,msg", [
    (ColumnSpec("x", "Ethane", "Pentane2", 26e5, 0.98, 0.99), "must both be in the feed"),
    (ColumnSpec("x", "Ethane", "Propane", 26e5, 0.98, 0.99, reflux_factor=1.0), "reflux_factor"),
    (ColumnSpec("x", "Ethane", "Propane", 26e5, 0.4, 0.99), "recoveries"),
    (ColumnSpec("x", "Propane", "Ethane", 26e5, 0.98, 0.99), "not more volatile"),
])
def test_size_column_rejections(spec, msg):
    with pytest.raises(ValueError, match=msg):
        size_column(NGL, spec)


if __name__ == "__main__":  # regenerate: python tests/test_pass2_characterisation.py
    out = {k: _plain(f()) for k, f in _cases().items()}
    GOLDEN.write_text(json.dumps(out, indent=1, sort_keys=True, allow_nan=True))
    print("wrote", GOLDEN, math.fsum(1 for _ in out))
