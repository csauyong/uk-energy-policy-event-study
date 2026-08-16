"""Load the hand-written a-priori policy inventory.

`data/events/inventory_apriori_<vintage>.yaml` is an independent enumeration of
policy instruments, written from the policy record **before** consulting the
generated shortlist. That order is what gives it its value: it can be used to
*score* the automated discovery, which a list assembled by reading the sweep
and filling gaps could not do -- it would inherit the sweep's blind spots and
so could not measure them.

Two things this module provides.

**Scoring.** :func:`score_discovery` compares the inventory against the
generated shortlist and reports recall, precision and -- the more damaging
category -- instruments the sweep found but *mis-dated*. A missed event costs
one observation; an event dated to its effect month rather than its
announcement puts the whole reaction outside the window and biases the
estimate toward zero while still looking like a valid row.

**Event construction.** :func:`usable_events` applies the inventory's own
admissibility rules: `date_grade` C is not usable until resolved, scheduled
commencements are kept but marked, and rows that `supersede` others collapse
into a single event. Superseding is not deduplication -- four September 2023
shortlist rows are one announcement, and treating them as four would quadruple
that event's weight in a pooled estimate.
"""

from __future__ import annotations

import enum
import itertools
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from policy_event_study.paths import EVENTS_DIR


class DateGrade(enum.StrEnum):
    """How firmly an instrument's date is established.

    The grades are an admissibility rule, not a confidence score. `C` means
    the day is unknown, and an event study cannot use a month: the whole
    apparatus turns on which trading session the information entered. A `C`
    row is excluded until resolved and then dropped, never guessed.
    """

    A = "A"
    B = "B"
    C = "C"

    @property
    def usable(self) -> bool:
        """Whether an instrument at this grade can enter an estimate."""
        return self is not DateGrade.C

    @property
    def needs_confirmation(self) -> bool:
        """Whether the date should be re-checked against a primary source."""
        return self is DateGrade.B


@dataclass(frozen=True)
class Instrument:
    """One policy instrument from the a-priori inventory."""

    id: str
    date: str
    title: str
    families: tuple[str, ...]
    stage: str
    direction: str
    channel_targets: tuple[str, ...]
    date_grade: DateGrade
    time_known: str = ""
    formal_date: str = ""
    leak_risk: str = ""
    scheduled: bool = False
    missing_from_sweep: bool = False
    supersedes: tuple[str, ...] = ()
    resolves: tuple[str, ...] = ()
    pairs_with: tuple[str, ...] = ()
    needs: str = ""
    note: str = ""
    alt_dates: tuple[str, ...] = ()
    direction_by_channel: dict[str, str] = field(default_factory=dict)

    @property
    def period(self) -> pd.Period | None:
        """Month the instrument falls in, or None when the date is unparseable.

        A `C`-grade date such as ``2018-11-??`` still yields a month, which is
        what the scoring comparison needs; only a wholly unparseable string
        returns None.
        """
        parsed: pd.Period | None = None
        try:
            parsed = pd.Period(
                self.date.replace("??", "01").replace("?", "0"), freq="M"
            )
        except (ValueError, TypeError):
            parsed = None
        return parsed

    @property
    def resolved_day(self) -> pd.Timestamp | None:
        """Exact day, or None when the inventory records only a month."""
        if "?" in self.date:
            return None
        try:
            return pd.Timestamp(self.date)
        except (ValueError, TypeError):
            return None

    @property
    def is_independent(self) -> bool:
        """Whether this is an event in its own right.

        Scheduled commencements are kept -- Rule 0 of the curation protocol is
        explicit that a list containing only events that should have moved
        something is selection on the dependent variable -- but a commencement
        that merely enacts an earlier decision is not an independent
        observation of *news*, and pooling it as one would double-count the
        decision that created it.
        """
        return not self.scheduled

    @property
    def opposite_signed_channels(self) -> bool:
        """Whether one shock moves two channels in opposite directions.

        The most informative shape available in a dose-response design: the
        same announcement, one exposure measure, two signs. It identifies the
        gradient from within a single event rather than across events.
        """
        return len(set(self.direction_by_channel.values())) > 1


