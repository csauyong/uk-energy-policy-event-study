"""A-priori inventory: loading, scoring arithmetic, and the group counts.

The group counts here are pinned deliberately. They are the numbers that
decide whether the sign-consistency test exists, and two arithmetic slips in
one day both landed in code of exactly that kind: a nested-set assumption that
returned -82% date accuracy, and a mistyped instrument id that made a dropped
event look harmless. Neither was caught by 279 passing tests, because none of
them covered this path.
"""

from __future__ import annotations

import pytest

from policy_event_study.events.inventory import (
    DateGrade,
    DiscoveryScore,
    Instrument,
    drop_instruments,
    group_count,
    load_inventory,
    score_discovery,
    usable_events,
)

GREEN_LEVIES = "green-levies-rollback-2013"
BUDGET_2025 = "budget-2025-eco-abolished"


def instrument(
    identifier: str, date: str, direction: str = "loosen", grade: str = "A"
) -> Instrument:
    return Instrument(
        id=identifier,
        date=date,
        title=identifier,
        families=("eco",),
        stage="target_change",
        direction=direction,
        channel_targets=("product_revenue",),
        date_grade=DateGrade(grade),
    )


@pytest.fixture(scope="module")
def inventory() -> tuple[Instrument, ...]:
    return load_inventory()


# -- loading ---------------------------------------------------------------


def test_inventory_loads_with_expected_shape(inventory: tuple[Instrument, ...]) -> None:
    assert len(inventory) == 49
    assert sum(1 for i in inventory if i.date_grade is DateGrade.C) == 8
    assert len(usable_events(inventory)) == 41


def test_c_grade_is_not_usable() -> None:
    """A month is not a trading session; a C-grade date cannot enter an estimate."""
    assert not DateGrade.C.usable
    assert DateGrade.A.usable and DateGrade.B.usable
    assert DateGrade.B.needs_confirmation and not DateGrade.A.needs_confirmation


def test_scheduled_commencements_are_kept_but_marked(
    inventory: tuple[Instrument, ...],
) -> None:
    """Rule 0: a list of only events that should have moved something is biased."""
    with_scheduled = usable_events(inventory, include_scheduled=True)
    without = usable_events(inventory, include_scheduled=False)
    assert len(with_scheduled) > len(without)
    assert all(i.is_independent for i in without)


def test_opposite_signed_channel_event_is_detected(
    inventory: tuple[Instrument, ...],
) -> None:
    mixed = [i for i in inventory if i.opposite_signed_channels]
    assert [i.id for i in mixed] == ["future-homes-standard-2026"]


# -- the scoring arithmetic ------------------------------------------------


def test_found_misdated_missed_partition_the_usable_set(
    inventory: tuple[Instrument, ...],
) -> None:
    score = score_discovery(inventory, [("October 2021", "heat_buildings_strategy")])
    total = len(score.found) + len(score.misdated) + len(score.missed)
    assert total == score.inventory_usable


def test_date_accuracy_is_not_a_nested_set_ratio() -> None:
    """Regression: `1 - misdated/found` returned -82% and read as catastrophe."""
    score = DiscoveryScore(
        inventory_total=41,
        inventory_usable=41,
        found=tuple(f"f{i}" for i in range(11)),
        missed=tuple(f"m{i}" for i in range(10)),
        misdated=tuple((f"d{i}", "2023-01", "x") for i in range(20)),
        sweep_only=0,
    )
    assert score.date_accuracy == pytest.approx(11 / 31)
    assert 0.0 <= score.date_accuracy <= 1.0
    assert score.coverage == pytest.approx(31 / 41)
    assert score.miss_rate == pytest.approx(10 / 41)


def test_metrics_are_zero_safe() -> None:
    empty = DiscoveryScore(0, 0, (), (), (), 0)
    assert empty.coverage == 0.0
    assert empty.date_accuracy == 0.0
    assert empty.miss_rate == 0.0


# -- dropping, and the silent no-op -----------------------------------------


def test_dropping_an_unknown_id_raises_rather_than_no_op() -> None:
    """A mistyped id left the set unchanged and read as a robustness finding."""
    items = [instrument("a", "2023-01-01"), instrument("b", "2023-06-01")]
    with pytest.raises(KeyError, match="silently do nothing"):
        drop_instruments(items, ["typo-id"])


def test_dropping_a_known_id_removes_exactly_it() -> None:
    items = [instrument("a", "2023-01-01"), instrument("b", "2023-06-01")]
    assert [i.id for i in drop_instruments(items, ["a"])] == ["b"]


# -- group counts: the numbers that decide whether the test exists ----------


def test_group_count_collapses_within_the_spacing_threshold() -> None:
    close = [instrument("a", "2015-07-10"), instrument("b", "2015-07-23")]
    assert group_count(close, spacing_days=14) == 1, "13 days apart must collapse"
    apart = [instrument("a", "2015-07-10"), instrument("b", "2015-08-10")]
    assert group_count(apart, spacing_days=14) == 2


def test_group_count_ignores_undated_instruments() -> None:
    items = [instrument("a", "2023-01-01"), instrument("b", "2018-11-??")]
    assert group_count(items) == 1


@pytest.mark.parametrize(
    ("dropped", "expected_n", "expected_groups"),
    [
        ((), 9, 8),
        ((GREEN_LEVIES,), 8, 7),
        ((BUDGET_2025,), 8, 7),
        ((GREEN_LEVIES, BUDGET_2025), 7, 6),
    ],
)
def test_loosen_side_survives_every_leak_outcome(
    inventory: tuple[Instrument, ...],
    dropped: tuple[str, ...],
    expected_n: int,
    expected_groups: int,
) -> None:
    """Pinned: the loosen side under each leak-search outcome.

    The pre-committed contingency fires below 4 groups. It does not fire in any
    scenario -- but an earlier estimate of `count // 2` put the baseline at ~4
    and made the design look one deletion from losing its falsification test.
    These are the numbers that decision rests on, so they are pinned.
    """
    independent = [
        i
        for i in usable_events(inventory, include_scheduled=False)
        if i.resolved_day is not None
    ]
    kept = [
        i
        for i in drop_instruments(independent, dropped)
        if i.direction in {"loosen", "mixed"}
    ]
    assert len(kept) == expected_n
    assert group_count(kept) == expected_groups
    assert group_count(kept) >= 4, "pre-stated contingency would fire"


def test_tighten_side_group_count_is_pinned(inventory: tuple[Instrument, ...]) -> None:
    independent = [
        i
        for i in usable_events(inventory, include_scheduled=False)
        if i.resolved_day is not None
    ]
    tighten = [i for i in independent if i.direction == "tighten"]
    assert len(tighten) == 22
    assert group_count(tighten) == 19


def test_whole_list_group_count_is_pinned(inventory: tuple[Instrument, ...]) -> None:
    """26 groups is what takes the p-value floor off the binding constraint."""
    independent = [
        i
        for i in usable_events(inventory, include_scheduled=False)
        if i.resolved_day is not None
    ]
    assert len(independent) == 31
    assert group_count(independent) == 26
