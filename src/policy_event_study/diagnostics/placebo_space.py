"""In-space placebos: run the estimator on every donor as if it were treated.

This is the inference backbone of the project. With one treated firm and one
event there is no cross-section to take a standard error over, so significance
comes from a permutation argument instead: if the announcement did nothing,
the treated unit's post-event gap should look like any donor's post-event gap,
because none of them was treated. Re-running the estimator with each donor
standing in for the treated unit traces out that reference distribution
directly.

Why the same machinery runs on the market model
-----------------------------------------------
Because all three estimators share one interface, the market-model baseline
gets permutation inference too. That matters for the project's stated
question: comparing an SC permutation p-value against a market-model
*parametric t-test* would confound the estimator with the inference method,
and any difference could be attributed to either. Running both through the
same permutation makes the comparison about the estimator alone.

The statistic
-------------
Two are reported, and they answer different questions.

``tau``
    The cumulative abnormal return itself. Directly interpretable, and biased
    toward donors that happen to be volatile.

``rmspe_ratio``
    Abadie's post-to-pre RMSPE ratio. Scale-free, so a donor the pool fits
    badly cannot manufacture significance simply by being noisy. This is the
    statistic Phase B3's kill criterion is stated in.

The exclusion rule
------------------
Abadie's standard practice is to drop placebo units whose *pre-treatment* fit
is much worse than the treated unit's, on the grounds that a synthetic control
that never fit cannot produce a meaningful post-event gap. That rule is also a
researcher degree of freedom, so :meth:`PlaceboDistribution.p_value` reports
the p-value across a ladder of cutoffs rather than at one chosen after seeing
the answer, and :func:`p_value_table` prints the whole ladder.

The floor on what is provable
-----------------------------
With ``J`` usable placebos the smallest attainable p-value is ``1 / (J + 1)``.
With 23 donors that floor is 0.042 -- so a 5% threshold is reachable but a 1%
threshold is *arithmetically impossible*, whatever the data show. This is a
property of the design, is knowable before any estimation, and is reported by
:attr:`PlaceboDistribution.min_attainable_p`. See
:mod:`policy_event_study.diagnostics.power`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
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
from policy_event_study.events.schema import ExpectedDirection

#: Pre-fit exclusion cutoffs, as multiples of the treated unit's pre-RMSPE.
#: `inf` keeps every placebo. Reported as a ladder so no single cutoff can be
#: chosen after seeing which one gives the smallest p-value.
DEFAULT_CUTOFFS: Final[tuple[float, ...]] = (float("inf"), 20.0, 5.0, 2.0)


@dataclass(frozen=True)
class PlaceboDistribution:
    """Reference distribution built by treating each donor as if treated.

    Attributes
    ----------
    placebo_taus, placebo_ratios, placebo_pre_rmspe
        Indexed by donor ticker.
    failures
        Donors the estimator could not be run on, with the reason. Reported
        rather than dropped silently: a pool that fails on half its members is
        not a pool of the size the p-value's denominator claims.
    """

    estimator: str
    event_id: str
    treated_unit: str
    treated_tau: float
    treated_ratio: float
    treated_pre_rmspe: float
    placebo_taus: pd.Series
    placebo_ratios: pd.Series
    placebo_pre_rmspe: pd.Series
    expected_direction: ExpectedDirection = ExpectedDirection.AMBIGUOUS
    failures: Mapping[str, str] = field(default_factory=dict)

    @property
    def n_placebos(self) -> int:
        """Usable placebo units."""
        return len(self.placebo_taus)

    @property
    def min_attainable_p(self) -> float:
        """Smallest p-value this design can produce: `1 / (J + 1)`.

        A property of the donor pool's size, not of the data. If this exceeds
        the threshold being tested against, the test cannot reject at that
        level no matter how large the true effect is.
        """
        return 1.0 / (self.n_placebos + 1.0)

    def filtered(self, max_pre_rmspe_multiple: float) -> PlaceboDistribution:
        """Drop placebos whose pre-fit is worse than the treated unit's by a multiple."""
        if not np.isfinite(max_pre_rmspe_multiple):
            return self
        threshold = self.treated_pre_rmspe * max_pre_rmspe_multiple
        keep = self.placebo_pre_rmspe.index[self.placebo_pre_rmspe <= threshold]
        return PlaceboDistribution(
            estimator=self.estimator,
            event_id=self.event_id,
            treated_unit=self.treated_unit,
            treated_tau=self.treated_tau,
            treated_ratio=self.treated_ratio,
            treated_pre_rmspe=self.treated_pre_rmspe,
            placebo_taus=self.placebo_taus.loc[keep],
            placebo_ratios=self.placebo_ratios.loc[keep],
            placebo_pre_rmspe=self.placebo_pre_rmspe.loc[keep],
            expected_direction=self.expected_direction,
            failures=self.failures,
        )

    def p_value(
        self, statistic: str = "ratio", *, one_sided: bool | None = None
    ) -> float:
        """Fisher randomisation p-value.

        ``p = (1 + #{placebo at least as extreme}) / (1 + J)``

        The treated unit is counted in its own reference set, which is the
        standard convention and is conservative -- it is also why the p-value
        can never be zero.

        Parameters
        ----------
        statistic
            ``"ratio"`` for Abadie's RMSPE ratio, ``"tau"`` for the raw
            cumulative abnormal return.
        one_sided
            Defaults to one-sided when the event dictionary recorded a
            directional expectation and two-sided when it recorded
            ``ambiguous``. Because ``expected_direction`` is curated *before*
            the returns are seen, the one-sided reading is legitimate here in
            a way it would not be if the direction were chosen afterwards.
        """
        if statistic == "ratio":
            # The ratio is non-negative and large-is-extreme by construction,
            # so a sign convention does not apply to it.
            placebos = self.placebo_ratios.to_numpy(dtype=float)
            extreme = int((placebos >= self.treated_ratio).sum())
            return (1.0 + extreme) / (1.0 + len(placebos))

        if statistic != "tau":
            msg = f"unknown statistic {statistic!r}; use 'ratio' or 'tau'"
            raise ValueError(msg)

        placebos = self.placebo_taus.to_numpy(dtype=float)
        directional = (
            one_sided
            if one_sided is not None
            else self.expected_direction is not ExpectedDirection.AMBIGUOUS
        )
        if not directional:
            extreme = int((np.abs(placebos) >= abs(self.treated_tau)).sum())
        elif self.expected_direction is ExpectedDirection.NEGATIVE:
            extreme = int((placebos <= self.treated_tau).sum())
        else:
            extreme = int((placebos >= self.treated_tau).sum())
        return (1.0 + extreme) / (1.0 + len(placebos))

    def rank(self, statistic: str = "ratio") -> int:
        """Rank of the treated unit among all units, 1 being the most extreme."""
        if statistic == "ratio":
            values = np.append(
                self.placebo_ratios.to_numpy(dtype=float), self.treated_ratio
            )
            return int((values >= self.treated_ratio).sum())
        values = np.append(
            np.abs(self.placebo_taus.to_numpy(dtype=float)), abs(self.treated_tau)
        )
        return int((values >= abs(self.treated_tau)).sum())

    def summary(self) -> pd.Series:
        """One-line summary for a report table."""
        return pd.Series(
            {
                "estimator": self.estimator,
                "event_id": self.event_id,
                "treated_unit": self.treated_unit,
                "tau": self.treated_tau,
                "rmspe_ratio": self.treated_ratio,
                "p_ratio": self.p_value("ratio"),
                "p_tau": self.p_value("tau"),
                "rank": self.rank("ratio"),
                "n_placebos": self.n_placebos,
                "min_attainable_p": self.min_attainable_p,
                "n_failed": len(self.failures),
            }
        )