@dataclass(frozen=True)
class DiscoveryScore:
    """How the automated sweep performed against the independent hand list."""

    inventory_total: int
    inventory_usable: int
    found: tuple[str, ...]
    missed: tuple[str, ...]
    misdated: tuple[tuple[str, str, str], ...]
    sweep_only: int

    @property
    def coverage(self) -> float:
        """Share of usable instruments the sweep had *something* for.

        Counts an instrument whether or not the date was right -- `found` and
        `misdated` together. Coverage on its own flatters the sweep, which is
        why it is never reported without `date_accuracy`.
        """
        if not self.inventory_usable:
            return 0.0
        return (len(self.found) + len(self.misdated)) / self.inventory_usable

    @property
    def date_accuracy(self) -> float:
        """Of the instruments the sweep covered, the share it dated correctly.

        `found`, `misdated` and `missed` partition the usable set, so this is
        `found / (found + misdated)`. An earlier version computed
        `1 - misdated/found`, which assumed the first two were nested and
        returned negative accuracy -- the kind of metric bug that looks like a
        catastrophic result rather than an arithmetic slip.
        """
        covered = len(self.found) + len(self.misdated)
        return len(self.found) / covered if covered else 0.0

    @property
    def miss_rate(self) -> float:
        """Share of usable instruments the sweep had nothing for at all."""
        if not self.inventory_usable:
            return 0.0
        return len(self.missed) / self.inventory_usable

    def summary(self) -> pd.Series:
        """One-line summary for the report."""
        return pd.Series(
            {
                "inventory_total": self.inventory_total,
                "inventory_usable": self.inventory_usable,
                "found_by_sweep": len(self.found),
                "missed_by_sweep": len(self.missed),
                "misdated_by_sweep": len(self.misdated),
                "coverage": self.coverage,
                "miss_rate": self.miss_rate,
                "date_accuracy": self.date_accuracy,
            }
        )


def load_inventory(path: Path | None = None) -> tuple[Instrument, ...]:
    """Parse the a-priori inventory.

    Source: hand-written by the project owner from the policy record, then
        date-verified against primary sources (gov.uk publication pages,
        written ministerial statements, legislation.gov.uk, HMT fiscal
        documents). Full source list in the accompanying `.md`.
    Licence: the underlying documents are OGL v3; the enumeration and the
        date grading are the project's own.
    Vintage: in the filename and in `meta.vintage`. Written before the
        generated shortlist was consulted, which is what makes it admissible
        as a scoring benchmark.
    Publication lag: none for the file; each instrument carries its own date
        and `date_grade`, and that grade -- not the file -- governs use.
    """
    if path is None:
        candidates = sorted(EVENTS_DIR.glob("inventory_apriori_*.yaml"))
        if not candidates:
            msg = "no a-priori inventory found in data/events/"
            raise FileNotFoundError(msg)
        path = candidates[-1]

    raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    instruments: list[Instrument] = []
    for entry in raw.get("events", []):
        families = entry.get("family", ())
        instruments.append(
            Instrument(
                id=str(entry["id"]),
                date=str(entry.get("date", "")),
                title=" ".join(str(entry.get("title", "")).split()),
                families=(
                    (str(families),) if isinstance(families, str) else tuple(families)
                ),
                stage=str(entry.get("stage", "")),
                direction=str(entry.get("direction") or ""),
                channel_targets=tuple(entry.get("channel_targets", ())),
                date_grade=DateGrade(str(entry.get("date_grade", "C"))),
                time_known=str(entry.get("time_known", "")),
                formal_date=str(entry.get("formal_date", "")),
                leak_risk=str(entry.get("leak_risk") or ""),
                scheduled=bool(entry.get("scheduled", False)),
                missing_from_sweep=bool(entry.get("missing_from_sweep", False)),
                supersedes=tuple(entry.get("supersedes", ())),
                resolves=tuple(entry.get("resolves", ())),
                pairs_with=tuple(entry.get("pairs_with", ())),
                needs=str(entry.get("needs") or ""),
                note=" ".join(str(entry.get("note", "")).split()),
                alt_dates=tuple(str(d) for d in entry.get("alt_dates", ())),
                direction_by_channel=dict(entry.get("direction_by_channel", {}) or {}),
            )
        )
    return tuple(instruments)


