r"""Synthetic difference-in-differences, after Arkhangelsky et al. (2021).

Arkhangelsky, Athey, Hirshberg, Imbens and Wager, *Synthetic
Difference-in-Differences*, American Economic Review 111(12), 2021.

What it adds over the other two
-------------------------------
SDiD sits between the market model and Abadie's synthetic control, and it is
in the study because the two things it relaxes are exactly the two things most
likely to break here.

*Against SC*, it adds an **intercept** to the unit-weight problem and a ridge
penalty. SC insists the synthetic unit match the treated unit's level; SDiD
only asks it to match the treated unit's *path*, absorbing any constant
difference into a DiD-style fixed effect. Phase B2's kill criterion
anticipates SC failing to span UK housebuilders from any untreated
combination -- SDiD is the estimator that can still say something when it
does.

*Against DiD*, it adds **time weights**, so the pre-period comparison is not
a flat average over the whole estimation window but a weighted one chosen to
predict the post-period. Pre-periods that look nothing like the post-period
get near-zero weight instead of contaminating the baseline.

Algorithm 1 of the paper, implemented directly
----------------------------------------------
1. Regularisation constant

   .. math::
      \zeta = (N_{tr} T_{post})^{1/4}\hat\sigma, \quad
      \hat\sigma^2 = \frac{1}{N_{co}(T_{pre}-1)}
        \sum_{i \in co}\sum_{t=1}^{T_{pre}-1}(\Delta_{it} - \bar\Delta)^2

   with :math:`\Delta_{it} = Y_{i,t+1} - Y_{it}`. Because the outcome here is
   a cumulative return, its first difference is a daily return, so
   :math:`\hat\sigma` is the cross-donor daily return volatility -- a
   quantity with a clear meaning rather than an opaque tuning constant.

2. Unit weights: minimise
   :math:`\sum_{t\le T_{pre}}(\omega_0 + \sum_{co}\omega_i Y_{it} - \bar Y_{tr,t})^2
   + \zeta^2 T_{pre}\lVert\omega\rVert^2` over the simplex, :math:`\omega_0` free.

3. Time weights: minimise
   :math:`\sum_{i \in co}(\lambda_0 + \sum_{t\le T_{pre}}\lambda_t Y_{it}
   - \bar Y_{i,post})^2` over the simplex, :math:`\lambda_0` free, unpenalised.

4. :math:`\hat\tau` from the :math:`\omega\lambda`-weighted two-way regression.

Step 4 is computed in closed form, which for a block treatment assignment is
algebraically identical to running the weighted two-way regression and far
faster -- and the placebo machinery runs it once per donor. The equivalence is
asserted against an explicit weighted least-squares fit in
`tests/test_estimators.py`, so the shortcut is verified rather than trusted.

Estimand
--------
The paper's estimand averages the gap over post-treatment periods. Applied to
a *cumulative-return* outcome that gives an average CAR over the window, which
is not the same quantity as the other two estimators' CAR at the horizon. Both
are available:

``Estimand.HORIZON`` (default)
    A single post period at ``t0 + post_horizon``. Time weights are then fit
    to predict that one period, and :math:`\hat\tau` is the cumulative
    abnormal return at the horizon -- directly comparable with the market
    model and SC.
``Estimand.AVERAGE``
    The paper's native estimand over the full post window.

Note the one genuine incomparability, and it is not a defect: SDiD's baseline
is the :math:`\lambda`-weighted pre-period, whereas SC and the market model
are re-baselined on the last pre-event day. That difference *is* the method.
`extras["tau_baselined_last_pre"]` reports the common-baseline number
alongside, so a reader can see how much the choice moved the answer.
"""

from __future__ import annotations

import enum
from typing import ClassVar

import numpy as np
import pandas as pd

from policy_event_study.data.prices import ReturnPanel
from policy_event_study.estimators.base import (
    EffectEstimate,
    EventSpec,
    EventStudyEstimator,
    align_outcome,
    cumulative_abnormal_return,
    rmspe,
)


class Estimand(enum.StrEnum):
    """Which post-treatment quantity SDiD targets. See the module docstring."""

    HORIZON = "horizon"
    AVERAGE = "average"


def regularisation_constant(
    donor_pre: np.ndarray, n_treated: int, n_post: int
) -> float:
    r"""Compute :math:`\zeta` from equation (2.3) of the paper.

    Parameters
    ----------
    donor_pre
        Donor pre-period outcomes, shape `(T_pre, J)`.
    n_treated, n_post
        :math:`N_{tr}` and :math:`T_{post}`.
    """
    if donor_pre.shape[0] < 2:
        return 0.0
    differences = np.diff(donor_pre, axis=0)
    sigma = float(np.std(differences, ddof=1))
    return float((n_treated * n_post) ** 0.25 * sigma)


