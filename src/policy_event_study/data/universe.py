"""Load `config/universe.yaml` and enforce the constraints written in it.

Two things this module does that a plain config parser would not.

**Per-event status resolution.** Treated / donor / excluded is a *global
default plus per-event overrides*, not one global list. Some firms'
classification is genuinely event-dependent -- Segro is unexposed to domestic
efficiency policy and plausibly exposed to commercial MEES -- and a single
global list forces a wrong answer for one event or the other.
:meth:`Universe.resolve_for_event` applies the overrides, drops units outside
their availability or inside an exclusion window, and then **asserts that every
remaining unit has exactly one status**. Two overrides disagreeing is a hard
error rather than last-one-wins.

**Unit identity separated from data source.** ``unit_id`` is how a firm enters
the panel; ``source_ticker`` is what gets fetched. They differ whenever one
price series carries two economically distinct firms. That is not hypothetical
here: Yahoo serves Barratt Developments' entire pre-merger history under the
post-merger symbol ``BTRW.L`` and serves neither ``BDEV.L`` nor ``RDW.L``, so a
naive pull returns a series that silently changes firm mid-sample. Splitting
identity from source, plus availability bounds, is what prevents the splice.

The `notes:` block of the config is titled "NOTES ENCODED IN THE LOADER".
This module is that encoding:

======================= =====================================================
Note                    Enforcement
======================= =====================================================
``fx``                  FX rates are exposed only under
                        ``fx_screen_rates_to_gbp`` and consumed only by the
                        liquidity screen. `data/prices.py` has no
                        currency-conversion code path at all.
``timezone``            :meth:`Universe.clock_alignment` computes the actual
                        UTC offset between each exchange's close and the LSE
                        close under both BST and GMT, and classifies each unit
                        LATE / ALIGNED / EARLY.
``survivorship``        A hard flag propagated into every panel's provenance,
                        plus the explicit ``unresolved:`` register.
``matching_variable``   ``meta.outcome`` is a closed enum with no
                        ``price_level`` member.
``power``               :meth:`Universe.signed_portfolio_members`.
``overfitting``         ``max_donors`` enforced at load time.
======================= =====================================================

Nothing here reaches the network.
"""

from __future__ import annotations

import datetime as dt
import enum
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Final

import pandas as pd
import yaml

from policy_event_study.paths import PROJECT_ROOT, UNIVERSE_CONFIG

#: A unit whose exchange closes more than this many minutes after the LSE
#: close is LATE and is lagged under `alignment: lag_late_markets`. Ten minutes
#: of overlap is not a tradeable information asymmetry; four and a half hours
#: is.
LATE_MARKET_TOLERANCE_MINUTES: Final[int] = 15

LSE_SUFFIX: Final[str] = ".L"
LONDON_TZ: Final[str] = "Europe/London"

#: Two probe dates, one under GMT and one under BST, so the London/continental
#: offset is evaluated in both regimes rather than assumed constant.
_PROBE_DATES: Final[tuple[str, str]] = ("2024-01-17", "2024-07-17")


class UniverseConfigError(ValueError):
    """Raised when `config/universe.yaml` is internally inconsistent."""


class EventResolutionError(ValueError):
    """Raised when an event cannot be resolved to exactly one status per unit.

    Separate from :class:`UniverseConfigError` because it fires at *event*
    resolution time rather than at load time: a config can be globally
    consistent and still ambiguous for one particular event's tag set.
    """


class Status(enum.StrEnum):
    """A unit's role for one event."""

    TREATED = "treated"
    DONOR = "donor"
    EXCLUDED = "excluded"
    MARKET_INDEX = "market_index"


class ExpectedSign(enum.StrEnum):
    """Sign of a treated group's response to a *tightening* of UK policy."""

    POSITIVE = "positive"
    NEGATIVE = "negative"
    AMBIGUOUS = "ambiguous"


class Outcome(enum.StrEnum):
    """Permitted SC/SDiD matching variables. Deliberately no ``price_level``."""

    CUMULATIVE_SIMPLE_RETURNS = "cumulative_simple_returns"
    CUMULATIVE_LOG_RETURNS = "cumulative_log_returns"


