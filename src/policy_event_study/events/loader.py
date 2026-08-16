"""Read and validate the hand-curated event dictionary.

This is the only sanctioned way to turn `data/events/uk_energy_policy_events.csv`
into :class:`PolicyEvent` objects. Every path through it validates first and
raises on anything fatal, so no downstream estimator can be handed a row with a
missing timestamp or an unauditable source.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

import pandas as pd

from policy_event_study.events.schema import (
    OPTIONAL_COLUMNS,
    REQUIRED_COLUMNS,
    AnticipationRisk,
    ExpectedDirection,
    PolicyDirection,
    PolicyEvent,
    ValidationReport,
)
from policy_event_study.events.validate import (
    EventValidationError,
    parse_bool_cell,
    parse_list_cell,
    validate_events_frame,
)
from policy_event_study.paths import EVENTS_CSV

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def _slugify(text: str, *, max_words: int = 5) -> str:
    """Build a short, stable, filename-safe token from a policy description."""
    words = _SLUG_STRIP.sub(" ", text.lower()).split()
    return "-".join(words[:max_words]) or "event"


def read_events_csv(path: Path | None = None) -> pd.DataFrame:
    """Read the event dictionary as raw strings, without validating.

    Source: hand-curated by the project owner from GOV.UK announcements
        (https://www.gov.uk/api/search.json), Hansard
        (https://hansard-api.parliament.uk), Ofgem and DESNZ press releases.
        See docs/data_inventory.md §8.
    Licence: the underlying announcements are OGL v3; the curation -- the
        classification, timing and confounder notes -- is this project's own
        and is version controlled alongside the code.
    Vintage: the file itself is the vintage. It is committed (the one
        deliberate exception to the `data/` gitignore, see paths.py) precisely
        so that "which events were in the study, and when did that change" is
        answerable from git history rather than from memory.
    Publication lag: none for the file, but every *row* carries its own
        knowability timestamp in `announcement_timestamp_utc`, and that column
        -- not the row's presence in the file -- governs what may be used
        when.

    Cells are read as strings with NA conversion disabled, so a blank cell is
    an empty string rather than a float NaN. That distinction matters: `nan`
    silently coerces through `str()` into the four-character text "nan", which
    would sail past a naive emptiness check.
    """
    target = path if path is not None else EVENTS_CSV
    if not target.exists():
        msg = (
            f"event dictionary not found at {target}. It is hand-curated, not "
            "generated -- create it from the header in "
            "data/events/uk_energy_policy_events.csv, or point `path` elsewhere."
        )
        raise FileNotFoundError(msg)
    return pd.read_csv(target, dtype=str, keep_default_na=False)


def validate_events_file(
    path: Path | None = None,
    *,
    known_sectors: Iterable[str] | None = None,
    now: pd.Timestamp | None = None,
) -> ValidationReport:
    """Validate the event dictionary on disk without constructing events."""
    return validate_events_frame(
        read_events_csv(path), known_sectors=known_sectors, now=now
    )


def load_events(
    path: Path | None = None,
    *,
    known_sectors: Iterable[str] | None = None,
    now: pd.Timestamp | None = None,
    strict: bool = True,
) -> tuple[tuple[PolicyEvent, ...], ValidationReport]:
    """Load, validate and construct the curated events.

    Parameters
    ----------
    path
        Defaults to `paths.EVENTS_CSV`.
    known_sectors
        Sector keys from the universe config. Supplying these turns a typo'd
        sector from a silently-empty treated set into a rejection.
    now
        Reference instant for the future-event check; injected in tests.
    strict
        When True (the default) any fatal issue raises
        :class:`EventValidationError`. Set False only to inspect a
        work-in-progress file; the returned events then exclude rows that
        failed, and the report says which.

    Returns
    -------
    tuple[tuple[PolicyEvent, ...], ValidationReport]
        The constructed events and the validation report. The report is
        returned even on success because its warnings -- inferred unknown
        announcement times, duplicated date/policy pairs -- are required
        content in `reports/event_study.md`, not console noise.
    """
    frame = read_events_csv(path)
    report = validate_events_frame(frame, known_sectors=known_sectors, now=now)
    if strict and not report.ok:
        raise EventValidationError(report)

    fatal_rows = {issue.row for issue in report.fatal_issues}
    events: list[PolicyEvent] = []

    for position, (_, row) in enumerate(frame.iterrows()):
        row_no = position + 2
        if row_no in fatal_rows:
            continue
        cells = {str(key): str(value) for key, value in row.to_dict().items()}
        ts = pd.Timestamp(cells["announcement_timestamp_utc"].strip()).tz_convert("UTC")

        explicit_time_known = parse_bool_cell(cells.get("time_known", ""))
        inferred_time_known = not (ts.hour == 0 and ts.minute == 0 and ts.second == 0)
        time_known = (
            explicit_time_known
            if explicit_time_known is not None
            else inferred_time_known
        )

        event_id = cells.get("event_id", "").strip()
        if not event_id:
            event_id = f"{ts.date().isoformat()}-{_slugify(cells['policy'])}"

        events.append(
            PolicyEvent(
                event_id=event_id,
                date=pd.Timestamp(cells["date"].strip()),
                announcement_ts_utc=ts,
                policy=cells["policy"].strip(),
                source_url=cells["source_url"].strip(),
                anticipation_risk=AnticipationRisk(
                    cells["anticipation_risk"].strip().lower()
                ),
                expected_direction=ExpectedDirection(
                    cells["expected_direction"].strip().lower()
                ),
                affected_sectors=parse_list_cell(cells["affected_sectors"]),
                direction=PolicyDirection(cells["direction"].strip().lower()),
                channel_targets=parse_list_cell(cells.get("channel_targets", "")),
                surprise_note=cells.get("surprise_note", "").strip(),
                overlap_ack=bool(parse_bool_cell(cells.get("overlap_ack", ""))),
                time_known=time_known,
                scheduled=parse_bool_cell(cells.get("scheduled", "")),
                confounders=parse_list_cell(cells.get("confounders", "")),
                event_tags=parse_list_cell(cells.get("event_tags", "")),
                leak_note=cells.get("leak_note", "").strip(),
                notes=cells.get("notes", "").strip(),
            )
        )

    return tuple(events), report


def write_events_template(path: Path | None = None, *, overwrite: bool = False) -> Path:
    """Write a header-only event dictionary with the full recognised schema.

    Writes required columns first, then the optional ones. Refuses to
    overwrite an existing file unless asked -- the target is hand-curated work
    that no loader can reconstruct.
    """
    target = path if path is not None else EVENTS_CSV
    if target.exists() and not overwrite:
        msg = (
            f"{target} already exists and holds hand-curated rows; pass "
            "overwrite=True only if you are certain"
        )
        raise FileExistsError(msg)
    target.parent.mkdir(parents=True, exist_ok=True)
    header = ",".join((*REQUIRED_COLUMNS, *OPTIONAL_COLUMNS))
    target.write_text(header + "\n", encoding="utf-8")
    return target
