"""Leave-one-donor-out sensitivity of the estimated effect.

`config/universe.yaml` `notes.overfitting`: a large donor pool will fit the
pre-treatment period well by chance, so the pool is kept substantively
justified and leave-one-out sensitivity is reported. This module is that
report.

What it catches
---------------
A synthetic control with a good pre-fit can still rest almost entirely on one
donor. When it does, the "effect" is a statement about one other firm's
post-event path, and the donor pool's apparent breadth is decoration. Dropping
each contributing donor in turn and refitting shows how much of the estimate
survives.

Two failure modes, distinguished
--------------------------------
``concentration``
    Detected before refitting, from the weights alone:
    :attr:`~policy_event_study.estimators.base.EffectEstimate.effective_weight_count`
    is the inverse Herfindahl of the weight vector -- the number of donors the
    counterfactual effectively rests on. Near 1 is a warning regardless of
    what leave-one-out then shows.

``instability``
    Detected by refitting: the estimate moves a lot, or changes sign, when one
    donor is removed. Note that concentration and instability are not the same
    thing. A pool of near-collinear sector peers can be *unconcentrated* and
    still unstable, because the SC problem has a continuum of near-optimal
    weight vectors and dropping a donor jumps between them -- which is the
    non-uniqueness discussed in
    :mod:`policy_event_study.estimators.synthetic_control`.

The market model has no donors, so leave-one-out does not apply to it. That
asymmetry is not a gap in the diagnostics: it is the substantive difference
between the methods, and the report says so rather than leaving a blank cell.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

import numpy as np
import pandas as pd

from policy_event_study.data.prices import ReturnPanel
from policy_event_study.estimators.base import (
    EventSpec,
    EventStudyEstimator,
    WindowError,
)

#: Donors below this weight are not worth refitting without -- their removal
#: changes the counterfactual by less than solver tolerance.
DEFAULT_WEIGHT_FLOOR: Final[float] = 1e-3


@dataclass(frozen=True)
class LeaveOneOutResult:
    """Effect estimates with each contributing donor removed in turn."""

    estimator: str
    event_id: str
    treated_unit: str
    full_tau: float
    full_pre_rmspe: float
    effective_donor_count: float
    max_weight: float
    taus: pd.Series
    pre_rmspes: pd.Series
    failures: dict[str, str] = field(default_factory=dict)

    @property
    def n_refits(self) -> int:
        """Number of donors actually dropped and refitted."""
        return len(self.taus)

    @property
    def sign_stable(self) -> bool:
        """True when no single donor's removal flips the sign of the effect."""
        if not self.n_refits or self.full_tau == 0:
            return False
        return bool(
            np.all(np.sign(self.taus.to_numpy(dtype=float)) == np.sign(self.full_tau))
        )

    @property
    def max_absolute_shift(self) -> float:
        """Largest change in tau from dropping a single donor."""
        if not self.n_refits:
            return float("nan")
        return float(np.max(np.abs(self.taus.to_numpy(dtype=float) - self.full_tau)))

    @property
    def relative_shift(self) -> float:
        """`max_absolute_shift` as a fraction of the full estimate.

        Above 1.0 means a single donor's removal moves the estimate by more
        than the estimate itself, which makes the point estimate a statement
        about that donor rather than about the treated unit.
        """
        if self.full_tau == 0:
            return float("inf")
        return self.max_absolute_shift / abs(self.full_tau)

    @property
    def most_influential(self) -> str:
        """Ticker whose removal moves the estimate most."""
        if not self.n_refits:
            return ""
        shifts = (self.taus - self.full_tau).abs()
        return str(shifts.idxmax())

    @property
    def concentrated(self) -> bool:
        """True when the counterfactual effectively rests on fewer than 3 donors."""
        return bool(0 < self.effective_donor_count < 3.0)

    def summary(self) -> pd.Series:
        """One-line summary for a report table."""
        return pd.Series(
            {
                "estimator": self.estimator,
                "event_id": self.event_id,
                "treated_unit": self.treated_unit,
                "tau": self.full_tau,
                "tau_min_loo": float(self.taus.min())
                if self.n_refits
                else float("nan"),
                "tau_max_loo": float(self.taus.max())
                if self.n_refits
                else float("nan"),
                "relative_shift": self.relative_shift,
                "sign_stable": self.sign_stable,
                "effective_donors": self.effective_donor_count,
                "max_weight": self.max_weight,
                "most_influential": self.most_influential,
                "n_refits": self.n_refits,
            }
        )

    def table(self) -> pd.DataFrame:
        """Per-donor detail: effect and pre-fit with that donor removed."""
        return pd.DataFrame(
            {
                "tau_without": self.taus,
                "shift": self.taus - self.full_tau,
                "pre_rmspe_without": self.pre_rmspes,
            }
        ).sort_values("shift", key=lambda column: column.abs(), ascending=False)