class Alignment(enum.StrEnum):
    """How cross-market clock misalignment is handled. See `notes.timezone`."""

    LAG_LATE_MARKETS = "lag_late_markets"
    TWO_DAY_WINDOW = "two_day_window"
    NONE = "none"


class ClockClass(enum.StrEnum):
    """Where an exchange's close sits relative to the LSE close."""

    LATE = "late"
    ALIGNED = "aligned"
    EARLY = "early"


@dataclass(frozen=True)
class ExchangeSpec:
    """Closing convention for one exchange."""

    suffix: str
    tz: str
    close_local: dt.time
    currency: str

    def close_utc_on(self, date: pd.Timestamp) -> pd.Timestamp:
        """UTC instant of this exchange's close on a given calendar date."""
        naive = pd.Timestamp(date).tz_localize(None).normalize() + pd.Timedelta(
            hours=self.close_local.hour, minutes=self.close_local.minute
        )
        return naive.tz_localize(
            self.tz, ambiguous=True, nonexistent="shift_forward"
        ).tz_convert("UTC")


@dataclass(frozen=True)
class ExclusionWindow:
    """A date range over which named units are unusable.

    Not the same thing as an availability bound. Availability says a series
    does not exist; an exclusion window says it exists but is contaminated by
    a shock of its own -- a merger, a restatement, a suspension -- and any
    event landing inside it must drop those units.
    """

    unit_ids: tuple[str, ...]
    start: pd.Timestamp
    end: pd.Timestamp
    reason: str

    def covers(self, moment: pd.Timestamp) -> bool:
        """Report whether `moment` falls inside the window, inclusive."""
        stamp = pd.Timestamp(moment).tz_localize(None).normalize()
        return bool(self.start <= stamp <= self.end)


@dataclass(frozen=True)
class Listing:
    """One unit in the universe.

    Attributes
    ----------
    unit_id
        How the firm enters the panel. Unique across the universe.
    source_ticker
        What to fetch. Defaults to `unit_id`; differs when one price series
        carries two economically distinct units.
    available_from, available_to
        Bounds outside which this unit does not exist. For `BARRATT_PRE` the
        upper bound is the day before the merger completed; for `BTRW.L` the
        lower bound is the day after. Together they make the boundary
        uncrossable rather than merely discouraged.
    """

    unit_id: str
    name: str
    group: str
    default_status: Status
    exchange: ExchangeSpec
    source_ticker: str = ""
    available_from: pd.Timestamp | None = None
    available_to: pd.Timestamp | None = None
    verify: bool = False
    note: str = ""

    def __post_init__(self) -> None:
        """Default `source_ticker` to `unit_id`."""
        if not self.source_ticker:
            object.__setattr__(self, "source_ticker", self.unit_id)

    @property
    def is_london(self) -> bool:
        """True for LSE listings."""
        return self.exchange.suffix == LSE_SUFFIX

    @property
    def is_aliased(self) -> bool:
        """True where this unit's data comes from another unit's symbol."""
        return self.source_ticker != self.unit_id

    def available_on(self, moment: pd.Timestamp) -> bool:
        """Report whether the unit exists on the given date."""
        stamp = pd.Timestamp(moment).tz_localize(None).normalize()
        if self.available_from is not None and stamp < self.available_from:
            return False
        return not (self.available_to is not None and stamp > self.available_to)


@dataclass(frozen=True)
class TreatedGroup:
    """A same-signed set of exposed names."""

    key: str
    expected_sign: ExpectedSign
    sign_rationale: str
    members: tuple[Listing, ...]


@dataclass(frozen=True)
class EventOverride:
    """A per-event reassignment of unit statuses."""

    id: str
    event_tags: frozenset[str]
    event_ids: frozenset[str]
    assignments: Mapping[str, Status]
    reason: str

    def matches(self, event_id: str, event_tags: Iterable[str]) -> bool:
        """Report whether this override applies to the given event."""
        tags = {tag.strip().lower() for tag in event_tags if tag.strip()}
        return bool(tags & self.event_tags) or event_id in self.event_ids


