"""Schema for the hand-curated event dictionary, and event-day resolution.

The event dictionary is the primary input to this project and it is treated as
data requiring provenance, not as constants typed into a notebook. Two columns
carry the whole point-in-time story and are therefore mandatory with no
default and no fallback:

``source_url``
    Where the announcement was published. Without it the row cannot be
    audited, and an event study whose dates cannot be audited is not a result.

``announcement_timestamp_utc``
    *When it became public*, not the date it describes. `CLAUDE.md` §2.5: an
    announcement landing at 15:00 London makes that day's close-to-close
    return a mixture of pre- and post-announcement information. Recording only
    the date silently discards the information needed to notice that.

Event-day resolution
--------------------
A trading day ``d`` has an open ``O(d)`` and a close ``C(d)``. Its
close-to-close return ``R(d)`` spans ``(C(prev(d)), C(d)]``, but **price
formation within that span only happens between ``O(d)`` and ``C(d)``** --
the overnight portion contains no trading. That distinction is what decides
contamination, and using the close alone gets it wrong:

* ``R(d)`` **straddles** the announcement when ``O(d) < ts < C(d)``, i.e. the
  news landed mid-session and the day's return mixes pre- and
  post-announcement prices;
* ``R(d)`` is **fully post-announcement** when ``ts <= O(d)``, including the
  common case of a 07:30 London press release: it lands after the previous
  close but before the open, so no pre-announcement trading occurred inside
  the interval and the whole day's move is a reaction to it;
* ``R(d)`` is **fully pre-announcement** when ``C(d) <= ts``.

There is at most one straddling day, and :class:`EventTiming` names it
explicitly rather than letting it hide inside a ``(0, +1)`` window. The
default convention is to open the event window at the first *fully
post-announcement* day and to report the straddling day's return separately.
That is the conservative reading of `CLAUDE.md` §2.5; the alternative
(``EventDayConvention.INCLUDE_STRADDLE``, which is what most published event
studies do) is available and is recorded in the output so a table can never
mix the two without saying so.

Unknown announcement times
--------------------------
Where the time could not be recovered, the curator records the date with a
``00:00:00+00:00`` time and sets ``time_known`` to ``false`` (or omits the
column, in which case a midnight timestamp is *inferred* to mean "time
unknown" and a warning is recorded). `docs/data_inventory.md` §8 is explicit
that GOV.UK gives publication date reliably and publication time less so, and
that the honest response is to widen the window rather than guess. Rows with
an unknown time are forced onto the conservative convention: the entire
announcement day is treated as straddling.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Final

import pandas as pd

#: Columns the curator must supply. Absence of any one of these is a hard
#: rejection, not a warning -- see `validate.py`.
REQUIRED_COLUMNS: Final[tuple[str, ...]] = (
    "date",
    "announcement_timestamp_utc",
    "policy",
    "source_url",
    "anticipation_risk",
    "expected_direction",
    "affected_sectors",
    # Added 2026-08-15. `direction` makes the mandate/repeal falsification test
    # executable rather than a design property described in prose.
    "direction",
)

#: Columns the validator will use if present and will not miss if absent.
#: Every one of these makes the identification argument sharper; none of them
#: is required, because a schema that demands more than a curator can honestly
#: supply gets filled in with guesses.
OPTIONAL_COLUMNS: Final[tuple[str, ...]] = (
    "event_id",
    "time_known",
    "scheduled",
    "confounders",
    "event_tags",
    "leak_note",
    "notes",
    # Which exposure channels the policy touches; scores every other channel
    # to zero for this event rather than letting an unrelated channel
    # contribute noise.
    "channel_targets",
    # Free text: what specifically was unanticipated. The curator's answer to
    # "why should this event have moved anything at all".
    "surprise_note",
    # Explicit acknowledgement that this event sits closer to another than the
    # minimum spacing allows. Clustered events are not independent and the
    # pooled inference assumes they are.
    "overlap_ack",
)

#: Separator for the list-valued columns (`affected_sectors`, `event_tags`).
#: Semicolon rather than comma so the file survives naive CSV editing.
LIST_SEPARATOR: Final[str] = ";"

#: London Stock Exchange regular session, local time. Both bounds matter: the
#: open decides whether a pre-market announcement contaminates the day's
#: return (it does not), the close decides when the day's return ends.
LSE_OPEN_LONDON: Final[tuple[int, int]] = (8, 0)
LSE_CLOSE_LONDON: Final[tuple[int, int]] = (16, 30)
LONDON_TZ: Final[str] = "Europe/London"


class AnticipationRisk(enum.StrEnum):
    """How much of the announcement was already in the price.

    This is an identification property, not a nuisance flag. An announcement
    the market fully anticipated has, by construction, no announcement-date
    effect to find; a null result on such an event says nothing about whether
    the policy mattered. `HIGH` rows are analysed and reported separately and
    are never pooled into a headline average -- see `diagnostics/power.py` and
    the anticipation section of `reports/event_study.md`.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ExpectedDirection(enum.StrEnum):
    """Sign the curator predicted *before* seeing the returns.

    Recording this in the dictionary rather than inferring it after the fact
    is what makes a one-sided reading of the result legitimate. `AMBIGUOUS`
    is an honest and common answer -- an efficiency mandate is a cost to
    residential landlords and a revenue opportunity to insulation makers, and
    `config/universe.yaml` warns against pooling opposite-signed units.
    """

    POSITIVE = "positive"
    NEGATIVE = "negative"
    AMBIGUOUS = "ambiguous"


