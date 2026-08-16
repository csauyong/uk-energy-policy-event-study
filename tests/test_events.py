"""Event dictionary: schema, validation, and event-day resolution."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from policy_event_study.events.grouping import assign_event_groups, attach_cluster_ids
from policy_event_study.events.loader import load_events, write_events_template
from policy_event_study.events.schema import (
    REQUIRED_COLUMNS,
    AnticipationRisk,
    EventDayConvention,
    ExpectedDirection,
    PolicyDirection,
    PolicyEvent,
    resolve_event_timing,
)
from policy_event_study.events.validate import (
    EventValidationError,
    validate_events_frame,
)
from tests.conftest import make_trading_days

NOW = pd.Timestamp("2026-08-15", tz="UTC")


def good_row(**overrides: str) -> dict[str, str]:
    row = {
        "date": "2023-09-20",
        "announcement_timestamp_utc": "2023-09-20T19:00:00+00:00",
        "policy": "PM speech rowing back the boiler phase-out",
        "source_url": "https://www.gov.uk/government/speeches/pm-speech-net-zero",
        "anticipation_risk": "low",
        "expected_direction": "negative",
        "affected_sectors": "insulation_and_materials;residential_landlords",
        "direction": "loosen",
    }
    row.update(overrides)
    return row


def frame_of(*rows: dict[str, str]) -> pd.DataFrame:
    return pd.DataFrame(list(rows)).astype(str)


# -- the two rejections the brief names ------------------------------------


def test_missing_source_url_is_rejected() -> None:
    report = validate_events_frame(frame_of(good_row(source_url="")), now=NOW)
    assert not report.ok
    assert any(issue.column == "source_url" for issue in report.fatal_issues)


def test_missing_timestamp_is_rejected() -> None:
    report = validate_events_frame(
        frame_of(good_row(announcement_timestamp_utc="")), now=NOW
    )
    assert not report.ok
    assert any(
        issue.column == "announcement_timestamp_utc" for issue in report.fatal_issues
    )


def test_good_row_passes() -> None:
    report = validate_events_frame(frame_of(good_row()), now=NOW)
    assert report.ok, report.render()


# -- the further rejections ------------------------------------------------


def test_naive_timestamp_is_rejected() -> None:
    report = validate_events_frame(
        frame_of(good_row(announcement_timestamp_utc="2023-09-20 19:00:00")), now=NOW
    )
    assert not report.ok


def test_bare_domain_url_warns_but_does_not_reject() -> None:
    report = validate_events_frame(
        frame_of(good_row(source_url="https://www.gov.uk")), now=NOW
    )
    assert report.ok
    assert any(issue.column == "source_url" for issue in report.warnings)


def test_non_http_url_is_rejected() -> None:
    report = validate_events_frame(
        frame_of(good_row(source_url="file:///home/me/notes.txt")), now=NOW
    )
    assert not report.ok


def test_date_disagreeing_with_timestamp_is_rejected() -> None:
    """A London-date/UTC-timestamp mismatch is unresolvable, so the row fails."""
    report = validate_events_frame(frame_of(good_row(date="2023-09-21")), now=NOW)
    assert not report.ok
    assert any(issue.column == "date" for issue in report.fatal_issues)


def test_bst_boundary_date_is_accepted() -> None:
    """23:30 UTC in July is 00:30 London the next day -- the `date` must match."""
    report = validate_events_frame(
        frame_of(
            good_row(
                date="2023-07-21",
                announcement_timestamp_utc="2023-07-20T23:30:00+00:00",
            )
        ),
        now=NOW,
    )
    assert report.ok, report.render()


@pytest.mark.parametrize("column", ["anticipation_risk", "expected_direction"])
def test_enum_columns_reject_unknown_values(column: str) -> None:
    report = validate_events_frame(frame_of(good_row(**{column: "quite"})), now=NOW)
    assert not report.ok


def test_missing_required_column_is_rejected() -> None:
    row = good_row()
    del row["affected_sectors"]
    report = validate_events_frame(frame_of(row), now=NOW)
    assert not report.ok


def test_unknown_sector_key_is_rejected_when_whitelist_supplied() -> None:
    report = validate_events_frame(
        frame_of(good_row(affected_sectors="insulaton_and_materials")),
        known_sectors=["insulation_and_materials", "housebuilders"],
        now=NOW,
    )
    assert not report.ok


def test_high_anticipation_without_a_note_warns() -> None:
    report = validate_events_frame(
        frame_of(good_row(anticipation_risk="high")), now=NOW
    )
    assert report.ok
    assert any(issue.column == "anticipation_risk" for issue in report.warnings)


def test_midnight_timestamp_infers_unknown_time_and_warns() -> None:
    report = validate_events_frame(
        frame_of(
            good_row(
                date="2020-07-08",
                announcement_timestamp_utc="2020-07-08T00:00:00+00:00",
            )
        ),
        now=NOW,
    )
    assert report.ok
    assert any("time_known" in issue.message for issue in report.warnings)


def test_future_event_warns() -> None:
    report = validate_events_frame(
        frame_of(
            good_row(
                date="2027-01-04",
                announcement_timestamp_utc="2027-01-04T09:00:00+00:00",
            )
        ),
        now=NOW,
    )
    assert report.ok
    assert report.warnings


def test_duplicate_event_id_is_rejected() -> None:
    report = validate_events_frame(
        frame_of(
            good_row(event_id="e1"),
            good_row(
                event_id="e1",
                date="2023-10-20",
                announcement_timestamp_utc="2023-10-20T19:00:00+00:00",
            ),
        ),
        now=NOW,
    )
    assert not report.ok


# -- loading ---------------------------------------------------------------


def test_load_events_constructs_and_flags(tmp_path: Path) -> None:
    path = tmp_path / "events.csv"
    frame_of(
        good_row(
            anticipation_risk="high",
            leak_note="Trailed by the BBC the night before",
            confounders="autumn_statement",
            event_tags="uk_domestic_policy",
        )
    ).to_csv(path, index=False)

    events, report = load_events(path, now=NOW)
    assert report.ok
    assert len(events) == 1
    event = events[0]
    assert event.source_url.startswith("https://")
    assert event.affected_sectors == (
        "insulation_and_materials",
        "residential_landlords",
    )
    assert event.confounders == ("autumn_statement",)
    # High anticipation, a confounder and a leak note each independently route
    # the event out of any pooled headline.
    assert event.requires_separate_reporting


def test_load_events_raises_on_fatal(tmp_path: Path) -> None:
    path = tmp_path / "events.csv"
    frame_of(good_row(source_url="")).to_csv(path, index=False)
    with pytest.raises(EventValidationError):
        load_events(path, now=NOW)


def test_committed_template_has_the_required_header() -> None:
    """The shipped CSV must carry the full schema even though it has no rows."""
    from policy_event_study.paths import EVENTS_CSV

    header = EVENTS_CSV.read_text(encoding="utf-8").splitlines()[0].split(",")
    assert set(REQUIRED_COLUMNS).issubset(header)


def test_write_template_refuses_to_clobber(tmp_path: Path) -> None:
    path = tmp_path / "events.csv"
    write_events_template(path)
    with pytest.raises(FileExistsError):
        write_events_template(path)


# -- event-day resolution --------------------------------------------------


@pytest.mark.pointintime
def test_before_the_open_gives_a_clean_same_day_return() -> None:
    """07:30 London: the whole close-to-close return for that day is post-news."""
    days = make_trading_days(20, start="2023-10-16")
    timing = resolve_event_timing(
        pd.Timestamp("2023-10-19T06:30:00Z"),
        days,  # 07:30 London under BST
    )
    assert timing.first_clean_day == pd.Timestamp("2023-10-19", tz="UTC")
    assert timing.straddling_day is None
    assert timing.t0 == pd.Timestamp("2023-10-19", tz="UTC")


@pytest.mark.pointintime
def test_intraday_announcement_straddles_and_is_excluded_by_default() -> None:
    """14:00 London: that day's return mixes pre- and post-announcement."""
    days = make_trading_days(20, start="2023-10-16")
    timing = resolve_event_timing(pd.Timestamp("2023-10-19T13:00:00Z"), days)
    assert timing.straddling_day == pd.Timestamp("2023-10-19", tz="UTC")
    assert timing.t0 == pd.Timestamp("2023-10-20", tz="UTC")
    assert timing.straddle_is_excluded