@dataclass(frozen=True)
class UnresolvedName:
    """A firm that could not be resolved to a usable series.

    Kept in the config and surfaced in the report rather than deleted:
    a treated name that cannot be fetched is survivorship bias, and silently
    dropping it is how survivorship bias becomes invisible.
    """

    name: str
    proposed_ticker: str
    checked: str
    finding: str


@dataclass(frozen=True)
class ScreeningUniverse:
    """Configuration for the broad cross-section used by the dose-response design."""

    path: Path
    min_history_days: int
    min_avg_daily_volume_gbp: float
    note: str


@dataclass(frozen=True)
class UniverseMeta:
    """The `meta:` block, parsed and typed."""

    base_currency: str
    return_type: str
    min_pre_window_days: int
    require_full_pre_window: bool
    min_avg_daily_volume_gbp: float
    max_donors: int
    alignment: Alignment
    outcome: Outcome
    fx_screen_rates_to_gbp: Mapping[str, float]


@dataclass(frozen=True)
class ClockAlignment:
    """Where one unit's close sits relative to the LSE close."""

    unit_id: str
    clock_class: ClockClass
    offset_minutes: int

    @property
    def needs_lag(self) -> bool:
        """True where the unit's close post-dates the London close."""
        return self.clock_class is ClockClass.LATE


@dataclass(frozen=True)
class EventUniverse:
    """The universe as it stands for one specific event.

    Every unit in the global universe appears exactly once in `statuses` or
    once in `dropped`, never in both and never in neither. That exhaustiveness
    is asserted at construction, which is the point of the type.
    """

    event_id: str
    statuses: Mapping[str, Status]
    dropped: Mapping[str, str]
    applied_overrides: tuple[str, ...]

    def of(self, status: Status) -> tuple[str, ...]:
        """Select unit ids holding the given status, in config order."""
        return tuple(
            unit_id for unit_id, assigned in self.statuses.items() if assigned is status
        )

    @property
    def treated(self) -> tuple[str, ...]:
        """Treated unit ids for this event."""
        return self.of(Status.TREATED)

    @property
    def donors(self) -> tuple[str, ...]:
        """Donor unit ids for this event."""
        return self.of(Status.DONOR)

    @property
    def excluded(self) -> tuple[str, ...]:
        """Excluded unit ids for this event."""
        return self.of(Status.EXCLUDED)

    def table(self) -> pd.DataFrame:
        """Resolution table for the report."""
        rows = [
            {"unit_id": unit_id, "status": str(status), "dropped_reason": ""}
            for unit_id, status in self.statuses.items()
        ]
        rows += [
            {"unit_id": unit_id, "status": "dropped", "dropped_reason": reason}
            for unit_id, reason in self.dropped.items()
        ]
        return pd.DataFrame(rows)