class PolicyDirection(enum.StrEnum):
    """Whether the announcement tightens or loosens the standard.

    The multiplier that makes the project's central falsification test
    executable. Exposure sign is anchored to policy *direction* rather than to
    the individual event, so one `channel_sign` per firm serves every event and
    **a mandate and its repeal must produce opposite-signed betas** on the
    direction-neutral exposure measure. If they do not, the exposure
    construction is measuring something other than policy exposure.

    Required in the event dictionary with no default: a guessed direction
    silently inverts the falsification test rather than failing it.
    """

    TIGHTEN = "tighten"
    LOOSEN = "loosen"

    @property
    def multiplier(self) -> float:
        """+1 for a tightening, -1 for a loosening."""
        return 1.0 if self is PolicyDirection.TIGHTEN else -1.0


class EventDayConvention(enum.StrEnum):
    """Which trading day opens the event window.

    `FIRST_CLEAN_CLOSE`
        Window opens at the first day whose close-to-close return lies
        entirely after the announcement. No pre-announcement information
        enters day 0. This is the default and the `CLAUDE.md` §2.5 reading.

    `INCLUDE_STRADDLE`
        Window opens at the straddling day -- what most published event
        studies do when they use a ``(0, +1)`` window. Day 0 mixes pre- and
        post-announcement information, which attenuates the estimate toward
        zero by an unknown amount. Permitted, recorded, never silent.
    """

    FIRST_CLEAN_CLOSE = "first_clean_close"
    INCLUDE_STRADDLE = "include_straddle"


@dataclass(frozen=True)
class EventTiming:
    """Resolution of an announcement timestamp against a trading calendar.

    Attributes
    ----------
    announcement_ts_utc
        The announcement timestamp as curated, tz-aware UTC.
    time_known
        False where the curator could not recover the publication time. When
        False, `straddling_day` is the whole announcement day by construction
        and `convention` is forced to `FIRST_CLEAN_CLOSE`.
    straddling_day
        The trading day whose close-to-close return spans the announcement,
        or None when the announcement fell outside trading hours and no
        return is contaminated.
    first_clean_day
        First trading day whose return lies entirely after the announcement.
    t0
        The day the event window opens, given `convention`.
    convention
        Which of the two conventions produced `t0`.
    """

    announcement_ts_utc: pd.Timestamp
    time_known: bool
    straddling_day: pd.Timestamp | None
    first_clean_day: pd.Timestamp
    t0: pd.Timestamp
    convention: EventDayConvention

    @property
    def straddle_is_excluded(self) -> bool:
        """True when a contaminated return exists and was kept out of day 0."""
        return self.straddling_day is not None and self.t0 != self.straddling_day