@pytest.mark.pointintime
def test_include_straddle_convention_opens_on_the_contaminated_day() -> None:
    days = make_trading_days(20, start="2023-10-16")
    timing = resolve_event_timing(
        pd.Timestamp("2023-10-19T13:00:00Z"),
        days,
        convention=EventDayConvention.INCLUDE_STRADDLE,
    )
    assert timing.t0 == pd.Timestamp("2023-10-19", tz="UTC")
    assert not timing.straddle_is_excluded


@pytest.mark.pointintime
def test_after_the_close_rolls_to_the_next_trading_day() -> None:
    """20:00 London on a Friday: t0 is the following Monday."""
    days = make_trading_days(20, start="2023-10-16")
    timing = resolve_event_timing(pd.Timestamp("2023-10-20T19:00:00Z"), days)
    assert timing.straddling_day is None
    assert timing.t0 == pd.Timestamp("2023-10-23", tz="UTC")  # Monday


@pytest.mark.pointintime
def test_unknown_time_forces_the_conservative_convention() -> None:
    days = make_trading_days(20, start="2023-10-16")
    timing = resolve_event_timing(
        pd.Timestamp("2023-10-19T00:00:00Z"),
        days,
        time_known=False,
        convention=EventDayConvention.INCLUDE_STRADDLE,
    )
    assert timing.convention is EventDayConvention.FIRST_CLEAN_CLOSE
    assert timing.straddling_day == pd.Timestamp("2023-10-19", tz="UTC")
    assert timing.t0 == pd.Timestamp("2023-10-20", tz="UTC")