def _solve_weights(
    target: np.ndarray,
    predictors: np.ndarray,
    *,
    penalty: float,
    n_periods: int,
) -> tuple[np.ndarray, float]:
    """Simplex-constrained least squares with a free intercept and ridge.

    Shared by the unit-weight and time-weight steps, which differ only in what
    is being predicted and in whether `penalty` is non-zero.
    """
    import cvxpy

    n_terms = predictors.shape[1]
    weights = cvxpy.Variable(n_terms, nonneg=True)
    intercept = cvxpy.Variable()
    objective = cvxpy.Minimize(
        cvxpy.sum_squares(target - (predictors @ weights + intercept))
        + (penalty**2) * n_periods * cvxpy.sum_squares(weights)
    )
    problem = cvxpy.Problem(objective, [cvxpy.sum(weights) == 1])

    for solver in ("CLARABEL", "ECOS", "SCS"):
        if solver not in cvxpy.installed_solvers():
            continue
        try:
            problem.solve(solver=solver)
        except cvxpy.error.SolverError:  # pragma: no cover - solver-specific
            continue
        if weights.value is not None:
            fitted = np.clip(np.asarray(weights.value, dtype=float), 0.0, None)
            total = fitted.sum()
            if total > 0:
                fitted = fitted / total
            return fitted, float(intercept.value)

    msg = "no cvxpy solver converged for the SDiD weight problem"
    raise RuntimeError(msg)


def twfe_tau(
    outcome: np.ndarray,
    unit_weights: np.ndarray,
    time_weights: np.ndarray,
    n_pre: int,
) -> float:
    """Weighted two-way fixed-effects fit of step 4, by explicit least squares.

    Slow and transparent: builds the unit and time dummies and solves the
    weighted normal equations. Used in tests to verify the closed form, and
    available when a non-block assignment makes the closed form inapplicable.

    Parameters
    ----------
    outcome
        Shape `(T, N)`, treated unit in the **last** column.
    unit_weights
        Donor weights, shape `(N-1,)`. The treated unit takes weight 1.
    time_weights
        Pre-period weights, shape `(n_pre,)`. Post-periods take weight
        `1 / T_post`.
    n_pre
        Number of pre-treatment periods.
    """
    n_periods, n_units = outcome.shape
    n_post = n_periods - n_pre
    omega = np.concatenate([unit_weights, [1.0]])
    lam = np.concatenate([time_weights, np.full(n_post, 1.0 / n_post)])

    rows: list[np.ndarray] = []
    targets: list[float] = []
    sample_weights: list[float] = []
    for time_index in range(n_periods):
        for unit_index in range(n_units):
            unit_dummy = np.zeros(n_units)
            unit_dummy[unit_index] = 1.0
            time_dummy = np.zeros(n_periods)
            time_dummy[time_index] = 1.0
            treated_flag = (
                1.0 if (unit_index == n_units - 1 and time_index >= n_pre) else 0.0
            )
            rows.append(np.concatenate([[treated_flag], unit_dummy, time_dummy]))
            targets.append(float(outcome[time_index, unit_index]))
            sample_weights.append(float(omega[unit_index] * lam[time_index]))

    design = np.asarray(rows)
    response = np.asarray(targets)
    root_weights = np.sqrt(np.asarray(sample_weights))
    solution, *_ = np.linalg.lstsq(
        design * root_weights[:, None], response * root_weights, rcond=None
    )
    return float(solution[0])


