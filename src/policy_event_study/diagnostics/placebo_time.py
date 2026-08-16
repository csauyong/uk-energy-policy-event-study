"""In-time placebos: fake event dates in the pre-period.

The in-space placebo asks "would a different *unit* have shown this?". The
in-time placebo asks the other question: "would a different *date* have shown
this?" -- and it is the one that catches a treated unit whose gap wanders
regardless of any announcement. A firm whose synthetic control routinely
drifts 4% over twenty days does not provide evidence for a policy effect by
drifting 4% over the twenty days after an announcement.

Buffering
---------
Every fake event's post-window must end strictly before the real event's
estimation window would begin to see announcement-related information. Two
guards enforce that:

* the fake post window ends at least `buffer` trading days before the real
  ``t0``, so no placebo window overlaps the real event's run-up;
* each fake date keeps a full `estimation_length + gap` of history behind it,
  so placebos are estimated on the same amount of data as the real event and
  a shorter window cannot masquerade as a quieter one.

Offsets that violate either guard are dropped and reported, not silently
truncated -- a placebo distribution built from windows of varying length is
not a reference distribution for a fixed-length statistic.

What this cannot do
-------------------
In-time placebos test whether the *date* is special given the unit. They
cannot detect a slow-moving confounder that affects the treated unit
throughout the sample, and they are weak when the pre-period contains its own
policy news -- which, for UK energy policy between 2020 and 2025, it usually
does. Read them alongside the in-space placebos rather than instead of them.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from policy_event_study.data.prices import ReturnPanel
from policy_event_study.estimators.base import (
    EventSpec,
    EventStudyEstimator,
    WindowError,
)


@dataclass(frozen=True)
class InTimePlaceboResult:
    """Distribution of effects at fake pre-period event dates."""

    estimator: str
    event_id: str
    treated_unit: str
    treated_tau: float
    treated_ratio: float
    placebo_taus: pd.Series
    placebo_ratios: pd.Series
    offsets_dropped: Mapping[int, str] = field(default_factory=dict)

    @property
    def n_placebos(self) -> int:
        """Usable fake dates."""
        return len(self.placebo_taus)

    @property
    def min_attainable_p(self) -> float:
        """Floor on the p-value: `1 / (K + 1)` for K fake dates."""
        return 1.0 / (self.n_placebos + 1.0)

    def p_value(self, statistic: str = "tau") -> float:
        """Fisher randomisation p-value against the fake-date distribution."""
        if statistic == "ratio":
            values = self.placebo_ratios.to_numpy(dtype=float)
            extreme = int((values >= self.treated_ratio).sum())
        elif statistic == "tau":
            values = self.placebo_taus.to_numpy(dtype=float)
            extreme = int((np.abs(values) >= abs(self.treated_tau)).sum())
        else:
            msg = f"unknown statistic {statistic!r}; use 'tau' or 'ratio'"
            raise ValueError(msg)
        return (1.0 + extreme) / (1.0 + len(values))

    def summary(self) -> pd.Series:
        """One-line summary for a report table."""
        return pd.Series(
            {
                "estimator": self.estimator,
                "event_id": self.event_id,
                "treated_unit": self.treated_unit,
                "tau": self.treated_tau,
                "p_tau_in_time": self.p_value("tau"),
                "p_ratio_in_time": self.p_value("ratio"),
                "n_fake_dates": self.n_placebos,
                "placebo_tau_sd": float(self.placebo_taus.std(ddof=1))
                if self.n_placebos > 1
                else float("nan"),
                "n_dropped": len(self.offsets_dropped),
            }
        )


def feasible_offsets(
    spec: EventSpec,
    trading_days: pd.DatetimeIndex,
    *,
    n_offsets: int = 12,
    buffer: int = 10,
    step: int | None = None,
) -> list[int]:
    """Trading-day offsets that satisfy both buffering guards.

    Parameters
    ----------
    n_offsets
        How many fake dates to aim for. Fewer are returned when history runs
        out, which is itself worth knowing: it bounds the smallest p-value the
        in-time test can produce.
    buffer
        Trading days between the end of a fake post-window and the real `t0`.
    step
        Spacing between fake dates. Defaults to `post_horizon + 1`, so
        adjacent placebo windows do not overlap each other. Overlapping
        windows would share data and the resulting "distribution" would count
        the same information several times.
    """
    days = pd.DatetimeIndex(trading_days)
    positions = days.get_indexer(pd.DatetimeIndex([spec.t0]))
    if positions[0] == -1:
        msg = f"t0 {spec.t0.date()} is not in the panel calendar"
        raise WindowError(msg)
    origin = int(positions[0])

    spacing = step if step is not None else spec.post_horizon + 1
    earliest = spec.estimation_length + spec.gap
    latest_index = origin - buffer - spec.post_horizon - 1

    offsets: list[int] = []
    index = latest_index
    while len(offsets) < n_offsets and index >= earliest:
        offsets.append(index - origin)
        index -= spacing
    return offsets


def in_time_placebos(
    estimator: EventStudyEstimator,
    panel: ReturnPanel,
    spec: EventSpec,
    treated_unit: str,
    *,
    n_offsets: int = 12,
    buffer: int = 10,
    step: int | None = None,
) -> InTimePlaceboResult:
    """Re-run the estimator at fake pre-period event dates.

    The donor pool, estimation length, gap and post horizon are held identical
    to the real event; only ``t0`` moves. Holding everything else fixed is
    what makes the resulting distribution a reference for the real statistic.
    """
    treated_estimate = estimator.estimate(panel, spec, treated_unit)
    offsets = feasible_offsets(
        spec, panel.trading_days, n_offsets=n_offsets, buffer=buffer, step=step
    )

    taus: dict[str, float] = {}
    ratios: dict[str, float] = {}
    dropped: dict[int, str] = {}

    for offset in offsets:
        try:
            fake_spec = spec.shifted(
                offset, panel.trading_days, label=f"in-time placebo {offset:+d}"
            )
            placebo = estimator.estimate(panel, fake_spec, treated_unit)
        except (WindowError, KeyError, RuntimeError, ValueError) as exc:
            dropped[offset] = f"{type(exc).__name__}: {exc}"
            continue
        key = f"{offset:+d}"
        taus[key] = placebo.tau
        ratios[key] = placebo.rmspe_ratio

    return InTimePlaceboResult(
        estimator=estimator.name,
        event_id=spec.event_id,
        treated_unit=treated_unit,
        treated_tau=treated_estimate.tau,
        treated_ratio=treated_estimate.rmspe_ratio,
        placebo_taus=pd.Series(taus, dtype=float, name="tau"),
        placebo_ratios=pd.Series(ratios, dtype=float, name="rmspe_ratio"),
        offsets_dropped=dropped,
    )


def combined_placebo_table(
    in_space_p: float,
    in_time_p: float,
    *,
    labels: Sequence[str] = ("in-space", "in-time"),
) -> pd.DataFrame:
    """Put the two placebo p-values side by side.

    They are deliberately *not* combined into a single number. The two tests
    condition on different things -- unit given date, date given unit -- and
    are not independent, so multiplying them or taking a Fisher combination
    would understate the true p-value by an unknown amount. Showing both and
    letting the reader see that one passes and the other does not is more
    informative than a composite that hides which.
    """
    return pd.DataFrame({"test": list(labels), "p_value": [in_space_p, in_time_p]})