def test_naive_timestamp_cannot_be_resolved() -> None:
    days = make_trading_days(20, start="2023-10-16")
    with pytest.raises(ValueError, match="timezone-naive"):
        resolve_event_timing(pd.Timestamp("2023-10-19T13:00:00"), days)


# -- Fix 3 / scaffolding: direction and spacing ---------------------------


def test_direction_is_required() -> None:
    """It drives the falsification test; absent, the test vanishes silently."""
    row = good_row()
    del row["direction"]
    assert not validate_events_frame(frame_of(row), now=NOW).ok


def test_direction_rejects_a_value_outside_the_enum() -> None:
    report = validate_events_frame(frame_of(good_row(direction="reform")), now=NOW)
    assert not report.ok
    assert any(issue.column == "direction" for issue in report.fatal_issues)


@pytest.mark.parametrize("value", ["tighten", "loosen"])
def test_direction_accepts_both_members(value: str) -> None:
    assert validate_events_frame(frame_of(good_row(direction=value)), now=NOW).ok


def test_events_closer_than_the_minimum_spacing_are_rejected() -> None:
    """Overlapping windows are not independent clusters."""
    report = validate_events_frame(
        frame_of(
            good_row(event_id="a"),
            good_row(
                event_id="b",
                date="2023-09-25",
                announcement_timestamp_utc="2023-09-25T19:00:00+00:00",
            ),
        ),
        now=NOW,
    )
    assert not report.ok
    assert any("minimum" in issue.message for issue in report.fatal_issues)


def test_overlap_ack_permits_close_events() -> None:
    report = validate_events_frame(
        frame_of(
            good_row(event_id="a", overlap_ack="true"),
            good_row(
                event_id="b",
                date="2023-09-25",
                announcement_timestamp_utc="2023-09-25T19:00:00+00:00",
            ),
        ),
        now=NOW,
    )
    assert report.ok, report.render()


def test_spacing_threshold_is_configurable() -> None:
    rows = frame_of(
        good_row(event_id="a"),
        good_row(
            event_id="b",
            date="2023-10-10",
            announcement_timestamp_utc="2023-10-10T19:00:00+00:00",
        ),
    )
    assert not validate_events_frame(rows, now=NOW, min_spacing_days=30).ok
    assert validate_events_frame(rows, now=NOW, min_spacing_days=5).ok


def test_high_anticipation_always_warns_even_with_a_note() -> None:
    report = validate_events_frame(
        frame_of(good_row(anticipation_risk="high", leak_note="trailed on the 19th")),
        now=NOW,
    )
    assert report.ok
    assert any(
        "cannot produce an informative null" in issue.message
        for issue in report.warnings
    )


def test_loader_carries_the_new_columns(tmp_path: Path) -> None:
    path = tmp_path / "events.csv"
    frame_of(
        good_row(
            direction="tighten",
            channel_targets="residential_stock;product_revenue",
            surprise_note="Band C mandate was not in the consultation response",
        )
    ).to_csv(path, index=False)
    events, _ = load_events(path, now=NOW)
    event = events[0]
    assert event.direction is PolicyDirection.TIGHTEN
    assert event.channel_targets == ("residential_stock", "product_revenue")
    assert "consultation" in event.surprise_note


def test_committed_template_carries_the_new_columns() -> None:
    from policy_event_study.paths import EVENTS_CSV

    header = EVENTS_CSV.read_text(encoding="utf-8").splitlines()[0].split(",")
    for column in ("direction", "channel_targets", "surprise_note", "overlap_ack"):
        assert column in header


# -- Step 6: grouping, not acknowledgement --------------------------------


def make_event_at(event_id: str, day: str) -> PolicyEvent:
    return PolicyEvent(
        event_id=event_id,
        date=pd.Timestamp(day),
        announcement_ts_utc=pd.Timestamp(f"{day}T09:00:00Z"),
        policy="test",
        source_url="https://www.gov.uk/x",
        anticipation_risk=AnticipationRisk.LOW,
        expected_direction=ExpectedDirection.POSITIVE,
        affected_sectors=("insulation_and_materials",),
        direction=PolicyDirection.TIGHTEN,
    )