@dataclass(frozen=True)
class Universe:
    """The parsed, validated universe. Construct via :func:`load_universe`."""

    meta: UniverseMeta
    treated_groups: tuple[TreatedGroup, ...]
    donors: tuple[Listing, ...]
    excluded: tuple[Listing, ...]
    market_index: Listing
    overrides: tuple[EventOverride, ...]
    exclusion_windows: tuple[ExclusionWindow, ...]
    unresolved: tuple[UnresolvedName, ...]
    screening_universe: ScreeningUniverse | None
    notes: Mapping[str, str]
    source_path: Path
    survivorship_biased: bool = True
    _by_id: Mapping[str, Listing] = field(default_factory=dict, repr=False)

    # -- lookups ----------------------------------------------------------

    @property
    def sector_keys(self) -> tuple[str, ...]:
        """Vocabulary for the event dictionary's `affected_sectors` column."""
        return tuple(group.key for group in self.treated_groups)

    @property
    def treated(self) -> tuple[Listing, ...]:
        """Every default-treated listing, across all groups."""
        return tuple(
            member for group in self.treated_groups for member in group.members
        )

    @property
    def all_listings(self) -> tuple[Listing, ...]:
        """Every listing, market index included."""
        return (*self.treated, *self.donors, *self.excluded, self.market_index)

    @property
    def unit_ids(self) -> tuple[str, ...]:
        """Every unit id in the universe."""
        return tuple(listing.unit_id for listing in self.all_listings)

    @property
    def source_tickers(self) -> tuple[str, ...]:
        """Distinct symbols to fetch. Aliased units collapse onto one fetch."""
        seen: dict[str, None] = {}
        for listing in self.all_listings:
            seen.setdefault(listing.source_ticker, None)
        return tuple(seen)

    def without_units(self, unit_ids: Iterable[str]) -> Universe:
        """Return a copy with `unit_ids` removed from every membership list.

        `build_panel` refuses to assemble a panel unless a price frame exists
        for every named unit, which is the right default: a unit that silently
        vanished between the universe config and the panel is exactly the kind
        of quiet loss this project keeps finding. But two names here are
        **permanent** absences rather than accidents -- `PRSR.L` and `SIG.L`
        were taken private or delisted and no vintage will ever carry them
        (see `unresolved:` in `config/universe.yaml`).

        So the drop is made here, explicitly, by a caller that has to name the
        units it drops. That keeps `build_panel`'s guard strict while letting
        an estimation run proceed, and leaves the removal visible in the
        calling code rather than buried in a tolerant loader.

        Raises
        ------
        KeyError
            If the market index is named: the market model has no baseline
            without it.
        """
        targets = set(unit_ids)
        if self.market_index.unit_id in targets:
            msg = (
                f"cannot drop the market index {self.market_index.unit_id!r}; "
                "the market model has no baseline without it"
            )
            raise KeyError(msg)

        def keep(listings: tuple[Listing, ...]) -> tuple[Listing, ...]:
            return tuple(item for item in listings if item.unit_id not in targets)

        groups = tuple(
            replace(group, members=keep(group.members)) for group in self.treated_groups
        )
        remaining = {
            listing.unit_id: listing
            for listing in (
                *(member for group in groups for member in group.members),
                *keep(self.donors),
                *keep(self.excluded),
                self.market_index,
            )
        }
        return replace(
            self,
            treated_groups=groups,
            donors=keep(self.donors),
            excluded=keep(self.excluded),
            _by_id=remaining,
        )

    def listing(self, unit_id: str) -> Listing:
        """Look up a listing by unit id."""
        try:
            return self._by_id[unit_id]
        except KeyError:
            msg = f"{unit_id!r} is not in the universe"
            raise KeyError(msg) from None

    def group(self, key: str) -> TreatedGroup:
        """Look up a treated group by its sector key."""
        for candidate in self.treated_groups:
            if candidate.key == key:
                return candidate
        msg = f"unknown sector key {key!r}; known keys are {list(self.sector_keys)}"
        raise KeyError(msg)

    # -- per-event resolution ---------------------------------------------

    def resolve_for_event(
        self,
        event_id: str,
        event_tags: Iterable[str] = (),
        event_date: pd.Timestamp | None = None,
    ) -> EventUniverse:
        """Resolve every unit to exactly one status for one event.

        Order of operations, and it matters:

        1. start from each unit's global default status;
        2. apply every matching override, **failing if two overrides assign
           different statuses to the same unit** -- last-one-wins would make
           the result depend on config file ordering, which is not a research
           decision anyone made;
        3. drop units unavailable on the event date (the Barratt boundary);
        4. drop units inside an exclusion window covering the event date;
        5. assert exhaustiveness: every unit is either assigned or dropped.

        Raises
        ------
        EventResolutionError
            On conflicting overrides, an override naming an unknown unit, or
            any unit left unresolved.
        """
        statuses: dict[str, Status] = {
            listing.unit_id: listing.default_status for listing in self.all_listings
        }

        applied: list[str] = []
        assigned_by: dict[str, tuple[str, Status]] = {}
        for override in self.overrides:
            if not override.matches(event_id, event_tags):
                continue
            applied.append(override.id)
            for unit_id, status in override.assignments.items():
                if unit_id not in statuses:
                    msg = (
                        f"override {override.id!r} assigns {status} to {unit_id!r}, "
                        "which is not in the universe"
                    )
                    raise EventResolutionError(msg)
                previous = assigned_by.get(unit_id)
                if previous is not None and previous[1] is not status:
                    msg = (
                        f"event {event_id!r}: overrides {previous[0]!r} and "
                        f"{override.id!r} both assign {unit_id!r}, as "
                        f"{previous[1]} and {status} respectively. Resolve the "
                        "conflict in config/universe.yaml -- the loader will not "
                        "pick one, because which it picked would depend on file "
                        "ordering rather than on a research decision"
                    )
                    raise EventResolutionError(msg)
                assigned_by[unit_id] = (override.id, status)
                statuses[unit_id] = status

        dropped: dict[str, str] = {}
        if event_date is not None:
            for listing in self.all_listings:
                if not listing.available_on(event_date):
                    bounds = (
                        f"available_from={listing.available_from.date()}"
                        if listing.available_from is not None
                        else f"available_to={listing.available_to.date()}"
                        if listing.available_to is not None
                        else "unbounded"
                    )
                    dropped[listing.unit_id] = f"not listed on this date ({bounds})"
            for window in self.exclusion_windows:
                if not window.covers(event_date):
                    continue
                for unit_id in window.unit_ids:
                    dropped[unit_id] = (
                        f"inside exclusion window "
                        f"{window.start.date()}..{window.end.date()}: {window.reason}"
                    )

        for unit_id in dropped:
            statuses.pop(unit_id, None)

        unresolved = set(self.unit_ids) - set(statuses) - set(dropped)
        if unresolved:
            msg = (
                f"event {event_id!r}: {sorted(unresolved)} resolved to neither a "
                "status nor a drop reason. Every unit must resolve to exactly one"
            )
            raise EventResolutionError(msg)

        return EventUniverse(
            event_id=event_id,
            statuses=statuses,
            dropped=dropped,
            applied_overrides=tuple(applied),
        )

    # -- the notes, enforced ----------------------------------------------

    def clock_alignment(self, unit_id: str) -> ClockAlignment:
        """Classify a unit's close against the LSE close. See `notes.timezone`."""
        listing = self.listing(unit_id)
        london = ExchangeSpec(
            suffix=LSE_SUFFIX, tz=LONDON_TZ, close_local=dt.time(16, 30), currency="GBp"
        )
        offsets = [
            int(
                (
                    listing.exchange.close_utc_on(pd.Timestamp(probe))
                    - london.close_utc_on(pd.Timestamp(probe))
                ).total_seconds()
                // 60
            )
            for probe in _PROBE_DATES
        ]
        offset = max(offsets, key=abs)
        if offset > LATE_MARKET_TOLERANCE_MINUTES:
            clock_class = ClockClass.LATE
        elif offset < -LATE_MARKET_TOLERANCE_MINUTES:
            clock_class = ClockClass.EARLY
        else:
            clock_class = ClockClass.ALIGNED
        return ClockAlignment(
            unit_id=unit_id, clock_class=clock_class, offset_minutes=offset
        )

    def alignment_table(self) -> pd.DataFrame:
        """Clock classification for every unit, for the report."""
        rows = [
            {
                "unit_id": listing.unit_id,
                "source_ticker": listing.source_ticker,
                "status": str(listing.default_status),
                "exchange": listing.exchange.suffix or "US",
                "clock_class": str(self.clock_alignment(listing.unit_id).clock_class),
                "offset_minutes_vs_lse": self.clock_alignment(
                    listing.unit_id
                ).offset_minutes,
            }
            for listing in self.all_listings
        ]
        return pd.DataFrame(rows)

    @property
    def late_units(self) -> tuple[str, ...]:
        """Units whose close post-dates the LSE close and must be lagged."""
        return tuple(
            unit_id
            for unit_id in self.unit_ids
            if self.clock_alignment(unit_id).needs_lag
        )

    @property
    def early_units(self) -> tuple[str, ...]:
        """Units whose close pre-dates the LSE close.

        Lagging does not fix these; correcting them would need a *lead*, which
        is future information. Reported as residual misalignment.
        """
        return tuple(
            unit_id
            for unit_id in self.unit_ids
            if self.clock_alignment(unit_id).clock_class is ClockClass.EARLY
        )

    def signed_portfolio_members(self, sign: ExpectedSign) -> tuple[str, ...]:
        """Collect unit ids of every treated name with the given expected sign."""
        return tuple(
            member.unit_id
            for group in self.treated_groups
            if group.expected_sign is sign
            for member in group.members
        )


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------


