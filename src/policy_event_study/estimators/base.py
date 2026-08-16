"""The interface all three estimators share.

One signature, three estimators::

    estimator.estimate(panel, spec, treated_unit) -> EffectEstimate

That shape is not cosmetic. It is what makes the diagnostics in
`policy_event_study.diagnostics` estimator-agnostic and, more importantly,
what makes them *cheap*: an in-space placebo is the same call with a donor
passed as `treated_unit`, and an in-time placebo is the same call with a
shifted `EventSpec`. Because the market-model baseline implements the same
interface, it gets the same permutation inference as the synthetic control --
so the comparison `CLAUDE.md` §4 demands is like-for-like rather than
parametric-t-test versus permutation-p-value.

Window construction
-------------------
Windows are defined in **trading-day counts relative to** ``t0``, not in
calendar dates, so an in-time placebo is a single integer shift and cannot
accidentally land on a non-trading day.

::

    |<---- estimation_length ---->|<-- gap -->|  t0  |<-- post_horizon -->|
                                              ^
                                              announcement resolved here

The `gap` is `CLAUDE.md` §3's embargo, applied to event time. It keeps the
estimation window clear of the pre-announcement drift that leaks, trailing and
speculation produce. Setting it to zero is permitted and is a research
decision the report has to defend, not a default.
"""

from __future__ import annotations

import abc
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import ClassVar, Final

import numpy as np
import pandas as pd

from policy_event_study.data.prices import PanelProvenance, ReturnPanel
from policy_event_study.events.schema import (
    AnticipationRisk,
    EventTiming,
    ExpectedDirection,
)

#: Default estimation window, in trading days. Matches
#: `config/universe.yaml` `meta.min_pre_window_days`.
DEFAULT_ESTIMATION_LENGTH: Final[int] = 250

#: Default embargo between the estimation window and t0, in trading days.
#: Roughly six weeks: long enough to exclude the period over which UK policy
#: announcements are typically trailed in the press.
DEFAULT_GAP: Final[int] = 30

#: Default post-event horizon, in trading days.
DEFAULT_POST_HORIZON: Final[int] = 20


class WindowError(ValueError):
    """Raised when the panel cannot supply the windows a spec asks for."""


@dataclass(frozen=True)
class ResolvedWindows:
    """Concrete trading days for one event, after resolving counts against a panel."""

    t0: pd.Timestamp
    pre_days: pd.DatetimeIndex
    post_days: pd.DatetimeIndex
    gap_days: pd.DatetimeIndex

    @property
    def n_pre(self) -> int:
        """Number of estimation-window trading days."""
        return len(self.pre_days)

    @property
    def n_post(self) -> int:
        """Number of post-event trading days, t0 included."""
        return len(self.post_days)

    @property
    def all_days(self) -> pd.DatetimeIndex:
        """Every day the gap is evaluated on: estimation, embargo, post.

        Contiguous, and the embargo days are deliberately included. They are
        excluded from *fitting* -- that is what makes them an embargo -- but
        the gap must still be computed over them, for two reasons. The
        cumulative outcome would otherwise skip them and misstate the level at
        ``t0``; and the embargo is the only genuine out-of-sample pre-event
        holdout the design has, which is where
        :func:`~policy_event_study.diagnostics.pretrends.pretrend_test` looks
        for the drift that leaks and press trailing produce.
        """
        return pd.DatetimeIndex(
            self.pre_days.append(self.gap_days).append(self.post_days)
        )

    @property
    def baseline_day(self) -> pd.Timestamp:
        """Last trading day before ``t0``; the level every effect is net of.

        This is the last day of the *embargo*, not the last day of the
        estimation window. Measuring from the end of the estimation window
        would fold the embargo period's own drift into the effect -- and the
        embargo exists precisely because that period is suspect.
        """
        if len(self.gap_days):
            return pd.Timestamp(self.gap_days[-1])
        return pd.Timestamp(self.pre_days[-1])


