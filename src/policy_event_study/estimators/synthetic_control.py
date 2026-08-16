r"""Abadie synthetic control, with donor weights fit on the pre-window only.

Specification
-------------
Let :math:`Y_{1t}` be the treated unit's cumulative return and :math:`Y_{0t}`
the matrix of donor cumulative returns. Weights solve

.. math::

    \hat w = \arg\min_{w \in \Delta}
      \lVert Y_{1,\mathrm{pre}} - Y_{0,\mathrm{pre}} w \rVert_2^2
      + \lambda \lVert w \rVert_2^2

over the unit simplex :math:`\Delta` -- weights non-negative and summing to
one. The simplex constraint is the whole point of the method: it forbids
extrapolation, so the counterfactual is a genuine weighted average of firms
that existed rather than a linear combination that may sit far outside the
donors' support. It is also what makes SC fail *visibly* when the donor pool
cannot span the treated unit, which is the diagnostic Phase B2's kill
criterion is built on.

Point-in-time
-------------
`CLAUDE.md` §3: donor weights are fit on pre-period data only and the
pre-period is disclosed. :meth:`SyntheticControlEstimator.estimate` reads the
post-window exactly once, to compute the gap *after* the weights are fixed.
`tests/test_pointintime.py` asserts this by perturbing post-event returns and
checking the fitted weights do not move.

Non-uniqueness
--------------
When the donor pool is large relative to the number of pre-periods -- or when
donors are near-collinear, which sector peers reliably are -- the SC problem
has a continuum of optimal weight vectors, all with identical pre-treatment
fit and different post-event implications. `penalty` adds a small ridge that
selects the minimum-norm solution among them, making the answer unique and
reproducible. It defaults to a tiny value rather than zero for that reason,
and :mod:`policy_event_study.diagnostics.leave_one_out` is the check on
whether the choice among near-ties matters.
"""

from __future__ import annotations

from typing import ClassVar, Final

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

#: Default ridge, scaled by the outcome's own variance inside the solver.
#: Small enough not to bias the fit, large enough to pick a unique optimum
#: among near-collinear donors.
DEFAULT_PENALTY: Final[float] = 1e-6

#: Solvers tried in order. Both are deterministic; the fallback exists because
#: CLARABEL is not present in every cvxpy build.
_SOLVER_ORDER: Final[tuple[str, ...]] = ("CLARABEL", "ECOS", "SCS")


def solve_simplex_weights(
    treated: np.ndarray,
    donors: np.ndarray,
    *,
    penalty: float = DEFAULT_PENALTY,
    allow_intercept: bool = False,
) -> tuple[np.ndarray, float]:
    """Fit non-negative donor weights summing to one.

    Parameters
    ----------
    treated
        Pre-window outcome for the treated unit, shape `(T_pre,)`.
    donors
        Pre-window outcomes for the donors, shape `(T_pre, J)`.
    penalty
        Ridge coefficient, scaled internally by the treated outcome's variance
        so the same value behaves the same way across units of very different
        volatility.
    allow_intercept
        Adds an unconstrained level shift (Doudchenko-Imbens). Relaxes the
        requirement that the synthetic unit match the treated unit's *level*
        while still matching its path. Off by default: with the outcome
        normalised to zero at the start of the window, the level is already
        matched by construction, and an unconstrained intercept can mask a
        pre-trend that the diagnostics are meant to catch.

    Returns
    -------
    tuple[np.ndarray, float]
        Weights, and the intercept (zero when `allow_intercept` is False).
    """
    import cvxpy

    n_donors = donors.shape[1]
    weights = cvxpy.Variable(n_donors, nonneg=True)
    intercept = cvxpy.Variable() if allow_intercept else None

    scale = float(np.var(treated)) or 1.0
    fitted_values = donors @ weights
    residual = treated - (
        fitted_values if intercept is None else fitted_values + intercept
    )
    objective = cvxpy.Minimize(
        cvxpy.sum_squares(residual) + penalty * scale * cvxpy.sum_squares(weights)
    )
    problem = cvxpy.Problem(objective, [cvxpy.sum(weights) == 1])

    last_error: Exception | None = None
    for solver in _SOLVER_ORDER:
        if solver not in cvxpy.installed_solvers():
            continue
        try:
            problem.solve(solver=solver)
        except cvxpy.error.SolverError as exc:  # pragma: no cover - solver-specific
            last_error = exc
            continue
        if weights.value is not None:
            fitted = np.asarray(weights.value, dtype=float)
            # Clip the small negative values interior-point solvers leave
            # behind, then renormalise so the simplex constraint holds exactly.
            fitted = np.clip(fitted, 0.0, None)
            total = fitted.sum()
            if total > 0:
                fitted = fitted / total
            shift = 0.0 if intercept is None else float(intercept.value)
            return fitted, shift

    msg = f"no cvxpy solver converged (tried {_SOLVER_ORDER}); last error: {last_error}"
    raise RuntimeError(msg)