def _parse_exchange_calendars(raw: Mapping[str, Any]) -> dict[str, ExchangeSpec]:
    """Build the suffix -> ExchangeSpec map from `meta.exchange_calendars`."""
    specs: dict[str, ExchangeSpec] = {}
    for suffix, entry in raw.items():
        hour_text, minute_text = str(entry["close"]).split(":")
        specs[str(suffix)] = ExchangeSpec(
            suffix=str(suffix),
            tz=str(entry["tz"]),
            close_local=dt.time(int(hour_text), int(minute_text)),
            currency=str(entry["currency"]),
        )
    if "" not in specs:
        msg = (
            "meta.exchange_calendars needs a '' entry giving the default "
            "(suffix-less, i.e. US) exchange convention"
        )
        raise UniverseConfigError(msg)
    return specs


def _exchange_for(
    ticker: str, specs: Mapping[str, ExchangeSpec], *, override: str | None = None
) -> ExchangeSpec:
    """Resolve a ticker's exchange from its suffix, or from an explicit override."""
    if override is not None:
        if override not in specs:
            msg = (
                f"exchange {override!r} for {ticker!r} is not in "
                "meta.exchange_calendars"
            )
            raise UniverseConfigError(msg)
        return specs[override]
    if "." in ticker:
        suffix = "." + ticker.rsplit(".", 1)[1]
        if suffix in specs:
            return specs[suffix]
        msg = (
            f"ticker {ticker!r} has suffix {suffix!r}, which is not in "
            f"meta.exchange_calendars ({sorted(specs)}). Add it rather than "
            "letting the ticker fall back to the US close convention"
        )
        raise UniverseConfigError(msg)
    return specs[""]


