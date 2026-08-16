"""Detectability limits: how large an effect this design could have found.

The section title question is "how large an effect could this design actually
have detected?", and the answer belongs in every report carrying a null.

A null result means nothing until this question is answered. With one treated
firm, one event and a donor pool in the low tens, the honest answer is often
"only an enormous one" -- and saying so converts an uninformative null into an
informative statement about the design's limits. `reports/event_study.md` is
required to carry this section.

Three separate limits, and they bind in different places
--------------------------------------------------------
1. **The arithmetic floor.** A permutation test over ``J`` placebos cannot
   produce a p-value below ``1 / (J + 1)``. With 23 donors that floor is
   0.042: a 5% threshold is reachable, a 1% threshold is *impossible*
   regardless of the data. :func:`min_attainable_p` and
   :func:`donors_required_for` quantify this, and it is knowable before any
   estimation.

2. **The noise floor.** Even when the arithmetic permits rejection, the
   effect must clear the placebo distribution's upper tail.
   :func:`power_analysis` reports the minimum detectable effect: the smallest
   true effect that would be rejected at level ``alpha`` with the requested
   power.

3. **The correlation floor.** Pooling exposed firms does not multiply the
   sample the way a row count suggests. `CLAUDE.md` §3 requires reporting
   *effective* independent observations rather than raw ones, and
   :func:`effective_sample_size` computes that for a set of firms whose
   abnormal returns are correlated -- which same-sector firms sharing an event
   date reliably are.

The identifying assumption behind the MDE
-----------------------------------------
:func:`power_analysis` treats the placebo distribution as the treated unit's
null distribution and assumes a true effect shifts it in location without
changing its shape. That is the same exchangeability assumption the
permutation p-value already rests on, so the MDE is no more heroic than the
p-value beside it -- but it is an assumption, and a treated unit substantially
more volatile than its donors will have its power overstated. The normalised
pre-RMSPE in
:class:`~policy_event_study.diagnostics.pretrends.PreFitReport` is the check
on that.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

from policy_event_study.diagnostics.placebo_space import PlaceboDistribution
from policy_event_study.estimators.base import EffectEstimate
from policy_event_study.events.schema import ExpectedDirection


def min_attainable_p(n_placebos: int) -> float:
    """Smallest p-value a permutation test over `n_placebos` units can produce."""
    return 1.0 / (n_placebos + 1.0)


def donors_required_for(alpha: float) -> int:
    """Donors needed before level `alpha` is even arithmetically reachable.

    Rejecting at `alpha` requires ``1 / (J + 1) <= alpha``, so
    ``J >= 1/alpha - 1``. At the 5% level that is 19 donors; at 1%, 99 --
    which for a study restricted to plausibly untreated UK and European
    listings is not obtainable, and is the reason this project reports at 5%
    and does not pretend otherwise.
    """
    return math.ceil(1.0 / alpha - 1.0)


@dataclass(frozen=True)
class PowerAnalysis:
    """Minimum detectable effect against a placebo reference distribution."""

    estimator: str
    event_id: str
    treated_unit: str
    alpha: float
    target_power: float
    n_placebos: int
    critical_value: float
    mde: float
    mde_at_50_power: float
    observed_tau: float
    placebo_sd: float
    direction: ExpectedDirection

    @property
    def feasible(self) -> bool:
        """False when the donor pool is too small to reject at `alpha` at all."""
        return min_attainable_p(self.n_placebos) <= self.alpha

    @property
    def observed_over_mde(self) -> float:
        """Observed effect as a multiple of the minimum detectable one.

        Below 1 with a null result is the interesting case: it says the study
        could not have found an effect of the size actually observed, so the
        null is uninformative about effects that small.
        """
        if self.mde == 0 or not np.isfinite(self.mde):
            return float("nan")
        return abs(self.observed_tau) / abs(self.mde)

    def summary(self) -> pd.Series:
        """One-line summary for a report table."""
        return pd.Series(
            {
                "estimator": self.estimator,
                "event_id": self.event_id,
                "treated_unit": self.treated_unit,
                "n_placebos": self.n_placebos,
                "alpha": self.alpha,
                "min_attainable_p": min_attainable_p(self.n_placebos),
                "feasible_at_alpha": self.feasible,
                "critical_value": self.critical_value,
                f"mde_at_{int(self.target_power * 100)}pct_power": self.mde,
                "mde_at_50pct_power": self.mde_at_50_power,
                "observed_tau": self.observed_tau,
                "observed_over_mde": self.observed_over_mde,
            }
        )

    def narrative(self) -> str:
        """One paragraph of plain English, for pasting into the report."""
        if not self.feasible:
            return (
                f"{self.treated_unit} / {self.event_id} ({self.estimator}): with "
                f"{self.n_placebos} usable placebos the smallest attainable p-value "
                f"is {min_attainable_p(self.n_placebos):.3f}, which exceeds the "
                f"{self.alpha:.0%} threshold. This design cannot reject at that "
                "level for any effect size; the result is uninformative about "
                "significance and only the point estimate and its placebo "
                "distribution should be read."
            )
        return (
            f"{self.treated_unit} / {self.event_id} ({self.estimator}): with "
            f"{self.n_placebos} placebos, an effect had to reach "
            f"{self.critical_value:+.2%} cumulative abnormal return to fall in the "
            f"{self.alpha:.0%} tail of the placebo distribution, and "
            f"{self.mde:+.2%} to be detected {self.target_power:.0%} of the time. "
            f"The observed effect was {self.observed_tau:+.2%}, "
            f"{self.observed_over_mde:.2f}x the minimum detectable effect."
        )


def power_analysis(
    distribution: PlaceboDistribution,
    *,
    alpha: float = 0.05,
    target_power: float = 0.80,
) -> PowerAnalysis:
    r"""Minimum detectable effect from an in-space placebo distribution.

    Under a location-shift alternative the treated statistic is
    :math:`\delta + \varepsilon` with :math:`\varepsilon` drawn from the
    signed placebo distribution :math:`F`. Rejection needs the *test*
    statistic to clear its critical value :math:`c`, so for :math:`\delta>0`

    .. math:: P(\text{reject}) = 1 - F(c - \delta) = \pi
              \;\Longrightarrow\;
              \delta = c - F^{-1}(1 - \pi).

    At 50% power this reduces to :math:`\delta = c - \text{median}(F)` --
    the familiar "an effect exactly at the critical value is detected half the
    time".

    **The two distributions in that formula are not the same one, and
    conflating them inverts the answer.** The critical value :math:`c` comes
    from whichever statistic the test actually thresholds: the signed placebo
    taus for a pre-registered direction, their absolute values for an
    ambiguous one. The power quantile :math:`F^{-1}(1-\pi)` always comes from
    the **signed** distribution, because the alternative shifts
    :math:`\varepsilon`, not :math:`|\varepsilon|` -- the treated statistic
    under :math:`H_1` is :math:`|\delta + \varepsilon|`, not
    :math:`\delta + |\varepsilon|`. Taking both quantiles from the absolute
    distribution makes a two-sided test appear *more* powerful than the
    one-sided test on the same data, which is impossible.

    The tail therefore follows the event dictionary's pre-registered
    ``expected_direction``: one-sided where a direction was recorded before
    the returns were seen, two-sided where it was recorded as ambiguous.
    """
    placebos = distribution.placebo_taus.to_numpy(dtype=float)
    if placebos.size == 0:
        msg = (
            f"no usable placebos for {distribution.treated_unit!r} on event "
            f"{distribution.event_id!r}; power cannot be assessed and neither "
            "can significance"
        )
        raise ValueError(msg)

    direction = distribution.expected_direction
    if direction is ExpectedDirection.NEGATIVE:
        # Extreme is the lower tail; negate so the same quantile arithmetic
        # applies, and flip the reported signs back at the end.
        signed = -placebos
        sign = -1.0
    else:
        signed = placebos
        sign = 1.0

    # The statistic the test thresholds...
    tail_statistic = (
        np.abs(placebos) if direction is ExpectedDirection.AMBIGUOUS else signed
    )
    critical = float(np.quantile(tail_statistic, 1.0 - alpha))
    # ...but the alternative shifts the signed statistic.
    mde = critical - float(np.quantile(signed, 1.0 - target_power))
    mde_50 = critical - float(np.quantile(signed, 0.5))

    return PowerAnalysis(
        estimator=distribution.estimator,
        event_id=distribution.event_id,
        treated_unit=distribution.treated_unit,
        alpha=alpha,
        target_power=target_power,
        n_placebos=distribution.n_placebos,
        critical_value=sign * critical,
        mde=sign * mde,
        mde_at_50_power=sign * mde_50,
        observed_tau=distribution.treated_tau,
        placebo_sd=float(np.std(placebos, ddof=1))
        if placebos.size > 1
        else float("nan"),
        direction=direction,
    )


def power_curve(
    distribution: PlaceboDistribution,
    effect_sizes: Sequence[float],
    *,
    alpha: float = 0.05,
) -> pd.DataFrame:
    """Trace detection probability across a grid of hypothetical true effects.

    More useful in a report than a single MDE, because it shows the shape of
    the trade-off: for a design this small the curve is typically flat and low
    over the entire range of economically plausible policy effects, which is a
    more persuasive statement of the limitation than any one number.

    Uses the same two-distribution construction as :func:`power_analysis` --
    critical value from the thresholded statistic, shift applied to the signed
    one.
    """
    placebos = distribution.placebo_taus.to_numpy(dtype=float)
    direction = distribution.expected_direction
    signed = -placebos if direction is ExpectedDirection.NEGATIVE else placebos
    tail_statistic = (
        np.abs(placebos) if direction is ExpectedDirection.AMBIGUOUS else signed
    )
    critical = float(np.quantile(tail_statistic, 1.0 - alpha))
    rows = [
        {
            "effect_size": effect,
            "detection_probability": float(
                np.mean(np.abs(signed + abs(effect)) >= critical)
                if direction is ExpectedDirection.AMBIGUOUS
                else np.mean(signed + abs(effect) >= critical)
            ),
        }
        for effect in effect_sizes
    ]
    return pd.DataFrame(rows)


def market_model_mde(estimate: EffectEstimate, *, alpha: float = 0.05) -> float:
    """Analytic MDE for the market model, from its prediction-error standard error.

    Reported next to the permutation MDE. The two disagreeing is informative:
    the parametric figure is usually the smaller, and the gap between them is
    a measure of how much the market model's standard error understates the
    real uncertainty once cross-sectional dependence and event-induced
    variance are accounted for.
    """
    from scipy import stats

    se = float(estimate.extras.get("se_car", float("nan")))
    if not np.isfinite(se):
        return float("nan")
    return float(stats.norm.ppf(1.0 - alpha / 2.0) * se)


def effective_sample_size(abnormal_returns: pd.DataFrame) -> float:
    r"""Effective independent observations for a set of correlated units.

    `CLAUDE.md` §3 requires reporting effective independent observations
    rather than raw counts. For ``N`` units with average pairwise correlation
    :math:`\rho`, the design effect gives

    .. math:: N_{\text{eff}} = \frac{N}{1 + (N-1)\rho}.

    Seven housebuilders correlated at 0.7 are worth about 1.4 independent
    observations, not seven. Any standard error computed as though there were
    seven is wrong by a factor of two, which is the concrete form of the
    over-rejection `docs/research_plan.md` Phase B1 warns about.

    Parameters
    ----------
    abnormal_returns
        Columns are units, rows are days -- typically the estimation-window
        abnormal returns from the market model.
    """
    if abnormal_returns.shape[1] < 2:
        return float(abnormal_returns.shape[1])
    correlation = abnormal_returns.corr().to_numpy(dtype=float)
    n_units = correlation.shape[0]
    off_diagonal = correlation[~np.eye(n_units, dtype=bool)]
    rho = float(np.nanmean(off_diagonal))
    denominator = 1.0 + (n_units - 1) * rho
    if denominator <= 0:
        return float(n_units)
    return float(n_units / denominator)


def design_summary(
    n_donors: int, n_events: int, n_treated: int, *, alpha: float = 0.05
) -> pd.DataFrame:
    """Design limits knowable before any estimation runs.

    Worth computing at the start of Phase B0 rather than discovering at the
    end of Phase B3: if `min_attainable_p` already exceeds `alpha`, no amount
    of estimator development will produce a significant result, and the
    project should be reframed around the diagnostic finding instead.
    """
    return pd.DataFrame(
        [
            {
                "quantity": "donors in pool",
                "value": float(n_donors),
                "note": "in-space placebo units available per event",
            },
            {
                "quantity": "min attainable p (in-space)",
                "value": min_attainable_p(n_donors),
                "note": f"1/(J+1); must be <= {alpha} to reject at that level",
            },
            {
                "quantity": f"donors required for alpha={alpha}",
                "value": float(donors_required_for(alpha)),
                "note": "arithmetic floor, independent of the data",
            },
            {
                "quantity": "events",
                "value": float(n_events),
                "note": "Phase B0 kill criterion: fewer than ~8-10 clean events",
            },
            {
                "quantity": "treated units",
                "value": float(n_treated),
                "note": "before the correlation haircut in effective_sample_size",
            },
        ]
    )
