import pytest

from lng_design.refrigerant_generation import (
    ProductSpec, blend_mixed_refrigerant, check_product_spec, makeup_rate,
)

PURE = {"N2": {"Nitrogen": 1.0}, "C1": {"Methane": 1.0},
        "C2": {"Ethane": 1.0}, "C3": {"Propane": 1.0}}


def test_blend_of_pure_sources_reproduces_target_exactly():
    target = {"Nitrogen": 0.05, "Methane": 0.40, "Ethane": 0.45, "Propane": 0.10}
    r = blend_mixed_refrigerant(target, PURE)
    assert r.reachable and r.max_abs_error < 1e-6
    assert r.source_kmol_per_kmol_mr["C2"] == pytest.approx(0.45, abs=1e-6)
    assert sum(r.source_kmol_per_kmol_mr.values()) == pytest.approx(1.0, abs=1e-6)


def test_blend_uses_impure_sources_correctly():
    sources = {"C2rich": {"Ethane": 0.95, "Propane": 0.05}, "C3": {"Propane": 1.0}}
    target = {"Ethane": 0.57, "Propane": 0.43}
    r = blend_mixed_refrigerant(target, sources)
    assert r.reachable
    assert r.achieved["Ethane"] == pytest.approx(0.57, abs=1e-6)
    assert r.source_kmol_per_kmol_mr["C2rich"] == pytest.approx(0.6, abs=1e-6)


def test_unreachable_target_is_flagged_not_hidden():
    r = blend_mixed_refrigerant({"Ethane": 0.5, "Propane": 0.5}, {"C3": {"Propane": 1.0}})
    assert not r.reachable and r.max_abs_error > 0.4


def test_blend_flows_are_non_negative():
    r = blend_mixed_refrigerant({"Methane": 0.5, "Ethane": 0.5}, PURE)
    assert all(v >= 0 for v in r.source_kmol_per_kmol_mr.values())


def test_spec_check_reports_each_violation():
    spec = ProductSpec("propane refrigerant", min_mole_frac={"Propane": 0.95},
                       max_mole_frac={"Ethane": 0.01, "n-Butane": 0.02})
    ok = check_product_spec({"Propane": 0.97, "Ethane": 0.005, "n-Butane": 0.025}, spec)
    assert not ok.passed and len(ok.violations) == 1 and "n-Butane" in ok.violations[0]
    assert check_product_spec({"Propane": 0.99, "Ethane": 0.005, "n-Butane": 0.005}, spec).passed
    bad = check_product_spec({"Propane": 0.90, "Ethane": 0.10}, spec)
    assert len(bad.violations) == 2


def test_spec_check_rejects_unnormalised_composition():
    with pytest.raises(ValueError):
        check_product_spec({"Propane": 0.5}, ProductSpec("x"))


def test_makeup_rate_arithmetic():
    r = blend_mixed_refrigerant({"Ethane": 0.5, "Propane": 0.5}, {"C2": {"Ethane": 1.0}, "C3": {"Propane": 1.0}})
    m = makeup_rate(charge_kmol=8760.0, annual_loss_fraction=0.10, blend=r, mr_molecular_weight_g_mol=37.0)
    assert m.makeup_kmol_h == pytest.approx(0.10 * 8760.0 / 8760.0)
    assert m.makeup_kg_h == pytest.approx(m.makeup_kmol_h * 37.0)
    assert m.by_source_kmol_h["C2"] == pytest.approx(0.05, rel=1e-6)
    with pytest.raises(ValueError):
        makeup_rate(1.0, 1.5, r, 37.0)