@dataclass(frozen=True)
class PolicyEvent:
    """One curated announcement.

    Constructed only by `events.loader.load_events`, which routes every row
    through `events.validate` first. Nothing else should build one of these
    from raw strings.
    """

    event_id: str
    date: pd.Timestamp
    announcement_ts_utc: pd.Timestamp
    policy: str
    source_url: str
    anticipation_risk: AnticipationRisk
    expected_direction: ExpectedDirection
    affected_sectors: tuple[str, ...]
    direction: PolicyDirection
    channel_targets: tuple[str, ...] = ()
    surprise_note: str = ""
    overlap_ack: bool = False
    time_known: bool = True
    scheduled: bool | None = None
    confounders: tuple[str, ...] = ()
    event_tags: tuple[str, ...] = ()
    leak_note: str = ""
    notes: str = ""

    @property
    def requires_separate_reporting(self) -> bool:
        """True where pooling this event into a headline average is unsound.

        Fires on high anticipation risk (no announcement-date effect to find
        by construction), on any recorded confounder (`docs/research_plan.md`
        Phase B0 class (c) -- Budget days and MPC days make a firm-level event
        study uninterpretable), and on a recorded leak (the effective event
        date is the leak, not the podium).
        """
        return (
            self.anticipation_risk is AnticipationRisk.HIGH
            or bool(self.confounders)
            or bool(self.leak_note.strip())
        )


def _session_timestamps(
    trading_days: pd.DatetimeIndex, local_time: tuple[int, int]
) -> pd.DatetimeIndex:
    """Map trading dates to a session instant in UTC.

    `trading_days` carries dates; the session bound is given in *London* local
    time, which is one UTC offset under BST and another under GMT. Going
    through the London zone rather than a fixed offset is what keeps
    resolution correct across the clock change -- a 16:30 close is 15:30 UTC
    in July and 16:30 UTC in January, and an announcement at 16:00 UTC is
    intraday in one and after the close in the other.
    """
    hour, minute = local_time
    naive = trading_days.tz_localize(None).normalize() + pd.Timedelta(
        hours=hour, minutes=minute
    )
    return (
        naive.tz_localize(LONDON_TZ, ambiguous=True, nonexistent="shift_forward")
        .tz_convert("UTC")
        .as_unit("ns")
    )