def _as_date(value: object) -> pd.Timestamp | None:
    """Parse an optional naive calendar date from the config."""
    if value is None:
        return None
    return pd.Timestamp(str(value)).tz_localize(None).normalize()


def _as_listing(
    entry: Mapping[str, Any] | str,
    *,
    group: str,
    status: Status,
    specs: Mapping[str, ExchangeSpec],
) -> Listing:
    """Normalise a config entry into a :class:`Listing`."""
    record: Mapping[str, Any] = {"unit_id": entry} if isinstance(entry, str) else entry
    raw_id = record.get("unit_id", record.get("ticker"))
    if raw_id is None:
        name = str(record.get("name", "<unnamed>"))
        msg = (
            f"{name!r} in group {group!r} has no unit_id (AWAITING TICKER). "
            "Supply a verified symbol or move the entry to `unresolved:`. The "
            "loader will not guess: several of these names were acquired, "
            "merged or delisted during the sample, and the wrong symbol "
            "silently produces the wrong firm's returns"
        )
        raise UniverseConfigError(msg)

    unit_id = str(raw_id)
    source = str(record.get("source_ticker", unit_id))
    return Listing(
        unit_id=unit_id,
        name=str(record.get("name", unit_id)),
        group=group,
        default_status=status,
        exchange=_exchange_for(
            source,
            specs,
            override=str(record["exchange"]) if "exchange" in record else None,
        ),
        source_ticker=source,
        available_from=_as_date(record.get("available_from")),
        available_to=_as_date(record.get("available_to")),
        verify=bool(record.get("verify", False)),
        note=str(record.get("note", "")).strip(),
    )


