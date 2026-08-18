"""Schema for firm-level exposure attributes and policy targets.

The exposure score is the project's core contribution and has no off-the-shelf
substitute. It is built from two hand-curated inputs, both validated here:

``data/exposure/firm_attributes.csv``
    Long format, one row per (unit, attribute, vintage). Long rather than wide
    because the attribute set differs by channel -- a landlord has a dwelling
    band profile, a manufacturer has revenue shares -- and a wide table would
    be mostly empty and would make "absent" and "zero" indistinguishable. That
    distinction is load-bearing: an absent attribute means unknown, a zero
    means measured and not exposed, and conflating them attenuates the
    estimate.

``data/exposure/policy_targets.csv``
    One row per event: which band the policy mandates, which product
    categories it touches, whether it tightens or loosens, and its scope.
    Exposure is a property of the firm *and* the event -- a firm with a stock
    profile concentrated in band D is heavily exposed to a mandate at C and
    not at all to a mandate at E.

Point-in-time
-------------
Every attribute row carries ``knowable_from``, the date the value became
public. That is usually the report publication date, **not** the balance-sheet
date it describes, and the gap is routinely four months. `CLAUDE.md` §2.3: the
timestamp at which a feature became knowable, not the timestamp it describes,
determines which prediction it may enter. :func:`filter_knowable` enforces it
and the builder cannot bypass it.

The specific failure this prevents is sharp. A firm's post-announcement
portfolio disclosure -- published *because* the policy changed, often quoting
the very exposure the policy created -- would otherwise flow into that firm's
pre-announcement exposure score, and the regression would recover the market's
reaction to news it was handed after the fact.
"""

from __future__ import annotations

import enum
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Final

import pandas as pd

from policy_event_study.events.schema import PolicyDirection

#: Required columns of `data/exposure/firm_attributes.csv`.
ATTRIBUTE_COLUMNS: Final[tuple[str, ...]] = (
    "unit_id",
    "attribute",
    "value",
    "as_of_date",
    "knowable_from",
    "source_url",
    "vintage",
)

#: Required columns of `data/exposure/policy_targets.csv`.
POLICY_TARGET_COLUMNS: Final[tuple[str, ...]] = (
    "event_id",
    "mandated_min_band",
    "affected_categories",
    "scope",
    "direction",
)

#: Optional columns, used where present.
OPTIONAL_ATTRIBUTE_COLUMNS: Final[tuple[str, ...]] = ("note", "confidence")
OPTIONAL_POLICY_COLUMNS: Final[tuple[str, ...]] = ("mechanism", "note")

LIST_SEPARATOR: Final[str] = ";"


class Scope(enum.StrEnum):
    """Which building stock a policy reaches.

    The vocabulary is the curated one in `data/exposure/policy_targets.csv`.
    It replaced an earlier ``domestic / commercial / both`` triple that no
    curated row ever used: the study narrowed to domestic policy, so
    ``commercial`` became dead, and ``domestic`` turned out to be too coarse
    because MEES binds by *tenure* -- an instrument aimed at the private rented
    sector does not reach a social landlord, and neither reaches new build.
    Loading the curated file against the old triple raised on the first row,
    which is how the drift was found.

    **The stock channels gate on scope; the flow channels do not.** Until
    2026-08-17 no channel read this field, so a listed private-rented landlord
    scored full exposure to a social-rented mandate and vice versa. It is now
    consumed by :func:`residential_stock_magnitude`, which selects the band
    profile of the tenure the instrument names, and by
    :func:`delivered_stock_magnitude`, which applies only to ``NEW_BUILD``.

    ``product_revenue`` and ``domestic_supply`` are deliberately **not** gated.
    A manufacturer sells fabric and heating products into whichever tenure the
    subsidy or mandate stimulates, so its demand channel is reached by any
    domestic scope; gating it would invent a distinction the firm's revenue
    disclosure does not make.
    """

    #: Every domestic tenure: retrofit subsidy, supplier obligations, grants.
    ALL_DOMESTIC = "all_domestic"
    #: Privately rented homes only. The MEES track.
    DOMESTIC_PRS = "domestic_prs"
    #: Social rented homes only. Decent Homes Standard and social MEES.
    SOCIAL_RENTED = "social_rented"
    #: Homes off the gas grid: oil and LPG boiler phase-out.
    OFF_GAS_GRID = "off_gas_grid"
    #: New dwellings. Building regulations and the Future Homes Standard.
    NEW_BUILD = "new_build"


#: One vocabulary for policy direction across the project. Defined in
#: `events.schema` because the event dictionary is where a curator writes it;
#: re-exported here so the exposure inputs cannot drift to a second spelling.
Direction = PolicyDirection


@dataclass(frozen=True)
class FirmAttribute:
    """One curated firm-level input."""

    unit_id: str
    attribute: str
    value: float
    as_of_date: pd.Timestamp
    knowable_from: pd.Timestamp
    source_url: str
    vintage: str
    note: str = ""
    confidence: str = ""

    @property
    def disclosure_lag_days(self) -> int:
        """Days between the period described and the date it became public."""
        return int((self.knowable_from - self.as_of_date).days)