def resolve_event_timing(
    announcement_ts_utc: pd.Timestamp,
    trading_days: pd.DatetimeIndex,
    *,
    time_known: bool = True,
    convention: EventDayConvention = EventDayConvention.FIRST_CLEAN_CLOSE,
) -> EventTiming:
    """Locate an announcement on a trading calendar.

    Parameters
    ----------
    announcement_ts_utc
        Tz-aware UTC announcement timestamp.
    trading_days
        Tz-aware UTC `DatetimeIndex` of trading dates, ascending. In practice
        this is the index of the assembled price panel, so the calendar is the
        one the data actually has rather than an assumed one.
    time_known
        False forces the conservative resolution described in the module
        docstring: the whole announcement day is treated as straddling.
    convention
        Which day opens the window. Ignored (forced to `FIRST_CLEAN_CLOSE`)
        when `time_known` is False, because `INCLUDE_STRADDLE` on an unknown
        time means opening the window on a day that may lie entirely before
        the announcement.

    Raises
    ------
    ValueError
        If the timestamp is naive, or the calendar has no trading day after
        the announcement -- the latter meaning the event is at or past the end
        of the sample and has no post-period to measure.
    """
    if announcement_ts_utc.tzinfo is None:
        msg = (
            "announcement timestamp is timezone-naive; event timing cannot be "
            "resolved without a zone (CLAUDE.md §2.5)"
        )
        raise ValueError(msg)

    ts = announcement_ts_utc.tz_convert("UTC")
    opens = _session_timestamps(trading_days, LSE_OPEN_LONDON)
    closes = _session_timestamps(trading_days, LSE_CLOSE_LONDON)

    if not time_known:
        # Conservative: pretend the announcement landed mid-session on its own
        # London date, so that date's return is treated as contaminated.
        london_date = ts.tz_convert(LONDON_TZ).normalize()
        same_day = trading_days[
            trading_days.tz_convert(LONDON_TZ).normalize() == london_date
        ]
        straddling = same_day[0] if len(same_day) else None
        after = trading_days[
            trading_days > (straddling if straddling is not None else ts)
        ]
        if not len(after):
            msg = f"no trading day follows the announcement on {london_date.date()}"
            raise ValueError(msg)
        first_clean = after[0]
        return EventTiming(
            announcement_ts_utc=ts,
            time_known=False,
            straddling_day=straddling,
            first_clean_day=first_clean,
            t0=first_clean,
            convention=EventDayConvention.FIRST_CLEAN_CLOSE,
        )

    # R(d) is fully post-announcement iff no trading in that day's session
    # preceded the announcement, i.e. ts is at or before the day's open.
    open_series = pd.Series(opens, index=trading_days)
    close_series = pd.Series(closes, index=trading_days)

    fully_post = open_series >= ts
    if not fully_post.any():
        msg = (
            f"no trading day in the calendar has a return lying entirely after "
            f"{ts.isoformat()}; the event is at or beyond the end of the sample"
        )
        raise ValueError(msg)
    first_clean = pd.Timestamp(fully_post.idxmax())

    # Straddling means the announcement landed mid-session.
    straddling_mask = (open_series < ts) & (close_series > ts)
    straddling = (
        pd.Timestamp(straddling_mask.idxmax()) if straddling_mask.any() else None
    )

    t0 = (
        straddling
        if convention is EventDayConvention.INCLUDE_STRADDLE and straddling is not None
        else first_clean
    )
    return EventTiming(
        announcement_ts_utc=ts,
        time_known=True,
        straddling_day=straddling,
        first_clean_day=first_clean,
        t0=t0,
        convention=convention,
    )


@dataclass(frozen=True)
class ValidationIssue:
    """One problem found in the event dictionary.

    `fatal` issues reject the file. Non-fatal issues are warnings that are
    carried into the report rather than printed and forgotten.
    """

    row: int
    column: str
    message: str
    fatal: bool = True


@dataclass
class ValidationReport:
    """Outcome of validating the event dictionary."""

    issues: list[ValidationIssue] = field(default_factory=list)
    n_rows: int = 0

    @property
    def fatal_issues(self) -> list[ValidationIssue]:
        """Issues that reject the file."""
        return [issue for issue in self.issues if issue.fatal]

    @property
    def warnings(self) -> list[ValidationIssue]:
        """Issues recorded and carried into the report, but not rejecting."""
        return [issue for issue in self.issues if not issue.fatal]

    @property
    def ok(self) -> bool:
        """True when nothing fatal was found."""
        return not self.fatal_issues

    def render(self) -> str:
        """Human-readable summary, suitable for an exception message."""
        if self.ok and not self.warnings:
            return f"event dictionary valid: {self.n_rows} row(s), no issues"
        lines = [f"event dictionary: {self.n_rows} row(s)"]
        for issue in self.fatal_issues:
            lines.append(f"  FATAL  row {issue.row} [{issue.column}]: {issue.message}")
        for issue in self.warnings:
            lines.append(f"  WARN   row {issue.row} [{issue.column}]: {issue.message}")
        return "\n".join(lines)
