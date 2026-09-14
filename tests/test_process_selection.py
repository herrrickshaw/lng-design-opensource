from lng_design.process_selection import compare_liquefaction_cycles


def test_small_train_moderate_climate_recommends_c3mr():
    result = compare_liquefaction_cycles(target_train_capacity_mtpa=4.0, ambient_temp_swing_K=15.0)
    assert result.recommended == "C3MR"


def test_mid_size_train_recommends_dmr():
    result = compare_liquefaction_cycles(target_train_capacity_mtpa=6.5, ambient_temp_swing_K=15.0)
    assert result.recommended == "DMR"


def test_very_large_train_recommends_apx():
    result = compare_liquefaction_cycles(target_train_capacity_mtpa=10.0, ambient_temp_swing_K=15.0)
    assert result.recommended == "AP-X"


def test_small_train_but_wide_ambient_swing_recommends_dmr():
    # Below C3MR's capacity ceiling, but a wide seasonal ambient swing
    # (e.g. a continental climate) tips the recommendation to DMR.
    result = compare_liquefaction_cycles(target_train_capacity_mtpa=4.0, ambient_temp_swing_K=30.0)
    assert result.recommended == "DMR"


def test_boundary_at_wide_swing_threshold_goes_to_dmr():
    result = compare_liquefaction_cycles(
        target_train_capacity_mtpa=4.0, ambient_temp_swing_K=25.0,
        wide_ambient_swing_threshold_K=25.0,
    )
    assert result.recommended == "DMR"


def test_recommendation_includes_alternatives_and_rationale():
    result = compare_liquefaction_cycles(target_train_capacity_mtpa=4.0, ambient_temp_swing_K=10.0)
    assert result.recommended not in result.alternatives_considered
    assert len(result.rationale) > 20
