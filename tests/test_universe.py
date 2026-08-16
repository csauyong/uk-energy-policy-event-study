"""Universe config: per-event resolution, and the `notes:` block enforced."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import yaml

from policy_event_study.data.universe import (
    ClockClass,
    EventResolutionError,
    ExpectedSign,
    Status,
    UniverseConfigError,
    load_universe,
)
from policy_event_study.paths import UNIVERSE_CONFIG


def rewrite(
    path: Path, tmp_path: Path, mutate: Callable[[dict[str, Any]], None]
) -> Path:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    mutate(raw)
    target = tmp_path / "mutated.yaml"
    target.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return target


DATE = pd.Timestamp("2023-03-15")


def test_loads_the_test_fixture(test_universe_path: Path) -> None:
    universe = load_universe(test_universe_path)
    assert universe.sector_keys == ("exposed_group", "other_group")
    assert {donor.unit_id for donor in universe.donors} == {
        "DON1.L",
        "DON2.L",
        "USDON",
        "EUDON.PA",
        "DKDON.CO",
        "FLIP.L",
    }
    assert universe.market_index.unit_id == "^IDX"
    assert universe.unresolved[0].proposed_ticker == "GONE.L"


# -- unit identity vs data source -----------------------------------------


def test_aliased_unit_shares_a_source_but_not_an_identity(
    test_universe_path: Path,
) -> None:
    """The Barratt pattern: one Yahoo symbol, two economically distinct units."""
    universe = load_universe(test_universe_path)
    pre = universe.listing("MERGED_PRE")
    post = universe.listing("MERGED.L")
    assert pre.source_ticker == post.source_ticker == "MERGED.L"
    assert pre.is_aliased and not post.is_aliased
    # One fetch, two columns.
    assert len(universe.source_tickers) == len(universe.unit_ids) - 1


def test_availability_bounds_make_the_boundary_uncrossable(
    test_universe_path: Path,
) -> None:
    universe = load_universe(test_universe_path)
    pre = universe.listing("MERGED_PRE")
    post = universe.listing("MERGED.L")
    assert pre.available_on(pd.Timestamp("2022-06-01"))
    assert not pre.available_on(pd.Timestamp("2022-07-10"))
    assert not post.available_on(pd.Timestamp("2022-06-01"))
    assert post.available_on(pd.Timestamp("2022-07-10"))
    # No date admits both, which is what "do not splice" means operationally.
    for day in pd.date_range("2022-01-01", "2023-01-01", freq="D"):
        assert not (pre.available_on(day) and post.available_on(day))


# -- per-event resolution --------------------------------------------------


def test_every_unit_resolves_to_exactly_one_status(test_universe_path: Path) -> None:
    universe = load_universe(test_universe_path)
    resolved = universe.resolve_for_event("E", (), DATE)
    assert set(resolved.statuses) | set(resolved.dropped) == set(universe.unit_ids)
    assert not set(resolved.statuses) & set(resolved.dropped)


def test_override_flips_a_donor_to_treated(test_universe_path: Path) -> None:
    """The Segro case: classification is event-dependent, not global."""
    universe = load_universe(test_universe_path)
    plain = universe.resolve_for_event("E", (), DATE)
    special = universe.resolve_for_event("E", ("special_regime",), DATE)
    assert plain.statuses["FLIP.L"] is Status.DONOR
    assert special.statuses["FLIP.L"] is Status.TREATED
    assert special.applied_overrides == ("flip_to_treated",)


def test_override_can_match_on_event_id(test_universe_path: Path) -> None:
    universe = load_universe(test_universe_path)
    resolved = universe.resolve_for_event("SPECIFIC-EVENT", (), DATE)
    assert resolved.statuses["DON2.L"] is Status.EXCLUDED
    assert "match_by_event_id" in resolved.applied_overrides


def test_override_removes_a_partially_treated_donor(test_universe_path: Path) -> None:
    universe = load_universe(test_universe_path)
    resolved = universe.resolve_for_event("E", ("eu_mandate",), DATE)
    assert resolved.statuses["EUDON.PA"] is Status.EXCLUDED
    assert "EUDON.PA" not in resolved.donors


def test_conflicting_overrides_fail_loudly(
    test_universe_path: Path, tmp_path: Path
) -> None:
    """Last-one-wins would make the answer depend on config file ordering."""

    def mutate(raw: dict[str, Any]) -> None:
        raw["event_overrides"].append(
            {
                "id": "contradicts_flip",
                "match": {"event_tags": ["special_regime"]},
                "set": {"FLIP.L": "excluded"},
                "reason": "deliberately contradictory",
            }
        )

    universe = load_universe(rewrite(test_universe_path, tmp_path, mutate))
    with pytest.raises(EventResolutionError, match="both assign"):
        universe.resolve_for_event("E", ("special_regime",), DATE)


def test_override_naming_an_unknown_unit_fails(
    test_universe_path: Path, tmp_path: Path
) -> None:
    def mutate(raw: dict[str, Any]) -> None:
        raw["event_overrides"].append(
            {
                "id": "ghost",
                "match": {"event_tags": ["special_regime"]},
                "set": {"NOSUCH.L": "treated"},
            }
        )

    universe = load_universe(rewrite(test_universe_path, tmp_path, mutate))
    with pytest.raises(EventResolutionError, match="not in the universe"):
        universe.resolve_for_event("E", ("special_regime",), DATE)


def test_exclusion_window_drops_both_units_of_a_merger(
    test_universe_path: Path,
) -> None:
    universe = load_universe(test_universe_path)
    inside = universe.resolve_for_event("E", (), pd.Timestamp("2022-07-15"))
    assert "MERGED_PRE" in inside.dropped
    assert "MERGED.L" in inside.dropped
    assert "merger" in inside.dropped["MERGED.L"]


def test_availability_drops_the_wrong_side_of_the_boundary(
    test_universe_path: Path,
) -> None:
    universe = load_universe(test_universe_path)
    early = universe.resolve_for_event("E", (), pd.Timestamp("2021-06-01"))
    assert "MERGED.L" in early.dropped
    assert early.statuses["MERGED_PRE"] is Status.TREATED

    late = universe.resolve_for_event("E", (), pd.Timestamp("2023-06-01"))
    assert "MERGED_PRE" in late.dropped
    assert late.statuses["MERGED.L"] is Status.TREATED


# -- notes.timezone --------------------------------------------------------


@pytest.mark.parametrize(
    ("unit", "expected"),
    [
        ("USDON", ClockClass.LATE),
        ("EUDON.PA", ClockClass.ALIGNED),
        ("DKDON.CO", ClockClass.EARLY),
        ("DON1.L", ClockClass.ALIGNED),
    ],
)
def test_clock_alignment_classification(
    test_universe_path: Path, unit: str, expected: ClockClass
) -> None:
    universe = load_universe(test_universe_path)
    assert universe.clock_alignment(unit).clock_class is expected


def test_only_the_us_name_needs_lagging(test_universe_path: Path) -> None:
    universe = load_universe(test_universe_path)
    assert universe.late_units == ("USDON",)
    assert universe.early_units == ("DKDON.CO",)


def test_alignment_none_rejected_with_overseas_units(
    test_universe_path: Path, tmp_path: Path
) -> None:
    def mutate(raw: dict[str, Any]) -> None:
        raw["meta"]["alignment"] = "none"

    with pytest.raises(UniverseConfigError, match="cross-market clock"):
        load_universe(rewrite(test_universe_path, tmp_path, mutate))


# -- structural consistency ------------------------------------------------


def test_a_unit_cannot_hold_two_default_statuses(
    test_universe_path: Path, tmp_path: Path
) -> None:
    def mutate(raw: dict[str, Any]) -> None:
        raw["donors"]["uk"].append({"unit_id": "TRT1.L", "name": "collision"})

    with pytest.raises(UniverseConfigError, match="more than once"):
        load_universe(rewrite(test_universe_path, tmp_path, mutate))


def test_missing_unit_id_is_refused(test_universe_path: Path, tmp_path: Path) -> None:
    def mutate(raw: dict[str, Any]) -> None:
        raw["treated"]["exposed_group"]["members"].append(
            {"unit_id": None, "name": "Some Unlisted Name"}
        )

    with pytest.raises(UniverseConfigError, match="AWAITING TICKER"):
        load_universe(rewrite(test_universe_path, tmp_path, mutate))


def test_max_donors_is_enforced(test_universe_path: Path, tmp_path: Path) -> None:
    def mutate(raw: dict[str, Any]) -> None:
        raw["meta"]["max_donors"] = 3

    with pytest.raises(UniverseConfigError, match="max_donors"):
        load_universe(rewrite(test_universe_path, tmp_path, mutate))


def test_unknown_exchange_suffix_is_refused(
    test_universe_path: Path, tmp_path: Path
) -> None:
    def mutate(raw: dict[str, Any]) -> None:
        raw["donors"]["uk"].append({"unit_id": "MYSTERY.XX", "name": "x"})

    with pytest.raises(UniverseConfigError, match="exchange_calendars"):
        load_universe(rewrite(test_universe_path, tmp_path, mutate))


def test_signed_portfolio_never_mixes_signs(test_universe_path: Path) -> None:
    universe = load_universe(test_universe_path)
    assert universe.signed_portfolio_members(ExpectedSign.POSITIVE) == (
        "TRT1.L",
        "TRT2.L",
        "MERGED_PRE",
        "MERGED.L",
    )
    assert universe.signed_portfolio_members(ExpectedSign.NEGATIVE) == ("TRT3.L",)


# -- the shipped config ----------------------------------------------------


def test_shipped_config_now_loads() -> None:
    """Part 0 unblocked it: every treated ticker supplied and verified."""
    universe = load_universe(UNIVERSE_CONFIG)
    assert len(universe.treated) >= 20
    assert universe.screening_universe is not None


def test_shipped_config_records_prs_reit_as_unresolved() -> None:
    """PRSR.L 404s on yfinance. Recorded, not guessed, not silently dropped."""
    universe = load_universe(UNIVERSE_CONFIG)
    entry = next(e for e in universe.unresolved if e.name == "PRS REIT")
    assert "404" in entry.finding or "not found" in entry.finding.lower()
    assert entry.proposed_ticker == "PRSR.L"


def test_shipped_config_separates_the_two_barratt_units() -> None:
    universe = load_universe(UNIVERSE_CONFIG)
    pre = universe.listing("BARRATT_PRE")
    post = universe.listing("BTRW.L")
    assert pre.source_ticker == "BTRW.L", "pre-merger data comes from the same symbol"
    assert pre.available_to is not None
    assert post.available_from is not None
    assert pre.available_to < post.available_from


def test_shipped_config_drops_barratt_across_the_merger() -> None:
    universe = load_universe(UNIVERSE_CONFIG)
    during = universe.resolve_for_event("E", (), pd.Timestamp("2024-06-01"))
    assert "BARRATT_PRE" in during.dropped
    assert "BTRW.L" in during.dropped


def test_shipped_config_flips_segro_on_commercial_mees() -> None:
    universe = load_universe(UNIVERSE_CONFIG)
    domestic = universe.resolve_for_event("E", (), pd.Timestamp("2023-09-20"))
    commercial = universe.resolve_for_event(
        "E", ("commercial_mees",), pd.Timestamp("2023-09-20")
    )
    assert domestic.statuses["SGRO.L"] is Status.DONOR
    assert commercial.statuses["SGRO.L"] is Status.TREATED
