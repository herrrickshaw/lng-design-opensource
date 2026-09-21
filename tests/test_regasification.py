import pytest

from lng_design.regasification import (
    MTPA_TO_KG_S, RegasificationBasis, size_regasification_terminal,
)


@pytest.fixture(scope="module")
def base():
    return size_regasification_terminal()


def test_default_basis_reproduces_the_worked_example(base):
    """Regression pin against examples/regas_bog_fractionation_worked_example.py."""
    assert base.bog_design.design_bog_kg_s * 3.6 == pytest.approx(54.4, rel=0.01)
    assert base.bog_compressor.shaft_power_kW_per_machine == pytest.approx(2097, rel=0.01)
    assert base.train.duty_kW / 1000 == pytest.approx(112.5, rel=0.01)
    assert base.train.orv.n_operating == 4
    assert base.recondenser.max_recondensable_bog_kg_s * 3.6 == pytest.approx(88, rel=0.03)
    assert base.recondenser_turndown.max_recondensable_bog_kg_s * 3.6 == pytest.approx(22, rel=0.05)
    assert base.hp_bog_compressor.n_stages == 5


def test_basis_conversions_and_mode_ordering(base):
    assert base.sendout_kg_s == pytest.approx(5.0 * MTPA_TO_KG_S)
    assert base.bog_design.design_mode == "unloading" and base.bog_holding.design_mode == "holding"
    assert base.bog_design.design_bog_kg_s > base.bog_holding.design_bog_kg_s


def test_bog_compressor_is_sized_on_the_design_bog_and_its_composition(base):
    c = base.bog_compressor
    assert c.design_flow_kg_s == pytest.approx(base.bog_design.design_bog_kg_s * 1.10)
    assert c.bog_molecular_weight_g_mol < 19.0                 # nitrogen-rich, lighter than LNG


def test_turndown_flag_is_consistent_with_the_fraction(base):
    b = base.basis
    assert base.holding_within_turndown == (base.holding_fraction_of_machine >= b.min_stable_fraction)
    if not base.holding_within_turndown:
        assert any("stable minimum" in n for n in base.notes)


def test_recondenser_is_send_out_limited(base):
    assert base.recondenser_turndown.max_recondensable_bog_kg_s < base.recondenser.max_recondensable_bog_kg_s
    # max absorbable BOG scales linearly with send-out flow: 25 % send-out -> 25 % capacity
    assert (base.recondenser_turndown.max_recondensable_bog_kg_s
            == pytest.approx(0.25 * base.recondenser.max_recondensable_bog_kg_s, rel=1e-6))


def test_excess_bog_routes_to_the_hp_compressor_and_is_disclosed(base):
    assert base.excess_bog_at_turndown_kg_s > 0
    hp = base.hp_bog_compressor
    assert hp.design_flow_kg_s == pytest.approx(base.excess_bog_at_turndown_kg_s * 1.10)
    assert hp.n_stages > base.bog_compressor.n_stages          # 85 bar vs 9 bar discharge
    assert any("HP BOG compressor" in n for n in base.notes)


def test_installed_power_is_the_sum_of_the_parts(base):
    assert base.installed_power_kW == pytest.approx(
        base.train.total_pump_shaft_kW + base.bog_compressor.installed_shaft_power_kW
        + base.hp_bog_compressor.installed_shaft_power_kW)


def test_no_hp_route_when_turndown_is_the_full_send_out():
    d = size_regasification_terminal(RegasificationBasis(turndown_sendout_fraction=1.0))
    assert d.hp_bog_compressor is None
    assert d.excess_bog_at_turndown_kg_s == 0.0


def test_invalid_turndown_fraction_rejected():
    with pytest.raises(ValueError):
        size_regasification_terminal(RegasificationBasis(turndown_sendout_fraction=0.0))