def leave_one_donor_out(
    estimator: EventStudyEstimator,
    panel: ReturnPanel,
    spec: EventSpec,
    treated_unit: str,
    *,
    weight_floor: float = DEFAULT_WEIGHT_FLOOR,
    all_donors: bool = False,
) -> LeaveOneOutResult:
    """Refit the estimator with each contributing donor removed.

    Parameters
    ----------
    weight_floor
        Only donors with weight above this are dropped and refitted, since
        removing a zero-weight donor cannot change the fit. Ignored when
        `all_donors` is True.
    all_donors
        Refit without every donor in the pool, including zero-weight ones.
        More expensive and occasionally informative: a zero-weight donor whose
        removal *does* move the estimate is a sign the weight vector is one of
        several near-optimal solutions rather than a unique one.
    """
    full = estimator.estimate(panel, spec, treated_unit)

    if full.weights.empty:
        return LeaveOneOutResult(
            estimator=estimator.name,
            event_id=spec.event_id,
            treated_unit=treated_unit,
            full_tau=full.tau,
            full_pre_rmspe=full.pre_rmspe,
            effective_donor_count=0.0,
            max_weight=float("nan"),
            taus=pd.Series(dtype=float),
            pre_rmspes=pd.Series(dtype=float),
            failures={
                "_": (
                    "estimator has no donor weights; leave-one-out does not apply. "
                    "This is the substantive difference from SC, not a missing test"
                )
            },
        )

    contributors = (
        list(spec.donors)
        if all_donors
        else [str(name) for name in full.weights.index[full.weights > weight_floor]]
    )

    taus: dict[str, float] = {}
    pre_rmspes: dict[str, float] = {}
    failures: dict[str, str] = {}

    for donor in contributors:
        reduced = EventSpec(
            event_id=spec.event_id,
            timing=spec.timing,
            donors=tuple(other for other in spec.donors if other != donor),
            estimation_length=spec.estimation_length,
            gap=spec.gap,
            post_horizon=spec.post_horizon,
            anticipation_risk=spec.anticipation_risk,
            expected_direction=spec.expected_direction,
            is_placebo_date=spec.is_placebo_date,
            label=f"leave-one-out: without {donor}",
        )
        try:
            refit = estimator.estimate(panel, reduced, treated_unit)
        except (WindowError, KeyError, RuntimeError, ValueError) as exc:
            failures[donor] = f"{type(exc).__name__}: {exc}"
            continue
        taus[donor] = refit.tau
        pre_rmspes[donor] = refit.pre_rmspe

    return LeaveOneOutResult(
        estimator=estimator.name,
        event_id=spec.event_id,
        treated_unit=treated_unit,
        full_tau=full.tau,
        full_pre_rmspe=full.pre_rmspe,
        effective_donor_count=full.effective_weight_count,
        max_weight=float(full.weights.max()),
        taus=pd.Series(taus, dtype=float, name="tau_without"),
        pre_rmspes=pd.Series(pre_rmspes, dtype=float, name="pre_rmspe_without"),
        failures=failures,
    )