class SyntheticControlEstimator(EventStudyEstimator):
    """Abadie synthetic control over the common estimator interface.

    Parameters
    ----------
    penalty
        Ridge on the weights; see the module docstring on non-uniqueness.
    allow_intercept
        Doudchenko-Imbens level shift. Off by default.
    """

    name: ClassVar[str] = "synthetic_control"

    def __init__(
        self, *, penalty: float = DEFAULT_PENALTY, allow_intercept: bool = False
    ) -> None:
        self.penalty = penalty
        self.allow_intercept = allow_intercept

    def estimate(
        self, panel: ReturnPanel, spec: EventSpec, treated_unit: str
    ) -> EffectEstimate:
        """Fit weights on the estimation window, then read the post-window gap."""
        donors = self._check_unit(panel, spec, treated_unit)
        windows = spec.resolve(panel.trading_days)
        outcome = align_outcome(panel, windows, [treated_unit, *donors])

        pre_treated = outcome.loc[windows.pre_days, treated_unit].to_numpy(dtype=float)
        pre_donors = outcome.loc[windows.pre_days, list(donors)].to_numpy(dtype=float)

        weights, intercept = solve_simplex_weights(
            pre_treated,
            pre_donors,
            penalty=self.penalty,
            allow_intercept=self.allow_intercept,
        )

        # Weights are fixed above. Only now is the post window read.
        synthetic = (
            outcome.loc[:, list(donors)].to_numpy(dtype=float) @ weights + intercept
        )
        gap = pd.Series(
            outcome.loc[:, treated_unit].to_numpy(dtype=float) - synthetic,
            index=outcome.index,
            name=treated_unit,
        )

        pre_gap = gap.reindex(windows.pre_days).to_numpy(dtype=float)
        baseline = float(gap.loc[windows.baseline_day])
        post_gap = gap.reindex(windows.post_days).to_numpy(dtype=float) - baseline
        weight_series = pd.Series(weights, index=list(donors), name="weight")

        return EffectEstimate(
            estimator=self.name,
            event_id=spec.event_id,
            treated_unit=treated_unit,
            tau=cumulative_abnormal_return(gap, windows),
            gap=gap,
            pre_rmspe=rmspe(pre_gap),
            post_rmspe=rmspe(post_gap),
            n_pre=windows.n_pre,
            n_post=windows.n_post,
            weights=weight_series.sort_values(ascending=False),
            provenance=panel.provenance,
            is_placebo=spec.is_placebo_date,
            label=spec.label,
            extras={
                "intercept": intercept,
                "n_donors": float(len(donors)),
                "max_weight": float(weights.max()),
                "n_donors_above_1pct": float(int((weights > 0.01).sum())),
                "penalty": self.penalty,
            },
        )

    def synthetic_path(
        self, panel: ReturnPanel, spec: EventSpec, treated_unit: str
    ) -> pd.DataFrame:
        """Treated and synthetic outcome paths, for the pre-fit plot.

        The pre-fit plot is the single most informative figure in a synthetic
        control study, and Phase B2's deliverable requires it.
        """
        estimate = self.estimate(panel, spec, treated_unit)
        windows = spec.resolve(panel.trading_days)
        donors = list(estimate.weights.index)
        outcome = align_outcome(panel, windows, [treated_unit, *donors])
        synthetic = (
            outcome.loc[:, donors].to_numpy(dtype=float)
            @ estimate.weights.to_numpy(dtype=float)
            + estimate.extras["intercept"]
        )
        return pd.DataFrame(
            {
                "treated": outcome.loc[:, treated_unit],
                "synthetic": synthetic,
                "gap": estimate.gap,
                "is_post": outcome.index.isin(windows.post_days),
            },
            index=outcome.index,
        )
