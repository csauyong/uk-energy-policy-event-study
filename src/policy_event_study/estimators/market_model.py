r"""The market-model event study. Baseline first, per `CLAUDE.md` §4.

This is the estimator everyone runs, and it is implemented first, as
first-class code with its own tests, because a baseline assembled at the end
to lose gracefully is dishonest. Every SC and SDiD result in
`reports/event_study.md` is reported next to this one.

Specification
-------------
OLS on the estimation window::

    r_it = alpha_i + beta_i * r_mt + e_it

Abnormal return ``AR_t = r_it - alpha_i - beta_i * r_mt``; the reported gap is
``cumsum(AR)``, so that :func:`~policy_event_study.estimators.base.cumulative_abnormal_return`
means the same thing here as it does for the synthetic control, and the three
estimators land in the same units in the same table.

Inference, three ways
---------------------
The parametric standard error uses the Campbell-Lo-MacKinlay prediction-error
correction, which accounts for the estimation window's own sampling error
rather than treating alpha and beta as known:

.. math::

    \operatorname{Var}(CAR) = \sigma^2\left[L_2 + \frac{L_2^2}{L_1}
      + \frac{\left(\sum_{t\in E}(r_{mt}-\bar r_m)\right)^2}
             {\sum_{s\in L_1}(r_{ms}-\bar r_m)^2}\right]

That t-statistic is reported and it is *not* the headline. Two further tests
are supplied because the parametric one over-rejects badly here:

:func:`caar_tests`
    Cross-sectional aggregation. `docs/research_plan.md` Phase B1 names the
    single most common error in published event studies: when several firms
    share an event date, their abnormal returns are correlated in event time,
    and a t-test that assumes independence over-rejects. The Brown-Warner
    crude dependence adjustment estimates the standard error from the
    *portfolio's* time series over the estimation window, so cross-sectional
    correlation is absorbed rather than assumed away. The BMP standardised
    cross-sectional test additionally survives event-induced variance.

:mod:`policy_event_study.diagnostics.placebo_space`
    Because this estimator implements the common interface, it gets the same
    permutation inference as the synthetic control -- every donor treated in
    turn as if it were the event's target. That makes the comparison
    `CLAUDE.md` §4 asks for like-for-like, instead of a parametric t-test
    against a permutation p-value.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import ClassVar

import numpy as np
import pandas as pd
from scipy import stats

from policy_event_study.data.prices import ReturnPanel
from policy_event_study.estimators.base import (
    EffectEstimate,
    EventSpec,
    EventStudyEstimator,
    cumulative_abnormal_return,
    rmspe,
)


class MarketModelEstimator(EventStudyEstimator):
    """OLS market model with cumulative abnormal returns.

    Parameters
    ----------
    ridge
        Tiny ridge on the slope, guarding only against a degenerate market
        series in a synthetic test panel. Zero in production.
    """

    name: ClassVar[str] = "market_model"

    def __init__(self, *, ridge: float = 0.0) -> None:
        self.ridge = ridge

    def estimate(
        self, panel: ReturnPanel, spec: EventSpec, treated_unit: str
    ) -> EffectEstimate:
        """Fit on the estimation window and accumulate abnormal returns."""
        if treated_unit not in panel.returns.columns:
            msg = f"{treated_unit!r} is not in the panel"
            raise KeyError(msg)
        windows = spec.resolve(panel.trading_days)

        returns = panel.returns.loc[windows.all_days, treated_unit]
        market = panel.market.reindex(windows.all_days)

        pre_returns = returns.reindex(windows.pre_days).to_numpy(dtype=float)
        pre_market = market.reindex(windows.pre_days).to_numpy(dtype=float)

        design = np.column_stack([np.ones_like(pre_market), pre_market])
        gram = design.T @ design + self.ridge * np.eye(2)
        coefficients = np.linalg.solve(gram, design.T @ pre_returns)
        alpha, beta = float(coefficients[0]), float(coefficients[1])

        fitted = alpha + beta * pre_market
        residuals = pre_returns - fitted
        n_pre = len(pre_returns)
        degrees = max(n_pre - 2, 1)
        resid_var = float(residuals @ residuals) / degrees

        abnormal = returns - (alpha + beta * market)
        gap = abnormal.cumsum()
        gap.name = treated_unit

        tau = cumulative_abnormal_return(gap, windows)

        post_market = market.reindex(windows.post_days).to_numpy(dtype=float)
        market_mean = float(np.mean(pre_market))
        market_ss = float(np.sum((pre_market - market_mean) ** 2))
        n_post = len(windows.post_days)
        # Campbell-Lo-MacKinlay prediction-error variance: the second and third
        # terms are the cost of having estimated alpha and beta rather than
        # knowing them, and they do not vanish as the event window grows.
        forecast_penalty = (n_post**2) / n_pre if n_pre else 0.0
        market_penalty = (
            float(np.sum(post_market - market_mean)) ** 2 / market_ss
            if market_ss > 0
            else 0.0
        )
        var_car = resid_var * (n_post + forecast_penalty + market_penalty)
        se_car = float(np.sqrt(var_car)) if var_car > 0 else float("nan")
        t_stat = tau / se_car if se_car and np.isfinite(se_car) else float("nan")
        p_value = (
            float(2.0 * stats.t.sf(abs(t_stat), df=degrees))
            if np.isfinite(t_stat)
            else float("nan")
        )

        total_ss = float(np.sum((pre_returns - pre_returns.mean()) ** 2))
        r_squared = (
            1.0 - float(residuals @ residuals) / total_ss if total_ss > 0 else 0.0
        )

        pre_gap = gap.reindex(windows.pre_days).to_numpy(dtype=float)
        baseline = float(gap.loc[windows.baseline_day])
        post_gap = gap.reindex(windows.post_days).to_numpy(dtype=float) - baseline

        return EffectEstimate(
            estimator=self.name,
            event_id=spec.event_id,
            treated_unit=treated_unit,
            tau=tau,
            gap=gap,
            pre_rmspe=rmspe(pre_gap - pre_gap.mean()),
            post_rmspe=rmspe(post_gap),
            n_pre=n_pre,
            n_post=n_post,
            # No donor pool: the market model has one factor and no weights to
            # report. The emptiness is the substantive difference from SC.
            weights=pd.Series(dtype=float),
            provenance=panel.provenance,
            is_placebo=spec.is_placebo_date,
            label=spec.label,
            extras={
                "alpha": alpha,
                "beta": beta,
                "r_squared": r_squared,
                "resid_sd_daily": float(np.sqrt(resid_var)),
                "se_car": se_car,
                "t_stat": t_stat,
                "p_value_parametric": p_value,
                "ar_t0": float(abnormal.loc[windows.post_days[0]]),
            },
        )

    def abnormal_returns(
        self, panel: ReturnPanel, spec: EventSpec, treated_unit: str
    ) -> pd.Series:
        """Daily abnormal-return path, for the cross-sectional tests."""
        estimate = self.estimate(panel, spec, treated_unit)
        return estimate.gap.diff().fillna(estimate.gap.iloc[0])


def car_by_window(
    panel: ReturnPanel,
    spec: EventSpec,
    treated_unit: str,
    horizons: Sequence[tuple[int, int]] = ((-1, 1), (0, 1), (0, 5), (0, 20)),
    *,
    estimator: MarketModelEstimator | None = None,
) -> pd.DataFrame:
    """CARs over several event windows, as `docs/research_plan.md` Phase B1 asks.

    Windows are `(start, end)` in trading days relative to `t0`, `t0` being
    day 0. A window opening at -1 reaches back into the gap, which is
    deliberate: it is where a leak would show up.

    Reporting four windows means four looks at the same data. That is a
    multiple-comparisons cost, it is why `reports/decision_log.md` counts
    specifications, and the report states the count rather than quoting
    whichever window came out best.
    """
    engine = estimator if estimator is not None else MarketModelEstimator()
    estimate = engine.estimate(panel, spec, treated_unit)
    windows = spec.resolve(panel.trading_days)
    days = panel.trading_days
    origin = int(days.get_indexer(pd.DatetimeIndex([windows.t0]))[0])

    rows: list[dict[str, object]] = []
    for start, end in horizons:
        first, last = origin + start, origin + end
        if first < 1 or last >= len(days):
            continue
        segment = estimate.gap.reindex(days[first - 1 : last + 1])
        if segment.isna().any():
            continue
        rows.append(
            {
                "window": f"({start:+d},{end:+d})",
                "car": float(segment.iloc[-1] - segment.iloc[0]),
                "n_days": last - first + 1,
            }
        )
    return pd.DataFrame(rows)


def caar_tests(
    panel: ReturnPanel,
    spec: EventSpec,
    treated_units: Sequence[str],
    *,
    estimator: MarketModelEstimator | None = None,
) -> pd.DataFrame:
    """Cross-sectional aggregation with a dependence correction.

    Three tests over the same CAAR, reported together because they disagree in
    an informative way:

    ``naive_cross_sectional``
        CAAR divided by the cross-sectional standard error. Assumes abnormal
        returns are independent across firms. **They are not** -- these firms
        share an event date and a sector -- so this test over-rejects, and it
        is reported to show by how much.
    ``crude_dependence``
        Brown-Warner. The standard error comes from the time series of the
        equally-weighted *portfolio's* abnormal return over the estimation
        window, so whatever cross-sectional correlation exists is already
        inside it. This is the honest test when firms share a date.
    ``bmp``
        Boehmer-Musumeci-Poulsen. Standardises each firm's CAR by its own
        prediction-error standard deviation, then tests the mean of the
        standardised values cross-sectionally. Robust to event-induced
        variance, which an announcement day reliably produces.

    Returns
    -------
    pd.DataFrame
        One row per test with `statistic`, `p_value`, `caar` and `n_units`.
    """
    engine = estimator if estimator is not None else MarketModelEstimator()
    windows = spec.resolve(panel.trading_days)
    units = [unit for unit in treated_units if unit in panel.returns.columns]
    if len(units) < 2:
        msg = (
            "cross-sectional tests need at least two treated units; with one "
            "unit use the placebo distribution, which is the whole reason the "
            "single-unit case is handled by permutation rather than by a t-test"
        )
        raise ValueError(msg)

    estimates = [engine.estimate(panel, spec, unit) for unit in units]
    cars = np.array([est.tau for est in estimates], dtype=float)
    standardised = np.array(
        [est.tau / est.extras["se_car"] for est in estimates], dtype=float
    )
    caar = float(cars.mean())
    n_units = len(units)
    rows: list[dict[str, object]] = []

    cross_sd = float(cars.std(ddof=1))
    naive_se = cross_sd / np.sqrt(n_units) if cross_sd > 0 else float("nan")
    naive_t = caar / naive_se if naive_se and np.isfinite(naive_se) else float("nan")
    rows.append(
        {
            "test": "naive_cross_sectional",
            "statistic": naive_t,
            "p_value": float(2.0 * stats.norm.sf(abs(naive_t)))
            if np.isfinite(naive_t)
            else float("nan"),
            "caar": caar,
            "n_units": n_units,
            "note": "assumes independence across firms; over-rejects on shared dates",
        }
    )

    # Crude dependence adjustment: build the equally-weighted portfolio's
    # abnormal return series and take its estimation-window standard deviation.
    portfolio_ar = pd.concat(
        [est.gap.diff().fillna(est.gap.iloc[0]) for est in estimates], axis=1
    ).mean(axis=1)
    pre_portfolio = portfolio_ar.reindex(windows.pre_days).to_numpy(dtype=float)
    portfolio_sd = float(np.std(pre_portfolio, ddof=1))
    crude_se = portfolio_sd * np.sqrt(windows.n_post)
    crude_t = caar / crude_se if crude_se > 0 else float("nan")
    rows.append(
        {
            "test": "crude_dependence",
            "statistic": crude_t,
            "p_value": float(2.0 * stats.norm.sf(abs(crude_t)))
            if np.isfinite(crude_t)
            else float("nan"),
            "caar": caar,
            "n_units": n_units,
            "note": "Brown-Warner; SE from the portfolio's own estimation-window series",
        }
    )

    bmp_mean = float(standardised.mean())
    bmp_sd = float(standardised.std(ddof=1))
    bmp_t = bmp_mean * np.sqrt(n_units) / bmp_sd if bmp_sd > 0 else float("nan")
    rows.append(
        {
            "test": "bmp",
            "statistic": bmp_t,
            "p_value": float(2.0 * stats.t.sf(abs(bmp_t), df=n_units - 1))
            if np.isfinite(bmp_t)
            else float("nan"),
            "caar": caar,
            "n_units": n_units,
            "note": "Boehmer-Musumeci-Poulsen; robust to event-induced variance",
        }
    )

    return pd.DataFrame(rows)


def bootstrap_car(
    panel: ReturnPanel,
    spec: EventSpec,
    treated_unit: str,
    *,
    seed: int,
    n_draws: int = 2000,
    block_length: int = 5,
    estimator: MarketModelEstimator | None = None,
) -> dict[str, float]:
    """Circular block bootstrap of the CAR null, from estimation-window residuals.

    Resampling *blocks* rather than individual days preserves the
    autocorrelation in daily abnormal returns; resampling days independently
    would understate the standard error for the same reason a naive
    cross-sectional test does.

    Deterministic given `seed`, per `CLAUDE.md` §7.

    Returns
    -------
    dict[str, float]
        `tau`, the bootstrap `p_value` (two-sided), and the 2.5/97.5
        percentiles of the null distribution.
    """
    engine = estimator if estimator is not None else MarketModelEstimator()
    estimate = engine.estimate(panel, spec, treated_unit)
    windows = spec.resolve(panel.trading_days)
    abnormal = estimate.gap.diff().fillna(estimate.gap.iloc[0])
    pre = abnormal.reindex(windows.pre_days).to_numpy(dtype=float)
    pre = pre - pre.mean()

    rng = np.random.default_rng(seed)
    n_post = windows.n_post
    n_blocks = int(np.ceil(n_post / block_length))
    draws = np.empty(n_draws, dtype=float)
    for draw in range(n_draws):
        starts = rng.integers(0, len(pre), size=n_blocks)
        sample = np.concatenate(
            [
                np.take(pre, np.arange(start, start + block_length), mode="wrap")
                for start in starts
            ]
        )[:n_post]
        draws[draw] = float(sample.sum())

    p_value = float((np.abs(draws) >= abs(estimate.tau)).mean())
    return {
        "tau": estimate.tau,
        "p_value_bootstrap": p_value,
        "null_q025": float(np.quantile(draws, 0.025)),
        "null_q975": float(np.quantile(draws, 0.975)),
        "n_draws": float(n_draws),
    }
