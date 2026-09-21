import CoolProp.CoolProp as CP
import pytest

from lng_design.refrigerant_supply import (
    RefrigerantLoop, RefrigerantSupplyBasis, refrigerant_demand, size_component_storage,
    size_refrigerant_supply,
)

C3 = RefrigerantLoop("C3 precool", {"Propane": 1.0}, charge_kg=16765.0)
MR = RefrigerantLoop("MR", {"Nitrogen": 0.05, "Methane": 0.38, "Ethane": 0.44, "Propane": 0.10,
                            "n-Butane": 0.03}, charge_kmol=8000.0)


def _mw(n):
    return CP.PropsSI("M", n) * 1000.0


@pytest.fixture(scope="module")
def design():
    return size_refrigerant_supply(RefrigerantSupplyBasis(loops=[C3, MR], ngl_available_kmol_h=920.0))


# ---- demand -------------------------------------------------------------

def test_demand_totals_charge_plus_makeup_by_component():
    d = refrigerant_demand([C3, MR], annual_loss_fraction=0.10, makeup_years=1.0)
    eth_charge = 8000.0 * 0.44 * _mw("Ethane")
    prop_charge = 16765.0 + 8000.0 * 0.10 * _mw("Propane")
    assert d.charge_kg["Ethane"] == pytest.approx(eth_charge, rel=1e-9)
    assert d.charge_kg["Propane"] == pytest.approx(prop_charge, rel=1e-9)
    assert d.by_component_kg["Ethane"] == pytest.approx(1.10 * eth_charge, rel=1e-9)
    assert d.makeup_kg["Propane"] == pytest.approx(0.10 * prop_charge, rel=1e-9)
    assert d.total_kg == pytest.approx(sum(d.by_component_kg.values()))
    assert d.by_component_kmol["Ethane"] == pytest.approx(d.by_component_kg["Ethane"] / _mw("Ethane"))


def test_makeup_years_scales_makeup_only():
    a = refrigerant_demand([MR], 0.10, 1.0)
    b = refrigerant_demand([MR], 0.10, 3.0)
    assert b.charge_kg == a.charge_kg
    assert b.makeup_kg["Ethane"] == pytest.approx(3 * a.makeup_kg["Ethane"])


def test_loop_validation():
    with pytest.raises(ValueError, match="exactly one"):
        refrigerant_demand([RefrigerantLoop("x", {"Propane": 1.0})])
    with pytest.raises(ValueError, match="exactly one"):
        refrigerant_demand([RefrigerantLoop("x", {"Propane": 1.0}, charge_kg=1.0, charge_kmol=1.0)])
    with pytest.raises(ValueError, match="sum"):
        refrigerant_demand([RefrigerantLoop("x", {"Propane": 0.5}, charge_kg=1.0)])
    with pytest.raises(ValueError):
        refrigerant_demand([])


# ---- component storage --------------------------------------------------

def test_storage_holds_factor_times_demand_with_the_fill_limit():
    s = size_component_storage("Propane", 57_000.0, 2.75, 308.15, 318.15)
    assert s.capacity_kg == pytest.approx(2.75 * 57_000.0)
    assert s.capacity_range_kg == pytest.approx((2.5 * 57_000.0, 3.0 * 57_000.0))
    # liquid at the 85 % max fill fills exactly the capacity
    assert s.total_volume_m3 * s.liquid_density_kg_m3 * 0.85 == pytest.approx(s.capacity_kg, rel=1e-6)


def test_design_pressure_is_vapor_pressure_at_design_temperature_plus_margin():
    s = size_component_storage("Propane", 57_000.0, 2.75, 308.15, 318.15, pressure_margin=0.10)
    assert s.design_pressure_Pa == pytest.approx(1.10 * CP.PropsSI("P", "T", 318.15, "Q", 0, "Propane"), rel=1e-9)
    assert s.liquid_density_kg_m3 == pytest.approx(CP.PropsSI("D", "T", 308.15, "Q", 0, "Propane"), rel=1e-9)


def test_butane_needs_a_far_lower_design_pressure_than_propane():
    p = size_component_storage("Propane", 50_000.0, 2.75, 308.15, 318.15)
    b = size_component_storage("n-Butane", 50_000.0, 2.75, 308.15, 318.15)
    assert b.design_pressure_Pa < 0.4 * p.design_pressure_Pa


def test_ethane_at_ambient_is_refused_because_it_is_supercritical():
    with pytest.raises(ValueError, match="critical temperature"):
        size_component_storage("Ethane", 100_000.0, 2.75, 308.15, 318.15)