def test_well_spaced_events_stay_separate() -> None:
    grouping = assign_event_groups(
        [make_event_at("a", "2023-01-05"), make_event_at("b", "2023-03-05")],
        min_spacing_days=14,
    )
    assert grouping.n_groups == 2
    assert grouping.n_events == 2
    assert not grouping.collapsed


def test_close_events_collapse_into_one_group() -> None:
    grouping = assign_event_groups(
        [make_event_at("a", "2023-01-05"), make_event_at("b", "2023-01-12")],
        min_spacing_days=14,
    )
    assert grouping.n_groups == 1
    assert grouping.n_events == 2
    assert grouping.assignment["a"] == grouping.assignment["b"]


def test_grouping_is_transitive() -> None:
    """Days 1, 10 and 19 chain into one group even though 1 and 19 are 18 apart.

    Pairwise grouping would leave the ends separate and overstate the cluster
    count -- which would lower the bootstrap p-value floor exactly when
    dependence should raise it.
    """
    grouping = assign_event_groups(
        [
            make_event_at("a", "2023-01-01"),
            make_event_at("b", "2023-01-10"),
            make_event_at("c", "2023-01-19"),
        ],
        min_spacing_days=14,
    )
    assert grouping.n_groups == 1
    assert grouping.groups[0].span_days == 18
    assert grouping.groups[0].size == 3


def test_chain_breaks_where_the_gap_exceeds_the_threshold() -> None:
    grouping = assign_event_groups(
        [
            make_event_at("a", "2023-01-01"),
            make_event_at("b", "2023-01-10"),
            make_event_at("c", "2023-02-20"),
            make_event_at("d", "2023-02-25"),
        ],
        min_spacing_days=14,
    )
    assert grouping.n_groups == 2
    assert grouping.assignment["a"] == grouping.assignment["b"]
    assert grouping.assignment["c"] == grouping.assignment["d"]
    assert grouping.assignment["a"] != grouping.assignment["c"]


def test_grouping_summary_reports_both_counts() -> None:
    grouping = assign_event_groups(
        [make_event_at("a", "2023-01-05"), make_event_at("b", "2023-01-12")],
        min_spacing_days=14,
    )
    assert "2 event(s) collapse to 1 group(s)" in grouping.summary()
    assert not grouping.table().empty


def test_attach_cluster_ids_refuses_an_ungrouped_event() -> None:
    grouping = assign_event_groups([make_event_at("a", "2023-01-05")])
    frame = pd.DataFrame({"event_id": ["a", "ghost"], "car": [0.0, 0.0]})
    with pytest.raises(KeyError, match="no group assigned"):
        attach_cluster_ids(frame, grouping)


def test_grouping_lowers_the_cluster_count_the_estimator_sees() -> None:
    """The whole point: dependence must reduce independent clusters, not inflate them."""
    from policy_event_study.estimators.dose_response import (
        WeightScheme,
        estimate_dose_response,
    )
    from tests.test_dose_response import make_frame

    frame = make_frame(beta=0.0, n_events=6, n_firms=80)
    ungrouped = estimate_dose_response(
        frame, scheme=WeightScheme.WEBB, bootstrap_draws=50, randomisation_draws=1
    )
    # Collapse the six events into three groups.
    grouped_frame = frame.assign(
        cluster_id=frame["event_id"].map(
            {"E0": "g0", "E1": "g0", "E2": "g1", "E3": "g1", "E4": "g2", "E5": "g2"}
        )
    )
    grouped = estimate_dose_response(
        grouped_frame,
        scheme=WeightScheme.WEBB,
        bootstrap_draws=50,
        randomisation_draws=1,
    )
    assert ungrouped.n_events == 6
    assert grouped.n_events == 3
    # Fewer independent clusters means a higher floor, which is correct.
    assert grouped.p_floor_bootstrap >= ungrouped.p_floor_bootstrap
    assert any("GROUPED" in note for note in grouped.notes)


def test_missing_grouping_is_flagged_not_assumed_safe() -> None:
    from policy_event_study.estimators.dose_response import (
        WeightScheme,
        estimate_dose_response,
    )
    from tests.test_dose_response import make_frame

    result = estimate_dose_response(
        make_frame(n_events=4, n_firms=60),
        scheme=WeightScheme.WEBB,
        bootstrap_draws=50,
        randomisation_draws=1,
    )
    assert any("NO GROUPING APPLIED" in note for note in result.notes)