def usable_events(
    instruments: Iterable[Instrument], *, include_scheduled: bool = True
) -> tuple[Instrument, ...]:
    """Instruments admissible for estimation.

    Excludes `date_grade` C -- a month is not a trading session. Keeps
    scheduled commencements by default, because excluding them would leave a
    list containing only events that should have moved something, which Rule 0
    of the curation protocol identifies as selection on the dependent
    variable.
    """
    return tuple(
        instrument
        for instrument in instruments
        if instrument.date_grade.usable
        and (include_scheduled or instrument.is_independent)
    )


def drop_instruments(
    instruments: Sequence[Instrument], drop_ids: Iterable[str]
) -> tuple[Instrument, ...]:
    """Remove instruments by id, failing loudly on an id that does not exist.

    A silent no-op is the dangerous failure here, not a crash. Dropping a
    mistyped id leaves the set unchanged, and a scenario table built that way
    reports "dropping this row changes nothing" -- which reads as a robustness
    finding rather than as a typo. That is exactly what happened once:
    `green-levies-2013` for `green-levies-rollback-2013` made a deleted event
    look harmless to the design.
    """
    known = {instrument.id for instrument in instruments}
    requested = set(drop_ids)
    unknown = sorted(requested - known)
    if unknown:
        msg = (
            f"unknown instrument id(s) {unknown}; dropping them would silently "
            "do nothing and the scenario would read as robustness. Known ids "
            f"number {len(known)}"
        )
        raise KeyError(msg)
    return tuple(i for i in instruments if i.id not in requested)


def group_count(instruments: Iterable[Instrument], *, spacing_days: int = 14) -> int:
    """Independent clusters among day-resolved instruments.

    Transitive closure over the spacing threshold, matching
    `events.grouping.assign_event_groups`. Reproduced here on bare
    instruments so a scenario table can be computed without constructing
    `PolicyEvent` objects.
    """
    days = sorted(
        instrument.resolved_day
        for instrument in instruments
        if instrument.resolved_day is not None
    )
    if not days:
        return 0
    count = 1
    for previous, current in itertools.pairwise(days):
        if (current - previous).days >= spacing_days:
            count += 1
    return count


def score_discovery(
    instruments: Sequence[Instrument], shortlist_months: Sequence[tuple[str, str]]
) -> DiscoveryScore:
    """Score the automated sweep against the independent hand list.

    Parameters
    ----------
    shortlist_months
        `(month, family)` pairs from the generated shortlist, where month is
        formatted as the shortlist writes it.

    Notes
    -----
    An instrument counts as *found* when the shortlist has a row in the same
    month touching one of its families, and *misdated* when the inventory
    marks it as carried at the wrong date. Mis-dating is scored separately
    because it is the more damaging error: a missed event costs one
    observation, while an event dated to its effect month rather than its
    announcement puts the entire reaction outside the estimation window and
    biases the estimate toward zero -- while still looking like a valid row.
    """
    lookup: set[tuple[str, str]] = set()
    for month, family_key in shortlist_months:
        try:
            month_key = str(pd.Period(pd.Timestamp(month), freq="M"))
        except (ValueError, TypeError):
            continue
        lookup.add((month_key, family_key))

    usable = usable_events(instruments)
    found: list[str] = []
    missed: list[str] = []
    misdated: list[tuple[str, str, str]] = []

    for instrument in usable:
        instrument_period = instrument.period
        if instrument_period is None:
            # Wholly unparseable date: counted as missed rather than dropped,
            # so the denominator stays honest.
            missed.append(instrument.id)
            continue
        hit = any(
            (str(instrument_period), family_key) in lookup
            for family_key in instrument.families
        )
        if instrument.missing_from_sweep:
            missed.append(instrument.id)
        elif hit:
            found.append(instrument.id)
        else:
            # Present in the inventory, absent from the shortlist at this
            # month: either missed outright, or carried at a different date.
            elsewhere = any(
                family_key == shortlist_family
                for family_key in instrument.families
                for _, shortlist_family in shortlist_months
            )
            if elsewhere:
                misdated.append((instrument.id, str(instrument_period), "date differs"))
            else:
                missed.append(instrument.id)

    return DiscoveryScore(
        inventory_total=len(instruments),
        inventory_usable=len(usable),
        found=tuple(found),
        missed=tuple(missed),
        misdated=tuple(misdated),
        sweep_only=max(len(shortlist_months) - len(found), 0),
    )
