"""Validation for the hand-curated event dictionary.

The contract is deliberately strict at the two points the brief names -- a row
without a source URL or without an announcement timestamp is rejected -- and
strict at several further points where a silent bad value would propagate into
every downstream estimate.

Design note: validation is separated from loading so the validator can be run
against a candidate file (`make events-check`) without constructing anything,
and so the test suite can assert on rejection reasons rather than on exception
text. Every check returns a `ValidationIssue` carrying its row and column;
nothing raises until the caller decides to.

Fatal vs warning
----------------
Fatal means the row cannot support an event study at all: no provenance, no
timestamp, an unparseable date, a category outside its enum. Warnings mean the
row is usable but carries a caveat that must reach the report -- an inferred
unknown announcement time, a high-anticipation event with no accompanying
note, a duplicated (date, policy) pair. Warnings are returned, not printed,
because a warning printed to a terminal during a batch run is a warning that
did not happen.
"""

from __future__ import annotations

import enum
import itertools
from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Final
from urllib.parse import urlparse

import pandas as pd

from policy_event_study.events.schema import (
    LIST_SEPARATOR,
    LONDON_TZ,
    OPTIONAL_COLUMNS,
    REQUIRED_COLUMNS,
    AnticipationRisk,
    ExpectedDirection,
    PolicyDirection,
    ValidationIssue,
    ValidationReport,
)

_TRUE_STRINGS: Final[frozenset[str]] = frozenset({"true", "yes", "y", "1", "t"})
_FALSE_STRINGS: Final[frozenset[str]] = frozenset({"false", "no", "n", "0", "f"})

#: Row offset applied when reporting row numbers, so a message points at the
#: line the curator sees in a spreadsheet: 1 for the header, 1 for 0-indexing.
_ROW_OFFSET: Final[int] = 2

#: Minimum trading-calendar-agnostic spacing between announcements, in days.
#: Below this, two events' windows overlap and their clusters are not
#: independent. Configurable per call; the default is a fortnight, comfortably
#: wider than the [0,2] event window plus a settling margin.
DEFAULT_MIN_SPACING_DAYS: Final[int] = 14


def parse_list_cell(value: str) -> tuple[str, ...]:
    """Split a list-valued cell on `LIST_SEPARATOR`, trimming and dropping blanks."""
    return tuple(part.strip() for part in value.split(LIST_SEPARATOR) if part.strip())


def parse_bool_cell(value: str) -> bool | None:
    """Parse an optional boolean cell. Returns None for blank or unrecognised."""
    lowered = value.strip().lower()
    if lowered in _TRUE_STRINGS:
        return True
    if lowered in _FALSE_STRINGS:
        return False
    return None


def _is_blank(value: object) -> bool:
    """Report whether a cell is None, NaN, empty, or whitespace-only."""
    if value is None:
        return True
    if isinstance(value, float):
        # A float cell is either NaN (blank) or a number someone typed into a
        # text column; neither is a usable value here.
        return bool(pd.isna(value))
    return str(value).strip() == ""


