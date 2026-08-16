"""Pre-treatment fit quality and pre-trend tests.

A synthetic control's entire claim is that it builds a better counterfactual
than a factor model. If the synthetic unit does not track the treated unit
before the event, the post-event "effect" is fit failure wearing a causal
label. These checks come before any estimate is read, and Phase B2's kill
criterion is stated in terms of them.

Two distinct tests, testing different things
--------------------------------------------
:func:`pre_fit_report`
    *Can* the donor pool span the treated unit at all? Measured by
    pre-treatment RMSPE, normalised by the treated unit's own variation so it
    is comparable across units, and benchmarked against the market model on
    identical windows -- which is the comparison `CLAUDE.md` §4 requires and
    the form Phase B2's kill criterion takes.

:func:`pretrend_test`
    *Was the treated unit already drifting* relative to its counterfactual
    before the event? A good RMSPE with a systematic slope is worse than a
    mediocre RMSPE with none: it means the gap was already moving, and
    whatever it was moving toward gets attributed to the announcement.

The holdout the design already provides
---------------------------------------
`EventSpec.gap` embargoes trading days between the estimation window and
``t0``. Those days are never seen by any estimator, which makes them a
genuine out-of-sample pre-event holdout -- and the natural place to look for
the pre-announcement drift that leaks and press trailing produce.
:func:`pretrend_test` reports the drift there separately from the in-sample
slope, because an in-sample slope is partly the fit's own residual structure
whereas the holdout drift is not.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

import numpy as np
from scipy import stats

from policy_event_study.data.prices import ReturnPanel
from policy_event_study.estimators.base import EffectEstimate, EventSpec


class PreFitVerdict(enum.StrEnum):
    """Outcome of the Phase B2 comparison against the market model."""

    SPANS = "spans"
    MARGINAL = "marginal"
    FAILS = "fails"


@dataclass(frozen=True)
class PreFitReport:
    """Pre-treatment fit for one unit under one estimator.

    Attributes
    ----------
    pre_rmspe
        Root mean squared prediction error over the estimation window, on the
        cumulative-return outcome.
    normalised_rmspe
        `pre_rmspe` divided by the standard deviation of the treated unit's
        own pre-window outcome. Scale-free, so a housebuilder and a utility
        can appear in the same column. Below roughly 0.3 the synthetic unit
        is tracking; above 1.0 it is doing no better than the treated unit's
        own mean.
    baseline_pre_rmspe
        The market model's pre-window RMSPE on identical windows and identical
        data -- the comparator Phase B2's kill criterion is stated against.
    ratio_to_baseline
        `pre_rmspe / baseline_pre_rmspe`. Below 1 means the donor pool beats
        the factor model at reconstructing the treated unit, which is the
        minimum condition for SC to be worth using.
    """

    estimator: str
    event_id: str
    treated_unit: str
    pre_rmspe: float
    normalised_rmspe: float
    baseline_pre_rmspe: float
    ratio_to_baseline: float
    n_pre: int
    n_donors_above_1pct: float
    max_weight: float
    effective_donor_count: float

    @property
    def verdict(self) -> PreFitVerdict:
        """Phase B2 classification.

        `FAILS` is a *reportable finding*, not an error: "for UK
        housebuilders, the available donor pool cannot construct a synthetic
        control with acceptable pre-treatment fit, because the sector's
        exposure to UK rates and planning policy is not spanned by any
        untreated combination" is a substantive statement about when SC
        applies, and it answers the project's research question directly.
        """
        if self.ratio_to_baseline <= 0.9:
            return PreFitVerdict.SPANS
        if self.ratio_to_baseline <= 1.1:
            return PreFitVerdict.MARGINAL
        return PreFitVerdict.FAILS


@dataclass(frozen=True)
class PretrendTest:
    """Pre-event drift, in sample and in the embargoed holdout."""

    estimator: str
    event_id: str
    treated_unit: str
    slope_per_day: float
    slope_se_hac: float
    slope_t: float
    slope_p: float
    holdout_drift: float
    holdout_z: float
    n_holdout: int

    @property
    def violated(self) -> bool:
        """True where either test flags drift at the 5% level.

        Deliberately reads *both* tests. An estimate that survives the
        placebo distribution but fails this is not a clean result, and the
        report says so next to the point estimate rather than in a footnote.
        """
        return bool(self.slope_p < 0.05 or abs(self.holdout_z) > 1.96)


def pre_fit_report(
    estimate: EffectEstimate,
    baseline: EffectEstimate,
    panel: ReturnPanel,
    spec: EventSpec,
) -> PreFitReport:
    """Assess whether the donor pool can reconstruct the treated unit.

    Parameters
    ----------
    estimate
        The SC or SDiD estimate under test.
    baseline
        The market-model estimate for the *same* unit, event and windows.
        `CLAUDE.md` §4: the comparison is made on identical data, identical
        splits and identical evaluation windows, so this is passed in rather
        than recomputed with whatever defaults happen to be in scope.
    """
    if baseline.treated_unit != estimate.treated_unit:
        msg = (
            f"baseline is for {baseline.treated_unit!r} but the estimate is for "
            f"{estimate.treated_unit!r}; the comparison must be like-for-like"
        )
        raise ValueError(msg)

    windows = spec.resolve(panel.trading_days)
    treated_outcome = (
        panel.window(windows.all_days[0], windows.all_days[-1])
        .outcome([estimate.treated_unit])
        .reindex(windows.pre_days)
        .iloc[:, 0]
    )
    own_sd = float(treated_outcome.std(ddof=1))

    ratio = (
        estimate.pre_rmspe / baseline.pre_rmspe
        if baseline.pre_rmspe > 0
        else float("inf")
    )
    return PreFitReport(
        estimator=estimate.estimator,
        event_id=estimate.event_id,
        treated_unit=estimate.treated_unit,
        pre_rmspe=estimate.pre_rmspe,
        normalised_rmspe=estimate.pre_rmspe / own_sd if own_sd > 0 else float("inf"),
        baseline_pre_rmspe=baseline.pre_rmspe,
        ratio_to_baseline=ratio,
        n_pre=estimate.n_pre,
        n_donors_above_1pct=float(
            estimate.extras.get("n_donors_above_1pct", float("nan"))
        ),
        max_weight=float(estimate.extras.get("max_weight", float("nan"))),
        effective_donor_count=estimate.effective_weight_count,
    )


def _newey_west_se(residuals: np.ndarray, regressor: np.ndarray, lags: int) -> float:
    """HAC standard error for the slope of a simple regression.

    Daily gaps on a cumulative outcome are strongly autocorrelated by
    construction -- a cumulative sum is a random walk -- so an OLS standard
    error here would be badly understated. `CLAUDE.md` §3 makes the same point
    about half-hourly demand data: the row count is not the observation count.
    """
    centred = regressor - regressor.mean()
    denominator = float(centred @ centred)
    if denominator <= 0:
        return float("nan")
    scores = centred * residuals
    variance = float(scores @ scores)
    for lag in range(1, lags + 1):
        weight = 1.0 - lag / (lags + 1.0)
        covariance = float(scores[lag:] @ scores[:-lag])
        variance += 2.0 * weight * covariance
    if variance <= 0:
        return float("nan")
    return float(np.sqrt(variance) / denominator)


def pretrend_test(
    estimate: EffectEstimate, spec: EventSpec, panel: ReturnPanel, *, hac_lags: int = 10
) -> PretrendTest:
    """Test for differential drift before the event.

    The in-sample slope regresses the estimation-window gap on a time index
    with Newey-West standard errors. The holdout drift measures how far the
    gap moved across the embargoed days between the estimation window and
    ``t0`` -- days no estimator saw -- standardised by the gap's own
    estimation-window daily volatility.
    """
    windows = spec.resolve(panel.trading_days)
    pre_gap = estimate.gap.reindex(windows.pre_days).to_numpy(dtype=float)
    time_index = np.arange(len(pre_gap), dtype=float)

    design = np.column_stack([np.ones_like(time_index), time_index])
    coefficients, *_ = np.linalg.lstsq(design, pre_gap, rcond=None)
    slope = float(coefficients[1])
    residuals = pre_gap - design @ coefficients
    slope_se = _newey_west_se(residuals, time_index, hac_lags)
    slope_t = slope / slope_se if slope_se and np.isfinite(slope_se) else float("nan")
    slope_p = (
        float(2.0 * stats.norm.sf(abs(slope_t)))
        if np.isfinite(slope_t)
        else float("nan")
    )

    daily_gap_sd = float(np.std(np.diff(pre_gap), ddof=1)) if len(pre_gap) > 2 else 0.0
    holdout = estimate.gap.reindex(windows.gap_days).to_numpy(dtype=float)
    if len(holdout) and len(pre_gap):
        drift = float(holdout[-1] - pre_gap[-1])
        scale = daily_gap_sd * np.sqrt(len(holdout))
        holdout_z = drift / scale if scale > 0 else float("nan")
    else:
        drift, holdout_z = 0.0, float("nan")

    return PretrendTest(
        estimator=estimate.estimator,
        event_id=estimate.event_id,
        treated_unit=estimate.treated_unit,
        slope_per_day=slope,
        slope_se_hac=slope_se,
        slope_t=slope_t,
        slope_p=slope_p,
        holdout_drift=drift,
        holdout_z=holdout_z,
        n_holdout=len(holdout),
    )