@dataclass(frozen=True)
class EventSpec:
    """One event's estimation problem, independent of which unit is treated.

    `treated_unit` is deliberately *not* a field: an in-space placebo is the
    same spec with a different unit passed to
    :meth:`EventStudyEstimator.estimate`, and keeping the unit out of the spec
    makes that impossible to get wrong.
    """

    event_id: str
    timing: EventTiming
    donors: tuple[str, ...]
    estimation_length: int = DEFAULT_ESTIMATION_LENGTH
    gap: int = DEFAULT_GAP
    post_horizon: int = DEFAULT_POST_HORIZON
    anticipation_risk: AnticipationRisk = AnticipationRisk.MEDIUM
    expected_direction: ExpectedDirection = ExpectedDirection.AMBIGUOUS
    #: Set by the in-time placebo machinery. Never true for a real event.
    is_placebo_date: bool = False
    #: Free-text label carried into the report, e.g. "in-time placebo -60".
    label: str = ""

    @property
    def t0(self) -> pd.Timestamp:
        """The trading day the event window opens on."""
        return self.timing.t0

    def resolve(self, trading_days: pd.DatetimeIndex) -> ResolvedWindows:
        """Turn the count-based window definition into concrete trading days.

        Raises
        ------
        WindowError
            If `t0` is not in the calendar, or history before it is too short
            for `estimation_length + gap`, or fewer than `post_horizon + 1`
            days remain after it. Truncating silently would produce an
            estimate whose effective sample differs from the one reported.
        """
        days = pd.DatetimeIndex(trading_days)
        positions = days.get_indexer(pd.DatetimeIndex([self.t0]))
        if positions[0] == -1:
            msg = (
                f"t0 {self.t0.date()} for event {self.event_id!r} is not a trading "
                "day in this panel. The panel calendar is the intersection of "
                "every listing's calendar, so a UK holiday-adjacent date can be "
                "absent even though the LSE traded"
            )
            raise WindowError(msg)
        index = int(positions[0])

        pre_end = index - self.gap
        pre_start = pre_end - self.estimation_length
        if pre_start < 0:
            msg = (
                f"event {self.event_id!r} needs {self.estimation_length + self.gap} "
                f"trading days before t0 but only {index} are available"
            )
            raise WindowError(msg)
        if index + self.post_horizon >= len(days):
            msg = (
                f"event {self.event_id!r} needs {self.post_horizon + 1} trading days "
                f"from t0 but only {len(days) - index} remain"
            )
            raise WindowError(msg)

        return ResolvedWindows(
            t0=self.t0,
            pre_days=days[pre_start:pre_end],
            post_days=days[index : index + self.post_horizon + 1],
            gap_days=days[pre_end:index],
        )

    def shifted(
        self, offset: int, trading_days: pd.DatetimeIndex, label: str
    ) -> EventSpec:
        """Copy this spec with `t0` moved `offset` trading days.

        Negative offsets produce in-time placebos. The returned spec carries
        `is_placebo_date=True`, which the reporting layer checks so a placebo
        can never be printed as a real estimate.
        """
        days = pd.DatetimeIndex(trading_days)
        index = int(days.get_indexer(pd.DatetimeIndex([self.t0]))[0])
        if index == -1:
            msg = f"t0 {self.t0.date()} is not in the panel calendar"
            raise WindowError(msg)
        target = index + offset
        if not 0 <= target < len(days):
            msg = f"shift of {offset} trading days moves t0 outside the panel"
            raise WindowError(msg)
        moved = pd.Timestamp(days[target])
        return EventSpec(
            event_id=self.event_id,
            timing=EventTiming(
                announcement_ts_utc=self.timing.announcement_ts_utc,
                time_known=self.timing.time_known,
                straddling_day=None,
                first_clean_day=moved,
                t0=moved,
                convention=self.timing.convention,
            ),
            donors=self.donors,
            estimation_length=self.estimation_length,
            gap=self.gap,
            post_horizon=self.post_horizon,
            anticipation_risk=self.anticipation_risk,
            expected_direction=self.expected_direction,
            is_placebo_date=True,
            label=label,
        )


@dataclass(frozen=True)
class EffectEstimate:
    """One estimator's answer for one unit and one event.

    A bare `tau` is never reported. `CLAUDE.md` and the project brief both
    require a placebo distribution alongside every point estimate, and
    `policy_event_study.reporting` refuses to format one of these without it.

    Attributes
    ----------
    tau
        Cumulative abnormal return over the post window, measured from the
        last pre-event day so that a non-zero pre-event gap does not leak into
        the effect. Same definition for all three estimators, which is what
        makes them comparable.
    gap
        Counterfactual gap over estimation and post days. For the market model
        this is the abnormal-return path; for SC and SDiD it is the treated
        outcome minus its synthetic counterpart.
    pre_rmspe
        Root mean squared prediction error over the estimation window. The
        denominator of Abadie's test statistic, and the quantity Phase B2's
        kill criterion is stated in.
    rmspe_ratio
        `post_rmspe / pre_rmspe`. Scale-free, so it is comparable across units
        with very different volatility -- which is exactly what an in-space
        placebo test needs.
    weights
        Donor weights. Empty for the market model, which has no donor pool;
        that emptiness is meaningful and is reported as such.
    """

    estimator: str
    event_id: str
    treated_unit: str
    tau: float
    gap: pd.Series
    pre_rmspe: float
    post_rmspe: float
    n_pre: int
    n_post: int
    weights: pd.Series
    provenance: PanelProvenance
    is_placebo: bool = False
    label: str = ""
    extras: Mapping[str, float] = field(default_factory=dict)

    @property
    def rmspe_ratio(self) -> float:
        """Abadie's scale-free test statistic. `inf` when pre-fit is exact."""
        if self.pre_rmspe == 0.0:
            return float("inf")
        return self.post_rmspe / self.pre_rmspe

    @property
    def effective_weight_count(self) -> float:
        """Inverse Herfindahl of the donor weights.

        The number of donors the synthetic control *effectively* rests on. A
        value near 1 means a single donor is carrying the counterfactual,
        which leave-one-out will confirm is fragile. Zero when there are no
        weights.
        """
        if self.weights.empty:
            return 0.0
        squared = float((self.weights.to_numpy() ** 2).sum())
        return 1.0 / squared if squared > 0 else 0.0

    def gap_path(self, windows: ResolvedWindows) -> pd.Series:
        """Gap re-centred on the last pre-event day, for plotting."""
        return self.gap - float(self.gap.loc[windows.baseline_day])