def _check_source_url(row_no: int, value: object) -> list[ValidationIssue]:
    """Require an auditable http(s) URL for the announcement."""
    if _is_blank(value):
        return [
            ValidationIssue(
                row=row_no,
                column="source_url",
                message=(
                    "missing source URL -- an event whose date cannot be audited "
                    "against its publication is not admissible evidence"
                ),
            )
        ]
    parsed = urlparse(str(value).strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return [
            ValidationIssue(
                row=row_no,
                column="source_url",
                message=f"not an http(s) URL: {value!r}",
            )
        ]
    issues: list[ValidationIssue] = []
    if not parsed.path.strip("/"):
        issues.append(
            ValidationIssue(
                row=row_no,
                column="source_url",
                message=(
                    f"bare domain {value!r} -- link the announcement itself, not "
                    "the publisher's home page"
                ),
                fatal=False,
            )
        )
    return issues


def _check_timestamp(
    row_no: int,
    raw_ts: object,
    raw_date: object,
    time_known_cell: object | None,
) -> tuple[pd.Timestamp | None, bool, list[ValidationIssue]]:
    """Parse and cross-check the announcement timestamp.

    Returns the parsed UTC timestamp (None if unusable), the resolved
    `time_known` flag, and any issues found.
    """
    issues: list[ValidationIssue] = []
    if _is_blank(raw_ts):
        issues.append(
            ValidationIssue(
                row=row_no,
                column="announcement_timestamp_utc",
                message=(
                    "missing announcement timestamp -- CLAUDE.md §2.5 requires the "
                    "moment the announcement became public, not only its date"
                ),
            )
        )
        return None, False, issues

    text = str(raw_ts).strip()
    try:
        parsed = pd.Timestamp(text)
    except (ValueError, TypeError) as exc:
        issues.append(
            ValidationIssue(
                row=row_no,
                column="announcement_timestamp_utc",
                message=f"unparseable timestamp {text!r}: {exc}",
            )
        )
        return None, False, issues

    if parsed.tzinfo is None:
        issues.append(
            ValidationIssue(
                row=row_no,
                column="announcement_timestamp_utc",
                message=(
                    f"timezone-naive timestamp {text!r} -- write an explicit offset "
                    "(e.g. 2023-09-20T15:30:00+00:00 or ...Z). A naive timestamp "
                    "read as UTC when it was London silently shifts the event day "
                    "under BST"
                ),
            )
        )
        return None, False, issues

    ts = parsed.tz_convert("UTC")

    # A midnight UTC timestamp is almost always a date placeholder rather than
    # a genuine 00:00 publication. Honour an explicit `time_known` cell where
    # the curator supplied one; otherwise infer and say so.
    explicit = (
        parse_bool_cell(str(time_known_cell)) if time_known_cell is not None else None
    )
    is_midnight = ts.hour == 0 and ts.minute == 0 and ts.second == 0
    if explicit is None:
        time_known = not is_midnight
        if is_midnight:
            issues.append(
                ValidationIssue(
                    row=row_no,
                    column="announcement_timestamp_utc",
                    message=(
                        "midnight UTC timestamp with no `time_known` column -- "
                        "inferring the publication time is unknown and forcing the "
                        "conservative event-day convention. Set `time_known` "
                        "explicitly to silence this"
                    ),
                    fatal=False,
                )
            )
    else:
        time_known = explicit
        if explicit and is_midnight:
            issues.append(
                ValidationIssue(
                    row=row_no,
                    column="time_known",
                    message=(
                        "`time_known` is true but the timestamp is exactly midnight "
                        "UTC (01:00 London under BST); confirm this is a real "
                        "publication time and not a placeholder"
                    ),
                    fatal=False,
                )
            )

    # Cross-check the redundant `date` column against the timestamp. The two
    # disagreeing means one of them is wrong, and there is no way to tell
    # which, so the row is rejected rather than silently resolved.
    if not _is_blank(raw_date):
        try:
            stated = pd.Timestamp(str(raw_date).strip()).date()
        except (ValueError, TypeError) as exc:
            issues.append(
                ValidationIssue(
                    row=row_no,
                    column="date",
                    message=f"unparseable date {raw_date!r}: {exc}",
                )
            )
        else:
            london_date = ts.tz_convert(LONDON_TZ).date()
            if stated != london_date:
                issues.append(
                    ValidationIssue(
                        row=row_no,
                        column="date",
                        message=(
                            f"`date` is {stated} but the announcement timestamp falls "
                            f"on {london_date} London. One of the two is wrong and "
                            "the row cannot be resolved automatically"
                        ),
                    )
                )
    return ts, time_known, issues


def _check_enum_cell(
    row_no: int,
    column: str,
    value: object,
    enum_cls: type[enum.StrEnum],
) -> list[ValidationIssue]:
    """Reject a categorical cell outside its enum."""
    permitted = ", ".join(member.value for member in enum_cls)
    if _is_blank(value):
        return [
            ValidationIssue(
                row=row_no,
                column=column,
                message=f"missing; must be one of: {permitted}",
            )
        ]
    if str(value).strip().lower() not in {member.value for member in enum_cls}:
        return [
            ValidationIssue(
                row=row_no,
                column=column,
                message=f"{value!r} is not one of: {permitted}",
            )
        ]
    return []


def _check_event_spacing(
    frame: pd.DataFrame, min_spacing_days: int
) -> list[ValidationIssue]:
    """Reject events closer together than `min_spacing_days` without an ack.

    Two announcements a week apart are not two independent observations. Their
    event windows overlap, the same firms appear in both, and the pooled
    inference -- which clusters by event and treats clusters as independent --
    silently double-counts. The wild cluster bootstrap is *particularly*
    sensitive to this, since its p-value floor is set by the nominal cluster
    count rather than the effective one.

    The curator can override per event with `overlap_ack`, which records that
    the dependence is known and accepted rather than unnoticed.
    """
    issues: list[ValidationIssue] = []
    parsed: list[tuple[int, pd.Timestamp, bool]] = []
    for position, (_, row) in enumerate(frame.iterrows()):
        raw = row.get("announcement_timestamp_utc")
        if _is_blank(raw):
            continue
        try:
            stamp = pd.Timestamp(str(raw).strip())
        except (TypeError, ValueError):
            continue
        if stamp.tzinfo is None:
            continue
        acknowledged = bool(parse_bool_cell(str(row.get("overlap_ack", ""))))
        parsed.append((position + _ROW_OFFSET, stamp.tz_convert("UTC"), acknowledged))

    parsed.sort(key=lambda item: item[1])
    for (row_a, stamp_a, ack_a), (row_b, stamp_b, ack_b) in itertools.pairwise(parsed):
        gap = (stamp_b - stamp_a).days
        if gap < min_spacing_days and not (ack_a or ack_b):
            issues.append(
                ValidationIssue(
                    row=row_b,
                    column="announcement_timestamp_utc",
                    message=(
                        f"only {gap} day(s) after the event on row {row_a}, below "
                        f"the {min_spacing_days}-day minimum. Overlapping event "
                        "windows are not independent clusters and the pooled "
                        "inference assumes they are. Set `overlap_ack` on one of "
                        "the two to record that this is known and accepted"
                    ),
                )
            )
    return issues


def validate_events_frame(
    frame: pd.DataFrame,
    *,
    known_sectors: Iterable[str] | None = None,
    now: pd.Timestamp | None = None,
    min_spacing_days: int = DEFAULT_MIN_SPACING_DAYS,
) -> ValidationReport:
    """Validate a raw event dictionary read as strings.

    Parameters
    ----------
    frame
        Event dictionary as read from CSV with `dtype=str` and
        `keep_default_na=False`, so blank cells are empty strings.
    known_sectors
        Sector keys the universe config defines. When supplied, an
        `affected_sectors` entry outside this set is fatal -- a typo'd sector
        silently selects an empty treated set otherwise.
    now
        Reference instant for the "event lies in the future" check. Defaults
        to the current UTC time; injected in tests for determinism.

    Returns
    -------
    ValidationReport
        Never raises on validation grounds. `report.ok` is the verdict;
        `report.render()` is the message.
    """
    reference = now if now is not None else pd.Timestamp.now(tz="UTC")
    report = ValidationReport(n_rows=len(frame))

    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        report.issues.append(
            ValidationIssue(
                row=0,
                column=",".join(missing),
                message=(
                    f"required column(s) absent: {missing}. Required schema is "
                    f"{list(REQUIRED_COLUMNS)}"
                ),
            )
        )
        return report

    unexpected = [
        column
        for column in frame.columns
        if column not in REQUIRED_COLUMNS and column not in OPTIONAL_COLUMNS
    ]
    if unexpected:
        report.issues.append(
            ValidationIssue(
                row=0,
                column=",".join(unexpected),
                message=(
                    f"unrecognised column(s) {unexpected} will be ignored; "
                    f"recognised optional columns are {list(OPTIONAL_COLUMNS)}"
                ),
                fatal=False,
            )
        )

    if not len(frame):
        report.issues.append(
            ValidationIssue(
                row=0,
                column="-",
                message=(
                    "event dictionary is empty. Curate it before running any "
                    "estimator -- see docs/research_plan.md Phase B0 and its kill "
                    "criterion (fewer than ~8-10 clean events means the panel "
                    "design is not viable and the single-event deep dive is the "
                    "documented fallback)"
                ),
                fatal=False,
            )
        )
        return report

    sector_whitelist = set(known_sectors) if known_sectors is not None else None
    seen_ids: Counter[str] = Counter()
    seen_date_policy: Counter[tuple[str, str]] = Counter()

    for position, (_, row) in enumerate(frame.iterrows()):
        row_no = position + _ROW_OFFSET
        cells: Mapping[str, object] = {
            str(key): value for key, value in row.to_dict().items()
        }

        report.issues.extend(_check_source_url(row_no, cells.get("source_url")))

        ts, _time_known, ts_issues = _check_timestamp(
            row_no,
            cells.get("announcement_timestamp_utc"),
            cells.get("date"),
            cells.get("time_known"),
        )
        report.issues.extend(ts_issues)

        if ts is not None and ts > reference:
            report.issues.append(
                ValidationIssue(
                    row=row_no,
                    column="announcement_timestamp_utc",
                    message=(
                        f"announcement is in the future ({ts.date()} > "
                        f"{reference.date()}); it has no post-event window"
                    ),
                    fatal=False,
                )
            )

        if _is_blank(cells.get("policy")):
            report.issues.append(
                ValidationIssue(
                    row=row_no,
                    column="policy",
                    message="missing policy description",
                )
            )

        report.issues.extend(
            _check_enum_cell(
                row_no,
                "anticipation_risk",
                cells.get("anticipation_risk"),
                AnticipationRisk,
            )
        )
        report.issues.extend(
            _check_enum_cell(
                row_no,
                "expected_direction",
                cells.get("expected_direction"),
                ExpectedDirection,
            )
        )
        # `direction` drives the mandate-versus-repeal falsification test. A
        # missing value would not fail that test, it would silently remove it.
        report.issues.extend(
            _check_enum_cell(
                row_no, "direction", cells.get("direction"), PolicyDirection
            )
        )

        sectors_raw = cells.get("affected_sectors")
        sectors = (
            parse_list_cell(str(sectors_raw)) if not _is_blank(sectors_raw) else ()
        )
        if not sectors:
            report.issues.append(
                ValidationIssue(
                    row=row_no,
                    column="affected_sectors",
                    message=(
                        f"missing; give one or more sector keys separated by "
                        f"{LIST_SEPARATOR!r}"
                    ),
                )
            )
        elif sector_whitelist is not None:
            unknown = [sector for sector in sectors if sector not in sector_whitelist]
            if unknown:
                report.issues.append(
                    ValidationIssue(
                        row=row_no,
                        column="affected_sectors",
                        message=(
                            f"sector key(s) {unknown} are not defined in the universe "
                            f"config; known keys are {sorted(sector_whitelist)}"
                        ),
                    )
                )

        risk_raw = str(cells.get("anticipation_risk", "")).strip().lower()
        if risk_raw == AnticipationRisk.HIGH.value:
            report.issues.append(
                ValidationIssue(
                    row=row_no,
                    column="anticipation_risk",
                    message=(
                        "high anticipation: this event cannot produce an "
                        "informative null, is excluded from every pooled figure, "
                        "and its estimate reads only as a bound on the residual "
                        "surprise at the podium"
                    ),
                    fatal=False,
                )
            )
        has_note = not _is_blank(cells.get("leak_note")) or not _is_blank(
            cells.get("notes")
        )
        if risk_raw == AnticipationRisk.HIGH.value and not has_note:
            report.issues.append(
                ValidationIssue(
                    row=row_no,
                    column="anticipation_risk",
                    message=(
                        "anticipation_risk is high but neither `leak_note` nor "
                        "`notes` explains what was already priced. The report is "
                        "required to discuss identification for these events, and "
                        "cannot do so from the flag alone"
                    ),
                    fatal=False,
                )
            )

        event_id = str(cells.get("event_id", "")).strip()
        if event_id:
            seen_ids[event_id] += 1
        date_policy_key = (
            str(cells.get("date", "")).strip(),
            str(cells.get("policy", "")).strip().lower(),
        )
        seen_date_policy[date_policy_key] += 1

    report.issues.extend(_check_event_spacing(frame, min_spacing_days))

    for duplicate_id, count in seen_ids.items():
        if count > 1:
            report.issues.append(
                ValidationIssue(
                    row=0,
                    column="event_id",
                    message=(
                        f"event_id {duplicate_id!r} appears {count} times; ids "
                        "must be unique"
                    ),
                )
            )
    for (date_key, policy_key), count in seen_date_policy.items():
        if count > 1 and date_key:
            report.issues.append(
                ValidationIssue(
                    row=0,
                    column="date,policy",
                    message=(
                        f"({date_key}, {policy_key!r}) appears {count} times; if these "
                        "are genuinely distinct announcements give them distinct "
                        "policy descriptions, otherwise the same shock is being "
                        "counted twice"
                    ),
                    fatal=False,
                )
            )

    return report


class EventValidationError(ValueError):
    """Raised when the event dictionary fails validation.

    Carries the full `ValidationReport` so a caller can inspect individual
    issues rather than parsing the message.
    """

    def __init__(self, report: ValidationReport) -> None:
        self.report = report
        super().__init__(report.render())