def _parse_overrides(raw: Sequence[Mapping[str, Any]]) -> tuple[EventOverride, ...]:
    """Parse the `event_overrides:` block."""
    overrides: list[EventOverride] = []
    for entry in raw:
        match: Mapping[str, Any] = entry.get("match", {})
        assignments = {
            str(unit_id): Status(str(status))
            for unit_id, status in entry.get("set", {}).items()
        }
        if not assignments:
            msg = f"override {entry.get('id')!r} assigns nothing"
            raise UniverseConfigError(msg)
        overrides.append(
            EventOverride(
                id=str(entry.get("id", f"override_{len(overrides)}")),
                event_tags=frozenset(
                    str(tag).strip().lower() for tag in match.get("event_tags", ())
                ),
                event_ids=frozenset(str(eid) for eid in match.get("event_ids", ())),
                assignments=assignments,
                reason=str(entry.get("reason", "")).strip(),
            )
        )
    ids = [override.id for override in overrides]
    duplicates = sorted({name for name in ids if ids.count(name) > 1})
    if duplicates:
        msg = f"duplicate override ids: {duplicates}"
        raise UniverseConfigError(msg)
    return tuple(overrides)


def _parse_exclusion_windows(
    treated_raw: Mapping[str, Any],
) -> tuple[ExclusionWindow, ...]:
    """Collect `exclusion_windows:` from every treated group block."""
    windows: list[ExclusionWindow] = []
    for block in treated_raw.values():
        for entry in block.get("exclusion_windows", ()):
            raw_ids = entry["unit_id"]
            unit_ids = (
                (str(raw_ids),)
                if isinstance(raw_ids, str)
                else tuple(map(str, raw_ids))
            )
            start = _as_date(entry["start"])
            end = _as_date(entry["end"])
            if start is None or end is None or start > end:
                msg = f"exclusion window for {unit_ids} has an invalid date range"
                raise UniverseConfigError(msg)
            windows.append(
                ExclusionWindow(
                    unit_ids=unit_ids,
                    start=start,
                    end=end,
                    reason=str(entry.get("reason", "")).strip(),
                )
            )
    return tuple(windows)


def _check_consistency(universe_listings: Sequence[Listing]) -> None:
    """Reject duplicate unit ids and cross-status collisions."""
    ids = [listing.unit_id for listing in universe_listings]
    duplicates = sorted({name for name in ids if ids.count(name) > 1})
    if duplicates:
        msg = (
            f"unit id(s) {duplicates} appear more than once. A unit holding two "
            "default statuses is exactly the ambiguity the per-event override "
            "schema exists to remove; fix the config rather than relying on "
            "resolution order"
        )
        raise UniverseConfigError(msg)