class EventStudyEstimator(abc.ABC):
    """Common interface. Three implementations; one call signature.

    Implementations must be deterministic: given the same panel, spec and
    unit, the same numbers. Any stochastic component takes an explicit `seed`
    (`CLAUDE.md` §7).
    """

    #: Short name used in report tables and in `EffectEstimate.estimator`.
    name: ClassVar[str]

    @abc.abstractmethod
    def estimate(
        self, panel: ReturnPanel, spec: EventSpec, treated_unit: str
    ) -> EffectEstimate:
        """Estimate the effect on `treated_unit` for the event in `spec`."""

    def _check_unit(
        self, panel: ReturnPanel, spec: EventSpec, treated_unit: str
    ) -> tuple[str, ...]:
        """Validate the unit/donor split and return the usable donors.

        The treated unit is removed from its own donor pool if present. That
        should never happen -- `Universe` rejects the overlap at load time --
        but an in-space placebo constructs donor pools programmatically, and a
        unit reconstructing itself drives the estimated effect to exactly zero
        without any error being raised.
        """
        if treated_unit not in panel.returns.columns:
            msg = f"{treated_unit!r} is not in the panel"
            raise KeyError(msg)
        windows = spec.resolve(panel.trading_days)
        complete = set(
            panel.complete_units(
                list(spec.donors), windows.all_days[0], windows.all_days[-1]
            )
        )
        donors = tuple(
            donor
            for donor in spec.donors
            if donor != treated_unit and donor in complete
        )
        if not donors:
            msg = (
                f"no usable donors for {treated_unit!r} in event {spec.event_id!r}: "
                f"the spec listed {len(spec.donors)}, none of which has complete "
                "returns over this event's windows. Units are dropped for "
                "incompleteness rather than interpolated -- a filled return is a "
                "day that never traded, and a synthetic control will happily fit it"
            )
            raise WindowError(msg)
        return donors


def cumulative_abnormal_return(
    gap: pd.Series, windows: ResolvedWindows, *, horizon: int | None = None
) -> float:
    """Cumulative abnormal return over the post window, net of the pre-event level.

    Shared by all three estimators so `tau` means the same thing in every row
    of every table. The gap on the eve of the event is subtracted because a
    synthetic control with imperfect pre-fit sits at a non-zero gap there, and
    counting that as effect would be reporting fit failure as treatment.

    Parameters
    ----------
    gap
        Gap path over estimation, embargo and post days.
    windows
        Resolved windows for this event.
    horizon
        Number of post-event days to accumulate over, t0 counted as day 0.
        Defaults to the full post window.
    """
    baseline = float(gap.loc[windows.baseline_day])
    end = windows.post_days[-1] if horizon is None else windows.post_days[horizon]
    return float(gap.loc[end] - baseline)


def rmspe(values: np.ndarray) -> float:
    """Root mean squared value. Named for what it measures in this project."""
    if values.size == 0:
        return float("nan")
    return float(np.sqrt(np.mean(np.square(values))))


def align_outcome(
    panel: ReturnPanel,
    windows: ResolvedWindows,
    units: Sequence[str],
) -> pd.DataFrame:
    """Outcome matrix over estimation + post days for the given units.

    The outcome is built on the *window* rather than on the whole panel, so it
    starts at zero on the first estimation day. Building it on the full sample
    and slicing afterwards would leave the level dependent on history outside
    the window, which changes the SC fit for no defensible reason.
    """
    windowed = panel.window(windows.all_days[0], windows.all_days[-1])
    return windowed.outcome(list(units)).reindex(windows.all_days)