class SyntheticDiDEstimator(EventStudyEstimator):
    r"""Synthetic DiD over the common estimator interface.

    Parameters
    ----------
    estimand
        See :class:`Estimand`. Defaults to `HORIZON` for comparability with
        the market model and SC.
    zeta_scale
        Multiplier on the paper's :math:`\zeta`. One reproduces Algorithm 1;
        zero removes the ridge and makes the unit weights an
        intercept-shifted synthetic control, which is a useful ablation and is
        reported as such rather than as SDiD.
    """

    name: ClassVar[str] = "synthetic_did"

    def __init__(
        self, *, estimand: Estimand = Estimand.HORIZON, zeta_scale: float = 1.0
    ) -> None:
        self.estimand = estimand
        self.zeta_scale = zeta_scale

    def estimate(
        self, panel: ReturnPanel, spec: EventSpec, treated_unit: str
    ) -> EffectEstimate:
        """Run Algorithm 1 with weights fit on pre-treatment data only."""
        donors = self._check_unit(panel, spec, treated_unit)
        windows = spec.resolve(panel.trading_days)
        outcome = align_outcome(panel, windows, [treated_unit, *donors])

        post_days = (
            windows.post_days[-1:]
            if self.estimand is Estimand.HORIZON
            else windows.post_days
        )
        pre_treated = outcome.loc[windows.pre_days, treated_unit].to_numpy(dtype=float)
        pre_donors = outcome.loc[windows.pre_days, list(donors)].to_numpy(dtype=float)
        post_donors = outcome.loc[post_days, list(donors)].to_numpy(dtype=float)
        post_treated = outcome.loc[post_days, treated_unit].to_numpy(dtype=float)

        n_pre = pre_donors.shape[0]
        n_post = post_donors.shape[0]

        zeta = self.zeta_scale * regularisation_constant(pre_donors, 1, n_post)

        # Step 2 -- unit weights, on pre-period data only.
        unit_weights, unit_intercept = _solve_weights(
            pre_treated, pre_donors, penalty=zeta, n_periods=n_pre
        )

        # Step 3 -- time weights, predicting the donors' post-period average
        # from their pre-periods. Uses donor post-period outcomes only; the
        # treated unit's post-period never enters a weight.
        time_weights, time_intercept = _solve_weights(
            post_donors.mean(axis=0), pre_donors.T, penalty=0.0, n_periods=n_pre
        )

        # Step 4 -- closed form for a block assignment.
        synthetic_donor_path = (
            outcome.loc[:, list(donors)].to_numpy(dtype=float) @ unit_weights
        )
        pre_offsets = (
            outcome.loc[windows.pre_days, treated_unit].to_numpy(dtype=float)
            - synthetic_donor_path[: len(windows.pre_days)]
        )
        level_shift = float(time_weights @ pre_offsets)

        gap = pd.Series(
            outcome.loc[:, treated_unit].to_numpy(dtype=float)
            - (synthetic_donor_path + level_shift),
            index=outcome.index,
            name=treated_unit,
        )
        tau = float(gap.reindex(post_days).mean())

        pre_gap = gap.reindex(windows.pre_days).to_numpy(dtype=float)
        baseline = float(gap.loc[windows.baseline_day])
        post_gap_full = gap.reindex(windows.post_days).to_numpy(dtype=float) - baseline
        weight_series = pd.Series(unit_weights, index=list(donors), name="weight")

        return EffectEstimate(
            estimator=self.name,
            event_id=spec.event_id,
            treated_unit=treated_unit,
            tau=tau,
            gap=gap,
            pre_rmspe=rmspe(pre_gap),
            post_rmspe=rmspe(post_gap_full),
            n_pre=windows.n_pre,
            n_post=windows.n_post,
            weights=weight_series.sort_values(ascending=False),
            provenance=panel.provenance,
            is_placebo=spec.is_placebo_date,
            label=spec.label,
            extras={
                "zeta": zeta,
                "unit_intercept": unit_intercept,
                "time_intercept": time_intercept,
                "level_shift": level_shift,
                "n_donors": float(len(donors)),
                "max_weight": float(unit_weights.max()),
                "max_time_weight": float(time_weights.max()),
                "effective_pre_periods": float(
                    1.0 / float((time_weights**2).sum())
                    if float((time_weights**2).sum()) > 0
                    else 0.0
                ),
                "estimand_post_periods": float(n_post),
                # Same quantity computed the way SC and the market model
                # compute it, so the two baselines can be compared directly.
                "tau_baselined_last_pre": cumulative_abnormal_return(gap, windows),
                "post_treated_mean": float(post_treated.mean()),
            },
        )

    def time_weights(
        self, panel: ReturnPanel, spec: EventSpec, treated_unit: str
    ) -> pd.Series:
        r"""Fitted pre-period time weights, for the diagnostic plot.

        Worth looking at: a concentrated :math:`\lambda` means the baseline
        rests on a handful of pre-event days, which is fragile in the same way
        a concentrated donor weight is.
        """
        donors = self._check_unit(panel, spec, treated_unit)
        windows = spec.resolve(panel.trading_days)
        outcome = align_outcome(panel, windows, [treated_unit, *donors])
        post_days = (
            windows.post_days[-1:]
            if self.estimand is Estimand.HORIZON
            else windows.post_days
        )
        pre_donors = outcome.loc[windows.pre_days, list(donors)].to_numpy(dtype=float)
        post_donors = outcome.loc[post_days, list(donors)].to_numpy(dtype=float)
        weights, _ = _solve_weights(
            post_donors.mean(axis=0),
            pre_donors.T,
            penalty=0.0,
            n_periods=len(windows.pre_days),
        )
        return pd.Series(weights, index=windows.pre_days, name="time_weight")
