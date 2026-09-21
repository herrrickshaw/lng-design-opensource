import pytest

from lng_design.fractionation import ColumnSpec
from lng_design.liquefaction import (
    MTPA_TO_KG_S, LiquefactionBasis, size_liquefaction_train,
)
from lng_design.precool import optimal_evap_temperature

NGL = {"Ethane": 320, "Propane": 300, "Isobutane": 60, "n-Butane": 100,
       "Isopentane": 50, "Pentane": 50, "Hexane": 40}
SPECS = [ColumnSpec("deethanizer", "Ethane", "Propane", 26e5, 0.98, 0.995),
         ColumnSpec("depropanizer", "Propane", "Isobutane", 17e5, 0.985, 0.98)]


@pytest.fixture(scope="module")
def base():
    return size_liquefaction_train()


def test_default_basis_reproduces_the_hand_written_worked_example(base):
    """Regression pin: these are the numbers examples/full_train_worked_example.py
    prints when its calls are made by hand (2 mtpa basis)."""
    assert base.inlet_separator.standard_diameter_mm == 2591
    assert base.absorber.diameter_m == pytest.approx(3.64, abs=0.01)
    assert base.molecular_sieve.n_beds == 2
    assert base.precool.T_evap_K - 273.15 == pytest.approx(-43.0, abs=0.1)
    assert base.precool.compressor_power_kW == pytest.approx(9330, rel=0.005)
    assert base.cascade.lrc.compressor_power_kW == pytest.approx(27219, rel=0.005)
    assert base.end_flash.vapor_mass_fraction == pytest.approx(0.0463, abs=0.0005)
    assert base.storage_tank.required_volume_m3 == pytest.approx(63827, rel=0.005)
    assert base.total_compression_power_kW == pytest.approx(36871, rel=0.005)


def test_precool_matches_a_direct_module_call(base):
    b = base.basis
    duty = base.feed_mass_flow_kg_s * b.precool_cp_kJ_kg_K * (b.precool_from_C - b.precool_to_C)
    direct = optimal_evap_temperature(duty, b.precool_to_C + 273.15, b.ambient_T_K)
    assert base.precool_duty_kW == pytest.approx(duty)
    assert base.precool.compressor_power_kW == pytest.approx(direct.compressor_power_kW)


def test_mass_and_duty_balances_close(base):
    ef = base.end_flash
    assert ef.vapor_mass_flow_kg_s + ef.liquid_mass_flow_kg_s == pytest.approx(base.feed_mass_flow_kg_s)
    assert base.feed_mass_flow_kg_s == pytest.approx(2.0 * MTPA_TO_KG_S)
    b = base.basis
    total = base.feed_mass_flow_kg_s * b.liquefaction_cp_kJ_kg_K * abs(b.end_C - b.precool_to_C)
    assert base.lrc_duty_kW + base.subcooling_duty_kW == pytest.approx(total)
    assert base.lng_out_kg_s == ef.liquid_mass_flow_kg_s


def test_totals_are_the_sum_of_the_parts(base):
    assert base.refrigeration_power_kW == pytest.approx(
        base.precool.compressor_power_kW + base.cascade.lrc.compressor_power_kW)
    assert base.total_compression_power_kW == pytest.approx(
        base.refrigeration_power_kW + base.flash_gas_compressor.gas_power_kW)


def test_unsized_subcooling_loop_is_disclosed_not_hidden(base):
    assert any("subcooling" in n.lower() and "does not size" in n for n in base.notes)


def test_bigger_train_needs_more_of_everything(base):
    big = size_liquefaction_train(LiquefactionBasis(capacity_mtpa=3.0))
    assert big.feed_mass_flow_kg_s > base.feed_mass_flow_kg_s
    assert big.precool.compressor_power_kW > base.precool.compressor_power_kW
    assert big.storage_tank.required_volume_m3 > base.storage_tank.required_volume_m3


def test_optional_fractionation_and_refrigerant_generation():
    d = size_liquefaction_train(LiquefactionBasis(
        ngl_feed_kmol_h=NGL, fractionation_specs=SPECS,
        mr_target={"Nitrogen": 0.05, "Methane": 0.40, "Ethane": 0.45, "Propane": 0.10}))
    assert d.fractionation is not None and len(d.fractionation.columns) == 2
    assert d.fractionation.mass_balance_error < 1e-9
    assert d.mr_blend.reachable and d.mr_makeup.makeup_kmol_h > 0


def test_fractionation_absent_by_default(base):
    assert base.fractionation is None and base.mr_blend is None and base.mr_makeup is None


def test_ngl_feed_without_specs_is_rejected():
    with pytest.raises(ValueError, match="fractionation_specs"):
        size_liquefaction_train(LiquefactionBasis(ngl_feed_kmol_h=NGL))


def test_mr_blend_needs_two_columns():
    with pytest.raises(ValueError, match="deethanizer and depropanizer"):
        size_liquefaction_train(LiquefactionBasis(
            ngl_feed_kmol_h=NGL, fractionation_specs=SPECS[:1],
            mr_target={"Methane": 0.5, "Ethane": 0.5}))


def test_unreachable_mr_target_is_flagged_in_notes():
    d = size_liquefaction_train(LiquefactionBasis(
        ngl_feed_kmol_h=NGL, fractionation_specs=SPECS,
        mr_target={"Ethane": 0.3, "Hexane": 0.7}))
    assert not d.mr_blend.reachable
    assert any("not reachable" in n for n in d.notes)