@dataclass(frozen=True)
class PolicyTarget:
    """What one event actually mandates, in terms the score can consume."""

    event_id: str
    mandated_min_band: str
    affected_categories: tuple[str, ...]
    scope: Scope
    direction: Direction
    mechanism: str = ""
    note: str = ""

    @property
    def is_scoreable(self) -> bool:
        """Whether any channel can turn this target into a magnitude.

        False when the row names neither a mandated band nor an affected
        category. Eight such rows exist and they are deliberate: they are the
        record of the `delivered_stock` exposure the design could not measure
        (`reports/decision_log.md`, 2026-08-16), kept rather than deleted so
        the gap is visible. They are skipped at scoring and counted, not
        dropped silently and not scored as zero -- an unmeasurable exposure is
        not a measured zero, and `docs/exposure_construction.md` section 3
        turns on that distinction.

        Scoring them would also crash: a blank band reaches
        :func:`~policy_event_study.exposure.channels.band_index`, which raises
        rather than guessing.
        """
        return bool(self.mandated_min_band or self.affected_categories)


@dataclass(frozen=True)
class ExposureScore:
    """One firm's exposure to one event.

    Attributes
    ----------
    magnitude
        Fraction of the firm's business the policy touches, in [0, 1].
        Unsigned. Retained so an unsigned specification can be run.
    signed
        ``magnitude * channel_sign * event_direction``. The quantity the
        dose-response regression uses before standardisation.
    channel
        Which channel produced the score, or ``"none"`` for an explicit zero.
    inputs_used
        Attribute names that fed the score, for the audit trail.
    """

    unit_id: str
    event_id: str
    magnitude: float
    signed: float
    channel: str
    channel_sign: float
    inputs_used: tuple[str, ...] = ()
    note: str = ""

    @property
    def is_explicit_zero(self) -> bool:
        """True for a measured zero, as opposed to an excluded unknown."""
        return self.magnitude == 0.0 and self.channel == "none"


@dataclass(frozen=True)
class ExposureIssue:
    """One problem found in the curated exposure inputs."""

    row: int
    column: str
    message: str
    fatal: bool = True


@dataclass
class ExposureReport:
    """Outcome of validating the exposure inputs."""

    issues: list[ExposureIssue] = field(default_factory=list)
    n_attributes: int = 0
    n_targets: int = 0

    @property
    def fatal_issues(self) -> list[ExposureIssue]:
        """Issues that reject the file."""
        return [issue for issue in self.issues if issue.fatal]

    @property
    def warnings(self) -> list[ExposureIssue]:
        """Issues carried into the report but not rejecting."""
        return [issue for issue in self.issues if not issue.fatal]

    @property
    def ok(self) -> bool:
        """True when nothing fatal was found."""
        return not self.fatal_issues

    def render(self) -> str:
        """Human-readable summary."""
        lines = [
            f"exposure inputs: {self.n_attributes} attribute row(s), "
            f"{self.n_targets} policy target(s)"
        ]
        for issue in self.fatal_issues:
            lines.append(f"  FATAL  row {issue.row} [{issue.column}]: {issue.message}")
        for issue in self.warnings:
            lines.append(f"  WARN   row {issue.row} [{issue.column}]: {issue.message}")
        return "\n".join(lines)


class ExposureValidationError(ValueError):
    """Raised when the curated exposure inputs fail validation."""

    def __init__(self, report: ExposureReport) -> None:
        self.report = report
        super().__init__(report.render())


def filter_knowable(
    attributes: Iterable[FirmAttribute], announcement_ts_utc: pd.Timestamp
) -> tuple[tuple[FirmAttribute, ...], tuple[FirmAttribute, ...]]:
    """Split attributes into those knowable at the announcement and those not.

    Returns ``(knowable, withheld)``. The second element is returned rather
    than discarded so the builder can report *what* it refused to use -- a
    silent drop looks identical to an absent attribute, and the two have
    different consequences for the score.

    Parameters
    ----------
    attributes
        Curated firm attributes.
    announcement_ts_utc
        Tz-aware UTC announcement timestamp. An attribute is usable when its
        `knowable_from` is strictly earlier than this.
    """
    if announcement_ts_utc.tzinfo is None:
        msg = "announcement timestamp must be timezone-aware"
        raise ValueError(msg)
    cutoff = announcement_ts_utc.tz_convert("UTC").tz_localize(None).normalize()

    knowable: list[FirmAttribute] = []
    withheld: list[FirmAttribute] = []
    for attribute in attributes:
        if attribute.knowable_from < cutoff:
            knowable.append(attribute)
        else:
            withheld.append(attribute)
    return tuple(knowable), tuple(withheld)


def latest_by_attribute(
    attributes: Sequence[FirmAttribute],
) -> dict[tuple[str, str], FirmAttribute]:
    """Keep the most recent knowable vintage of each (unit, attribute).

    A firm restates. Where two vintages of the same attribute are both
    knowable at the announcement, the later one is what the market had, so it
    is the one used -- selecting on `knowable_from` rather than on
    `as_of_date`, since a recently-published older figure is still the freshest
    public information.

    **Ties on `knowable_from` are broken on `as_of_date`, and the tie is the
    normal case rather than the exotic one.** R7 in
    `docs/exposure_construction.md` requires a prior-year comparative to carry
    the *later* report's `knowable_from`, so every attribute curated with a
    comparative produces two rows sharing a publication date and differing only
    in the period they describe. Ranking on `knowable_from` alone left that
    pair unordered, and the winner was then decided by CSV row order: sorting
    the file, or curating the comparative above the current year, silently
    swapped the current-year figure for the prior-year one and moved every
    score downstream of it. Among equally-public vintages the market had both
    and would use the fresher period, so the greater `as_of_date` wins.
    """
    best: dict[tuple[str, str], FirmAttribute] = {}
    for attribute in attributes:
        key = (attribute.unit_id, attribute.attribute)
        current = best.get(key)
        if current is None or (attribute.knowable_from, attribute.as_of_date) > (
            current.knowable_from,
            current.as_of_date,
        ):
            best[key] = attribute
    return best
