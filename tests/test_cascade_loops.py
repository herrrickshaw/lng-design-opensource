import pytest

from lng_design.cascade_loops import mixed_refrigerant_cycle, three_loop_cascade
from lng_design.properties import GasMixture

# Composition and temperature range empirically validated (see
# docs/VALIDATION.md) to give a numerically robust mixture flash: a light
# LRC-style blend, evaporating cold and condensing at a COLD (not
# ambient) sink.
LRC_BLEND = GasMixture({"Nitrogen": 0.05, "Methane": 0.30, "Ethane": 0.35, "Propane": 0.30})

# Heavier DMR-style precool blend - verified to condense at 40 C ambient
# while evaporating well below pure propane's ~-42 C atmospheric floor.
DMR_PRECOOL_BLEND = GasMixture({"Ethane": 0.30, "Propane": 0.70})

PMR_T_EVAP = 233.15   # -40 C, at/near pure propane's practical floor
PMR_T_COND = 313.15   # 40 C ambient
LRC_T_EVAP = 173.15   # -100 C
LRC_T_COND = PMR_T_EVAP + 3.0  # 3 K MITA margin above PMR's evaporator - NOT zero


def test_mixed_refrigerant_cycle_gives_sane_valid_cycle():
    result = mixed_refrigerant_cycle(LRC_BLEND, duty_kW=5000.0, T_evap_K=LRC_T_EVAP, T_cond_K=LRC_T_COND)
    assert result.P_cond_Pa > result.P_evap_Pa
    assert result.compressor_power_kW > 0
    assert result.refrigerant_mass_flow_kg_s > 0
    # Energy balance: rejected duty = absorbed duty + compressor work
    assert result.condensing_duty_kW == pytest.approx(5000.0 + result.compressor_power_kW, rel=1e-6)


def test_mixed_refrigerant_cycle_rejects_inverted_temperatures():
    with pytest.raises(ValueError):
        mixed_refrigerant_cycle(LRC_BLEND, 5000.0, T_evap_K=233.15, T_cond_K=173.15)


def test_mixed_refrigerant_cycle_rejects_infeasible_ambient_condensing():
    # This light blend cannot condense anywhere near ambient temperature -
    # confirmed empirically; the wrapped error should surface clearly
    # rather than leaking a raw CoolProp solver exception.
    with pytest.raises(ValueError, match="too light"):
        mixed_refrigerant_cycle(LRC_BLEND, 5000.0, T_evap_K=LRC_T_EVAP, T_cond_K=293.15)


def test_heavier_dmr_blend_condenses_at_ambient_colder_than_propane_floor():
    # The concrete mechanism behind DMR's reported precool advantage:
    # this blend evaporates well below propane's ~-42 C atmospheric-
    # pressure floor while still condensing at 40 C ambient.
    result = mixed_refrigerant_cycle(DMR_PRECOOL_BLEND, duty_kW=3000.0, T_evap_K=223.15, T_cond_K=313.15)  # -50 C
    assert result.compressor_power_kW > 0


def test_three_loop_cascade_rejects_zero_or_negative_mita_between_loops():
    # LRC condensing exactly at (or below) PMR's evaporator temperature
    # would need infinite heat-transfer area - must be rejected, the same
    # discipline mche.py applies to the main cryogenic exchanger.
    with pytest.raises(ValueError, match="MITA violated"):
        three_loop_cascade(
            3000.0, 5000.0, PMR_T_EVAP, PMR_T_COND, LRC_BLEND, LRC_T_EVAP,
            lrc_T_cond_K=PMR_T_EVAP,  # zero margin
        )


def test_three_loop_cascade_pmr_duty_includes_lrc_condensing_heat():
    result = three_loop_cascade(
        ng_precool_duty_kW=3000.0,
        ng_liquefaction_duty_kW=5000.0,
        pmr_T_evap_K=PMR_T_EVAP,
        pmr_T_cond_K=PMR_T_COND,
        lrc_refrigerant=LRC_BLEND,
        lrc_T_evap_K=LRC_T_EVAP,
        lrc_T_cond_K=LRC_T_COND,
    )
    # The cascade link: PMR's total duty must exceed the raw NG precool
    # duty by exactly the LRC loop's condensing heat rejection.
    assert result.pmr_total_duty_kW == pytest.approx(3000.0 + result.lrc.condensing_duty_kW, rel=1e-6)
    assert result.pmr_total_duty_kW > 3000.0


def test_three_loop_cascade_total_power_is_sum_of_both_loops():
    result = three_loop_cascade(3000.0, 5000.0, PMR_T_EVAP, PMR_T_COND, LRC_BLEND, LRC_T_EVAP, LRC_T_COND)
    assert result.total_compressor_power_kW == pytest.approx(
        result.lrc.compressor_power_kW + result.pmr.compressor_power_kW, rel=1e-9
    )