def in_space_placebos(
    estimator: EventStudyEstimator,
    panel: ReturnPanel,
    spec: EventSpec,
    treated_unit: str,
    *,
    candidates: Sequence[str] | None = None,
) -> PlaceboDistribution:
    """Re-run `estimator` with each donor standing in as the treated unit.

    Each placebo run uses the remaining donors as its pool. The real treated
    unit is **never** put into a placebo's donor pool: it is treated, so
    including it would inject the very effect being tested into the reference
    distribution and bias the p-value toward one.

    Parameters
    ----------
    candidates
        Donors to use as placebos. Defaults to every donor in the spec. Pass a
        subset to restrict to, say, same-sector donors.

    Returns
    -------
    PlaceboDistribution
        Carrying both statistics, the failures, and the design's floor on
        attainable p-values.
    """
    treated_estimate = estimator.estimate(panel, spec, treated_unit)
    pool = list(candidates) if candidates is not None else list(spec.donors)

    taus: dict[str, float] = {}
    ratios: dict[str, float] = {}
    pre_rmspes: dict[str, float] = {}
    failures: dict[str, str] = {}

    for donor in pool:
        if donor == treated_unit or donor not in panel.returns.columns:
            continue
        placebo_spec = EventSpec(
            event_id=spec.event_id,
            timing=spec.timing,
            # The treated unit is excluded; every other donor is available.
            donors=tuple(other for other in pool if other != donor),
            estimation_length=spec.estimation_length,
            gap=spec.gap,
            post_horizon=spec.post_horizon,
            anticipation_risk=spec.anticipation_risk,
            expected_direction=spec.expected_direction,
            is_placebo_date=spec.is_placebo_date,
            label=f"in-space placebo: {donor}",
        )
        try:
            placebo = estimator.estimate(panel, placebo_spec, donor)
        except (WindowError, KeyError, RuntimeError, ValueError) as exc:
            failures[donor] = f"{type(exc).__name__}: {exc}"
            continue
        taus[donor] = placebo.tau
        ratios[donor] = placebo.rmspe_ratio
        pre_rmspes[donor] = placebo.pre_rmspe

    return PlaceboDistribution(
        estimator=estimator.name,
        event_id=spec.event_id,
        treated_unit=treated_unit,
        treated_tau=treated_estimate.tau,
        treated_ratio=treated_estimate.rmspe_ratio,
        treated_pre_rmspe=treated_estimate.pre_rmspe,
        placebo_taus=pd.Series(taus, dtype=float, name="tau"),
        placebo_ratios=pd.Series(ratios, dtype=float, name="rmspe_ratio"),
        placebo_pre_rmspe=pd.Series(pre_rmspes, dtype=float, name="pre_rmspe"),
        expected_direction=spec.expected_direction,
        failures=failures,
    )


def p_value_table(
    distribution: PlaceboDistribution,
    cutoffs: Sequence[float] = DEFAULT_CUTOFFS,
) -> pd.DataFrame:
    """P-values across the ladder of pre-fit exclusion cutoffs.

    Reporting the whole ladder rather than one cutoff is the point: the
    exclusion rule is a researcher degree of freedom, and a result that only
    reaches significance at one rung of the ladder should be visible as such.
    """
    rows: list[dict[str, object]] = []
    for cutoff in cutoffs:
        filtered = distribution.filtered(cutoff)
        rows.append(
            {
                "pre_rmspe_cutoff": "none"
                if not np.isfinite(cutoff)
                else f"{cutoff:g}x",
                "n_placebos": filtered.n_placebos,
                "p_ratio": filtered.p_value("ratio")
                if filtered.n_placebos
                else float("nan"),
                "p_tau": filtered.p_value("tau")
                if filtered.n_placebos
                else float("nan"),
                "min_attainable_p": filtered.min_attainable_p,
            }
        )
    return pd.DataFrame(rows)
