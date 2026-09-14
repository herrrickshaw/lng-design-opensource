from lng_design.loads import DutyItem, DutyType, UtilityMedium, summarize_loads


def test_summarize_loads_splits_heating_and_cooling():
    items = [
        DutyItem("E-101", 500.0, DutyType.COOLING, UtilityMedium.COOLING_WATER),
        DutyItem("E-102", 300.0, DutyType.HEATING, UtilityMedium.STEAM),
        DutyItem("E-103", 200.0, DutyType.COOLING, UtilityMedium.AIR),
    ]
    summary = summarize_loads(items)
    assert summary.total_cooling_kW == 700.0
    assert summary.total_heating_kW == 300.0


def test_summarize_loads_groups_by_medium():
    items = [
        DutyItem("E-101", 500.0, DutyType.COOLING, UtilityMedium.COOLING_WATER),
        DutyItem("E-104", 100.0, DutyType.COOLING, UtilityMedium.COOLING_WATER),
        DutyItem("E-103", 200.0, DutyType.COOLING, UtilityMedium.AIR),
    ]
    summary = summarize_loads(items)
    assert summary.by_medium_kW["cooling_water"] == 600.0
    assert summary.by_medium_kW["air"] == 200.0


def test_summarize_loads_empty_list():
    summary = summarize_loads([])
    assert summary.total_heating_kW == 0.0
    assert summary.total_cooling_kW == 0.0
    assert summary.by_medium_kW == {}
