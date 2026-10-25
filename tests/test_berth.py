import pytest

from lng_design.berth import berth_queueing_analysis, size_storage_tank, _erlang_c_probability_wait


def test_erlang_c_reduces_to_mm1_probability_of_waiting_equals_rho():
    # Textbook special case: for a single server (c=1), Erlang C's
    # probability of waiting reduces exactly to rho (the M/M/1 utilization),
    # since P(wait) = P(system busy) when there's only one server.
    a = 0.6  # offered load in Erlangs, c=1 so rho = a
    p_wait = _erlang_c_probability_wait(a, n_berths=1)
    assert p_wait == pytest.approx(a, rel=1e-9)


def test_erlang_c_rejects_unstable_system():
    with pytest.raises(ValueError):
        _erlang_c_probability_wait(offered_load_erlangs=2.5, n_berths=2)  # rho > 1


def test_more_berths_reduces_wait_time():
    kwargs = dict(annual_offtake_mtpa=5.0, cargo_size_m3=170000.0,
                  lng_density_kg_m3=450.0, berth_service_time_h=30.0)
    one_berth = berth_queueing_analysis(**kwargs, n_berths=1)
    two_berths = berth_queueing_analysis(**kwargs, n_berths=2)
    assert two_berths.expected_wait_hours < one_berth.expected_wait_hours


def test_littles_law_consistency():
    result = berth_queueing_analysis(
        annual_offtake_mtpa=5.0, cargo_size_m3=170000.0, lng_density_kg_m3=450.0,
        berth_service_time_h=30.0, n_berths=2,
    )
    # Recompute arrival rate independently to check Little's Law (L = lambda * W)
    cargo_mass_kg = 170000.0 * 450.0
    ships_per_year = (5.0 * 1e9) / cargo_mass_kg
    arrival_rate_per_h = ships_per_year / (365.25 * 24.0)
    assert result.expected_ships_in_queue == pytest.approx(
        arrival_rate_per_h * result.expected_wait_hours, rel=1e-9
    )


def test_storage_tank_sizing_matches_manual_mass_balance():
    prod_rate, density, interval, contingency = 60.0, 450.0, 4.0, 1.5
    result = size_storage_tank(prod_rate, density, interval, contingency)
    expected = (prod_rate * 86400.0 * (interval + contingency)) / density
    assert result.required_volume_m3 == pytest.approx(expected, rel=1e-9)


def test_storage_tank_cargo_equivalent():
    result = size_storage_tank(60.0, 450.0, 4.0, 1.5, cargo_size_m3=170000.0)
    assert result.cargo_equivalent == pytest.approx(result.required_volume_m3 / 170000.0, rel=1e-9)


def test_erlang_c_hand_values():
    # M/M/1: P(wait) = rho
    assert _erlang_c_probability_wait(0.5, 1) == pytest.approx(0.5)
    # M/M/2 with a = 1: (1/(2!(1-0.5))) / (1 + 1 + 1) = 1/3
    assert _erlang_c_probability_wait(1.0, 2) == pytest.approx(1.0 / 3.0)


def test_mm1_wait_by_hand():
    # 4.5 mtpa, 170,000 m3 x 450 kg/m3 = 76,500 t cargo -> 58.824 ships/yr
    # lambda = 58.824 / 8766 h = 0.0067105 /h; mu = 1/24 /h -> a = 0.161050
    # Wq = rho/(mu - lambda) = 0.16105 / (0.041667 - 0.0067105) = 4.6071 h
    r = berth_queueing_analysis(4.5, 170000.0, 450.0, 24.0, n_berths=1)
    assert r.offered_load_erlangs == pytest.approx(0.161050, rel=1e-5)
    assert r.probability_of_waiting == pytest.approx(0.161050, rel=1e-5)
    assert r.expected_wait_hours == pytest.approx(4.6071, rel=1e-4)
