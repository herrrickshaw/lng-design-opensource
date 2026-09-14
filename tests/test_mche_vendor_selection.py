from lng_design.mche_vendor_selection import compare_mche_vendors


def test_returns_both_vendor_profiles():
    result = compare_mche_vendors()
    assert result.apci.vendor.startswith("APCI")
    assert result.linde.vendor.startswith("Linde")


def test_apci_has_two_cycles_linde_has_three():
    result = compare_mche_vendors()
    assert result.apci.n_refrigeration_cycles == 2
    assert result.linde.n_refrigeration_cycles == 3


def test_capacity_note_added_when_capacity_given():
    result = compare_mche_vendors(target_train_capacity_mtpa=8.0)
    assert len(result.screening_notes) >= 1
    assert any("8.0 mtpa" in n for n in result.screening_notes)


def test_no_notes_when_no_inputs_given():
    result = compare_mche_vendors()
    assert result.screening_notes == []


def test_modularity_preference_adds_a_note():
    modular = compare_mche_vendors(values_modularity=True)
    simple = compare_mche_vendors(values_modularity=False)
    assert any("Linde" in n for n in modular.screening_notes)
    assert any("APCI" in n for n in simple.screening_notes)