def test_more_liquefaction_duty_increases_total_power():
    small = three_loop_cascade(3000.0, 2000.0, PMR_T_EVAP, PMR_T_COND, LRC_BLEND, LRC_T_EVAP, LRC_T_COND)
    large = three_loop_cascade(3000.0, 8000.0, PMR_T_EVAP, PMR_T_COND, LRC_BLEND, LRC_T_EVAP, LRC_T_COND)
    assert large.total_compressor_power_kW > small.total_compressor_power_kW


def test_dmr_style_pmr_reaches_colder_evap_than_propane_default():
    # With pmr_refrigerant given, PMR can be run at a T_evap colder than
    # propane's practical floor - this is the actual DMR-vs-C3MR
    # comparison the module exists to make possible.
    dmr_pmr_T_evap = 223.15  # -50 C, below propane's ~-42 C floor
    result = three_loop_cascade(
        3000.0, 5000.0, dmr_pmr_T_evap, PMR_T_COND, LRC_BLEND, LRC_T_EVAP,
        lrc_T_cond_K=dmr_pmr_T_evap + 3.0,
        pmr_refrigerant=DMR_PRECOOL_BLEND,
    )
    assert result.pmr.T_evap_K == pytest.approx(dmr_pmr_T_evap)
    assert result.pmr.compressor_power_kW > 0
    assert result.total_compressor_power_kW > 0


def test_propane_below_its_normal_boiling_point_needs_vacuum_operation():
    # -50 C is below propane's normal boiling point (-42.1 C, verified in
    # test_properties.py), so propane_cycle_power still resolves it
    # thermodynamically (propane's triple point is ~-187.7 C, far colder)
    # but only via a SUB-ATMOSPHERIC evaporator pressure - an operational
    # drawback (air/moisture ingress risk) real plants avoid, which is
    # itself part of the practical case for DMR over deep-vacuum propane
    # operation, distinct from the thermodynamic-limit framing above.
    from lng_design.precool import propane_cycle_power
    propane_result = propane_cycle_power(3000.0, 223.15, PMR_T_COND)
    assert propane_result.P_evap_Pa < 101325.0  # sub-atmospheric

    dmr_result = mixed_refrigerant_cycle(DMR_PRECOOL_BLEND, 3000.0, 223.15, PMR_T_COND)
    assert dmr_result.compressor_power_kW > 0


def test_single_stage_cannot_span_full_precool_to_lng_rundown_range():
    # Found by running examples/full_train_worked_example.py: this exact
    # blend cannot do -40C to -159C (or even -100C to -159C) in one
    # compression stage - the isentropic P-S flash fails to converge,
    # a real limitation this test locks in rather than lets regress
    # silently into a wrong-but-plausible-looking number.
    with pytest.raises(ValueError, match="did not converge"):
        mixed_refrigerant_cycle(LRC_BLEND, 5000.0, T_evap_K=173.15 - 60, T_cond_K=236.15)


def test_pure_propane_cycle_pressures_match_saturation_tables():
    # propane saturation (NIST): -40 C -> 1.11 bar, 40 C -> 13.69 bar
    r = mixed_refrigerant_cycle(GasMixture({"Propane": 1.0}), 5000.0, 233.15, 313.15)
    assert r.P_evap_Pa / 1e5 == pytest.approx(1.11, abs=0.01)
    assert r.P_cond_Pa / 1e5 == pytest.approx(13.69, abs=0.02)
    assert r.condensing_duty_kW == pytest.approx(5000.0 + r.compressor_power_kW)


@pytest.mark.parametrize("blend,T_evap,T_cond", [
    ({"Nitrogen": 0.05, "Methane": 0.30, "Ethane": 0.35, "Propane": 0.30}, 173.15, 236.15),
    ({"Ethane": 0.30, "Propane": 0.70}, 223.15, 313.15),
])
def test_mr_cycle_agrees_with_an_independent_peng_robinson_cycle(blend, T_evap, T_cond):
    """Same textbook single-stage cycle (dew-point suction, bubble-point condensate,
    isentropic compression / 0.75) re-solved on CoolProp's Peng-Robinson backend."""
    import CoolProp.CoolProp as CP
    names, fracs = "&".join(blend), list(blend.values())

    def st():
        a = CP.AbstractState("PR", names)
        a.set_mole_fractions(fracs)
        return a
    e, c, k = st(), st(), st()
    e.update(CP.QT_INPUTS, 1.0, T_evap)
    c.update(CP.QT_INPUTS, 0.0, T_cond)
    k.update(CP.PSmass_INPUTS, c.p(), e.smass())
    m = 5000e3 / (e.hmass() - c.hmass())
    w_pr = m * (k.hmass() - e.hmass()) / 0.75 / 1000.0
    r = mixed_refrigerant_cycle(GasMixture(blend), 5000.0, T_evap, T_cond)
    assert r.refrigerant_mass_flow_kg_s == pytest.approx(m, rel=0.05)
    assert r.compressor_power_kW == pytest.approx(w_pr, rel=0.06)
    assert r.P_cond_Pa == pytest.approx(c.p(), rel=0.12)