def load_universe(path: Path | None = None) -> Universe:
    """Parse and validate `config/universe.yaml`.

    Source: hand-curated by the project owner. Donor pool as uploaded
        2026-08-15; treated tickers supplied and verified against yfinance on
        2026-08-15, with failures recorded under ``unresolved:`` rather than
        substituted.
    Licence: project's own.
    Vintage: the file, which is version controlled. Changing the universe is a
        research decision and appears in git history as one.
    Publication lag: none -- a configuration file, not a data feed. The
        point-in-time exposure it does carry is survivorship: the pool is built
        from firms a scraper still serves, which `notes.survivorship` requires
        be stated rather than worked around.

    Raises
    ------
    UniverseConfigError
        On a missing unit id, a duplicate unit id, an unknown exchange suffix,
        a donor pool exceeding `meta.max_donors`, an invalid exclusion window,
        or `alignment: none` with a non-London unit present.
    """
    target = path if path is not None else UNIVERSE_CONFIG
    if not target.exists():
        msg = f"universe config not found at {target}"
        raise FileNotFoundError(msg)

    raw: Mapping[str, Any] = yaml.safe_load(target.read_text(encoding="utf-8"))
    meta_raw: Mapping[str, Any] = raw["meta"]
    specs = _parse_exchange_calendars(meta_raw["exchange_calendars"])

    meta = UniverseMeta(
        base_currency=str(meta_raw["base_currency"]),
        return_type=str(meta_raw["return_type"]),
        min_pre_window_days=int(meta_raw["min_pre_window_days"]),
        require_full_pre_window=bool(meta_raw["require_full_pre_window"]),
        min_avg_daily_volume_gbp=float(meta_raw["min_avg_daily_volume_gbp"]),
        max_donors=int(meta_raw["max_donors"]),
        alignment=Alignment(str(meta_raw["alignment"])),
        outcome=Outcome(str(meta_raw["outcome"])),
        fx_screen_rates_to_gbp={
            str(code): float(rate)
            for code, rate in meta_raw.get("fx_screen_rates_to_gbp", {}).items()
        },
    )

    treated_raw: Mapping[str, Any] = raw.get("treated", {})
    treated_groups = tuple(
        TreatedGroup(
            key=str(key),
            expected_sign=ExpectedSign(str(block["expected_sign"])),
            sign_rationale=str(block.get("sign_rationale", "")).strip(),
            members=tuple(
                _as_listing(entry, group=str(key), status=Status.TREATED, specs=specs)
                for entry in block.get("members", ())
            ),
        )
        for key, block in treated_raw.items()
    )

    donors = tuple(
        _as_listing(entry, group=str(key), status=Status.DONOR, specs=specs)
        for key, block in raw.get("donors", {}).items()
        for entry in block
    )
    excluded = tuple(
        _as_listing(entry, group=str(key), status=Status.EXCLUDED, specs=specs)
        for key, block in raw.get("excluded", {}).items()
        for entry in block
    )
    market_index = _as_listing(
        raw["market_index"],
        group="market_index",
        status=Status.MARKET_INDEX,
        specs=specs,
    )

    listings = (
        *(member for group in treated_groups for member in group.members),
        *donors,
        *excluded,
        market_index,
    )
    _check_consistency(listings)

    if len(donors) > meta.max_donors:
        msg = (
            f"{len(donors)} donors exceeds meta.max_donors={meta.max_donors}. "
            "`notes.overfitting`: a large pool fits the pre-treatment period well "
            "by chance"
        )
        raise UniverseConfigError(msg)

    if meta.alignment is Alignment.NONE:
        non_london = [listing.unit_id for listing in listings if not listing.is_london]
        if non_london:
            msg = (
                f"meta.alignment is 'none' but the universe contains non-London "
                f"listings {non_london}. `notes.timezone` calls unstated "
                "cross-market clock misalignment the single most common silent "
                "error in cross-market event studies"
            )
            raise UniverseConfigError(msg)

    missing_currencies = sorted(
        {listing.exchange.currency for listing in listings}
        - set(meta.fx_screen_rates_to_gbp)
    )
    if missing_currencies:
        msg = (
            f"meta.fx_screen_rates_to_gbp has no rate for {missing_currencies}; "
            "the liquidity screen would silently pass those names"
        )
        raise UniverseConfigError(msg)

    screening_raw = raw.get("screening_universe")
    screening = (
        ScreeningUniverse(
            path=PROJECT_ROOT / str(screening_raw["path"]),
            min_history_days=int(screening_raw["min_history_days"]),
            min_avg_daily_volume_gbp=float(screening_raw["min_avg_daily_volume_gbp"]),
            note=str(screening_raw.get("note", "")).strip(),
        )
        if screening_raw
        else None
    )

    return Universe(
        meta=meta,
        treated_groups=treated_groups,
        donors=donors,
        excluded=excluded,
        market_index=market_index,
        overrides=_parse_overrides(raw.get("event_overrides", ())),
        exclusion_windows=_parse_exclusion_windows(treated_raw),
        unresolved=tuple(
            UnresolvedName(
                name=str(entry["name"]),
                proposed_ticker=str(entry.get("proposed_ticker", "")),
                checked=str(entry.get("checked", "")),
                finding=str(entry.get("finding", "")).strip(),
            )
            for entry in raw.get("unresolved", ())
        ),
        screening_universe=screening,
        notes={
            str(key): str(value).strip() for key, value in raw.get("notes", {}).items()
        },
        source_path=target,
        _by_id={listing.unit_id: listing for listing in listings},
    )