def test_refrigerated_ethane_is_sized_and_flagged():
    s = size_component_storage("Ethane", 116_000.0, 2.75, 258.15, 278.15, needs_refrigeration=True)
    assert s.needs_refrigeration
    assert s.design_pressure_Pa > 25e5          # ~27 bar at +5 C, plus margin


def test_vessel_count_grows_with_capacity():
    small = size_component_storage("Propane", 2_000.0, 2.75, 308.15, 318.15)
    big = size_component_storage("Propane", 400_000.0, 2.75, 308.15, 318.15)
    assert small.n_vessels == 1 and big.n_vessels > small.n_vessels


def test_unstorable_component_rejected():
    with pytest.raises(ValueError, match="not a storable"):
        size_component_storage("Methane", 1000.0, 2.75, 300.0, 310.0)


# ---- whole supply system ------------------------------------------------

def test_storage_is_sized_for_each_liquid_component_and_not_methane_or_nitrogen(design):
    assert set(design.storage) == {"Ethane", "Propane", "n-Butane"}
    assert any("Methane" in n and "not stored" in n for n in design.notes)
    assert any("Nitrogen" in n and "not stored" in n for n in design.notes)
    for c, s in design.storage.items():
        assert s.capacity_kg == pytest.approx(2.75 * design.demand.by_component_kg[c])
    assert design.storage["Ethane"].needs_refrigeration
    assert any("Ethane cannot be stored at ambient" in n for n in design.notes)
    assert design.total_capacity_kg == pytest.approx(sum(s.capacity_kg for s in design.storage.values()))


def test_storage_scales_with_the_factor_and_range_is_reported():
    base = size_refrigerant_supply(RefrigerantSupplyBasis(loops=[C3, MR], storage_factor=2.5))
    top = size_refrigerant_supply(RefrigerantSupplyBasis(loops=[C3, MR], storage_factor=3.0))
    assert top.total_capacity_kg / base.total_capacity_kg == pytest.approx(3.0 / 2.5, rel=1e-9)
    assert not any("outside the requested" in n for n in base.notes + top.notes)


def test_factor_outside_the_requested_range_is_noted():
    d = size_refrigerant_supply(RefrigerantSupplyBasis(loops=[C3, MR], storage_factor=4.0))
    assert any("outside the requested 2.5-3.0x range" in n for n in d.notes)


def test_train_produces_ethane_propane_and_butane_within_spec(design):
    assert set(design.production) == {"ethane", "propane", "butane"}
    for p in design.production.values():
        assert p.spec.passed, p.spec.violations
        assert p.component_kg_h > 0
    assert design.train.mass_balance_error < 1e-9


def test_every_storage_fills_within_the_requested_time(design):
    fd = design.basis.fill_days
    for prod, days in design.fill_days_achieved.items():
        assert days <= fd + 1e-6, (prod, days)
    # the limiting product is filled in ~ fill_days / (1 + margin)
    assert max(design.fill_days_achieved.values()) == pytest.approx(fd / 1.10, rel=0.02)
    assert min(p.coverage for p in design.production.values()) == pytest.approx(1.10, rel=0.02)


def test_longer_fill_time_needs_a_proportionally_smaller_train():
    fast = size_refrigerant_supply(RefrigerantSupplyBasis(loops=[C3, MR], fill_days=30.0))
    slow = size_refrigerant_supply(RefrigerantSupplyBasis(loops=[C3, MR], fill_days=60.0))
    assert fast.feed_scale / slow.feed_scale == pytest.approx(2.0, rel=0.01)


def test_share_of_available_ngl_is_reported_and_overrun_flagged(design):
    assert any("of the 920 kmol/h of NGL available" in n for n in design.notes)
    tight = size_refrigerant_supply(RefrigerantSupplyBasis(loops=[C3, MR], ngl_available_kmol_h=5.0))
    assert any("cannot fill the storage" in n for n in tight.notes)


def test_feed_without_a_product_component_is_rejected():
    with pytest.raises(ValueError):
        size_refrigerant_supply(RefrigerantSupplyBasis(
            loops=[C3, MR], ngl_feed_kmol_h={"Propane": 300.0, "n-Butane": 100.0, "Pentane": 50.0}))


def test_wrong_number_of_columns_rejected():
    from lng_design.refrigerant_supply import default_column_specs
    with pytest.raises(ValueError, match="deethanizer"):
        size_refrigerant_supply(RefrigerantSupplyBasis(loops=[C3, MR], column_specs=default_column_specs()[:2]))
