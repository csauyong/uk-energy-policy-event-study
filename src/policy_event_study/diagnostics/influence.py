r"""Influence diagnostics: is beta identified off the cross-section or a few names.

The question is whether beta is identified off the whole cross-section or off
a handful of extreme names.

The dose-response design's claim to power rests on having several hundred
observations. But exposure is heavily right-skewed -- most firms score exactly
zero and a fully exposed firm sits several standard deviations out -- so the
regression's *effective* sample can be far smaller than its nominal one.

**Several hundred observations with five influential ones is the small-N
problem wearing a large-N regression as a costume.** Nothing else in the
pipeline would surface it: the standard error, the bootstrap and the
randomisation test are all computed on the same design matrix and are all
equally happy to let a handful of leverage points carry the answer.

Five checks, and each catches something the others miss
-------------------------------------------------------
:func:`leverage_report`
    Hat values and Cook's distance per observation, plus the share of total
    leverage held by the top 1% and top 5%. In a balanced design each
    observation holds :math:`p/n` of the leverage; concentration far above
    that means the design is not what the row count suggests.

:func:`top_k_drop_path`
    Re-estimate dropping the *k* most exposed firms, for k = 1, 2, 3, 5. **A
    beta that dies at k = 3 is a statement about three firms, not about
    exposure.** Firms are dropped entirely, not single observations: a firm
    appears once per event and dropping one of its rows would leave the rest
    of its influence in place.

:func:`winsorised_variant`
    Re-standardise with exposure clipped at the 1st/99th percentile within
    event. Separates "the gradient is real" from "one extreme score is
    levering the fit".

:func:`functional_form_comparison`
    `exposure_continuous` against `exposure_rank`, head to head. The rank is
    monotone-invariant, so divergence means the result depends on the shape of
    the scoring function rather than on the ordering of firms by exposure.

:func:`effective_firm_count`
    Leverage-based participation ratio: the inverse Herfindahl of each firm's
    share of total leverage. **The nominal firm count must never appear in the
    report without this beside it.**
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final

import numpy as np
import pandas as pd

from policy_event_study.estimators.dose_response import (
    DEFAULT_CONTROLS,
    DoseResponseResult,
    WeightScheme,
    _design_matrix,
    _ols,
    estimate_dose_response,
)

#: Drop depths reported by :func:`top_k_drop_path`.
DEFAULT_DROP_DEPTHS: Final[tuple[int, ...]] = (1, 2, 3, 5)

#: Winsorisation bounds for the influence variant, within event.
WINSOR_QUANTILES: Final[tuple[float, float]] = (0.01, 0.99)


@dataclass(frozen=True)
class LeverageReport:
    """Distribution of leverage and influence across observations."""

    hat_values: pd.Series
    cooks_distance: pd.Series
    n_observations: int
    n_parameters: int
    leverage_share_top_1pct: float
    leverage_share_top_5pct: float
    effective_firms: float
    nominal_firms: float
    max_cooks: float
    n_cooks_above_threshold: int

    @property
    def balanced_share(self) -> float:
        """Leverage a single observation would hold in a balanced design."""
        return self.n_parameters / self.n_observations if self.n_observations else 0.0

    @property
    def participation_fraction(self) -> float:
        """Effective firms as a fraction of nominal. Below ~0.2 is a red flag."""
        return self.effective_firms / self.nominal_firms if self.nominal_firms else 0.0

    @property
    def concentrated(self) -> bool:
        """True when the top 5% of observations hold more than half the leverage."""
        return self.leverage_share_top_5pct > 0.5

    def summary(self) -> pd.Series:
        """One-line summary for a report table."""
        return pd.Series(
            {
                "n_obs": self.n_observations,
                "nominal_firms": self.nominal_firms,
                "effective_firms": self.effective_firms,
                "participation_fraction": self.participation_fraction,
                "leverage_top_1pct": self.leverage_share_top_1pct,
                "leverage_top_5pct": self.leverage_share_top_5pct,
                "max_cooks_d": self.max_cooks,
                "n_cooks_above_4_over_n": self.n_cooks_above_threshold,
                "concentrated": self.concentrated,
            }
        )


@dataclass(frozen=True)
class DropPathStep:
    """One rung of the top-k drop path."""

    k: int
    dropped_units: tuple[str, ...]
    beta: float
    p_wild_bootstrap: float
    n_observations: int
    share_of_beta_retained: float


@dataclass(frozen=True)
class InfluenceReport:
    """Everything the report's influence section needs."""

    leverage: LeverageReport
    drop_path: tuple[DropPathStep, ...]
    winsorised_beta: float
    winsorised_p: float
    continuous_beta: float
    rank_beta: float
    rank_correlation: float
    baseline_beta: float
    baseline_p: float
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def survives_drop_path(self) -> bool:
        """True when sign holds and at least half of beta survives every rung."""
        if not self.drop_path:
            return False
        return all(
            np.sign(step.beta) == np.sign(self.baseline_beta)
            and step.share_of_beta_retained >= 0.5
            for step in self.drop_path
        )

    @property
    def functional_form_agrees(self) -> bool:
        """True when the continuous and rank variants agree in sign."""
        if self.continuous_beta == 0 or self.rank_beta == 0:
            return False
        return bool(np.sign(self.continuous_beta) == np.sign(self.rank_beta))

    @property
    def verdict(self) -> str:
        """Plain-language reading, for the report."""
        if not self.survives_drop_path:
            failed = next(
                step
                for step in self.drop_path
                if np.sign(step.beta) != np.sign(self.baseline_beta)
                or step.share_of_beta_retained < 0.5
            )
            return (
                f"FRAGILE: beta does not survive dropping the {failed.k} most "
                f"exposed firm(s) ({', '.join(failed.dropped_units)}). This is a "
                "statement about those firms, not about exposure."
            )
        if not self.functional_form_agrees:
            return (
                "FRAGILE: the continuous and rank variants disagree in sign, so "
                "the result depends on the shape of the scoring function rather "
                "than on the ordering of firms by exposure."
            )
        if self.leverage.concentrated:
            return (
                "CAUTION: the top 5% of observations hold over half the total "
                "leverage. Beta survives the drop path, but the effective "
                f"cross-section is {self.leverage.effective_firms:.0f} firms "
                f"against a nominal {self.leverage.nominal_firms:.0f}."
            )
        return (
            "ROBUST: beta survives the drop path, the functional-form variants "
            "agree, and leverage is not concentrated."
        )

    def table(self) -> pd.DataFrame:
        """Drop path as a frame."""
        return pd.DataFrame(
            [
                {
                    "k": step.k,
                    "dropped": ", ".join(step.dropped_units),
                    "beta": step.beta,
                    "p_wild": step.p_wild_bootstrap,
                    "share_retained": step.share_of_beta_retained,
                    "n_obs": step.n_observations,
                }
                for step in self.drop_path
            ]
        )


def effective_firm_count(
    hat_values: pd.Series, unit_ids: pd.Series
) -> tuple[float, float]:
    r"""Participation ratio of firms, weighted by leverage.

    Each firm's share of total leverage :math:`s_j` gives

    .. math:: N_{\text{eff}} = \frac{1}{\sum_j s_j^2},

    the inverse Herfindahl -- the same construction used for donor weights in
    the synthetic-control diagnostics. Equal leverage across :math:`J` firms
    returns :math:`J`; leverage concentrated on one firm returns 1.

    Returns
    -------
    tuple[float, float]
        ``(effective, nominal)``.
    """
    by_firm = pd.DataFrame({"unit": unit_ids.to_numpy(), "h": hat_values.to_numpy()})
    totals = by_firm.groupby("unit")["h"].sum()
    nominal = float(len(totals))
    total = float(totals.sum())
    if total <= 0:
        return nominal, nominal
    shares = (totals / total).to_numpy(dtype=float)
    denominator = float((shares**2).sum())
    return (1.0 / denominator if denominator > 0 else nominal), nominal


def leverage_report(
    frame: pd.DataFrame,
    *,
    exposure_column: str = "exposure_continuous",
    controls: Sequence[str] = DEFAULT_CONTROLS,
) -> LeverageReport:
    """Hat values, Cook's distance, and leverage concentration."""
    required = {"unit_id", "event_id", "car", exposure_column, *controls}
    missing = sorted(required - set(frame.columns))
    if missing:
        msg = f"frame is missing columns {missing}"
        raise ValueError(msg)

    working = frame.dropna(subset=list(required)).copy()
    design, _, _ = _design_matrix(working, exposure_column, controls)
    response = working["car"].to_numpy(dtype=float)

    beta = _ols(design, response)
    residuals = response - design @ beta
    n_obs, n_params = design.shape

    gram_inv = np.linalg.pinv(design.T @ design)
    hat = np.einsum("ij,jk,ik->i", design, gram_inv, design)
    hat = np.clip(hat, 0.0, 1.0 - 1e-12)

    sigma_squared = float(residuals @ residuals) / max(n_obs - n_params, 1)
    cooks = (
        (residuals**2) / (n_params * sigma_squared) * (hat / (1.0 - hat) ** 2)
        if sigma_squared > 0
        else np.zeros_like(hat)
    )

    order = np.argsort(hat)[::-1]
    total_leverage = float(hat.sum())
    top_1 = max(int(np.ceil(0.01 * n_obs)), 1)
    top_5 = max(int(np.ceil(0.05 * n_obs)), 1)
    share_1 = (
        float(hat[order[:top_1]].sum() / total_leverage) if total_leverage else 0.0
    )
    share_5 = (
        float(hat[order[:top_5]].sum() / total_leverage) if total_leverage else 0.0
    )

    hat_series = pd.Series(hat, index=working.index, name="hat")
    effective, nominal = effective_firm_count(hat_series, working["unit_id"])

    # The conventional Cook's distance flag.
    threshold = 4.0 / n_obs if n_obs else np.inf

    return LeverageReport(
        hat_values=hat_series,
        cooks_distance=pd.Series(cooks, index=working.index, name="cooks_d"),
        n_observations=n_obs,
        n_parameters=n_params,
        leverage_share_top_1pct=share_1,
        leverage_share_top_5pct=share_5,
        effective_firms=effective,
        nominal_firms=nominal,
        max_cooks=float(np.max(cooks)) if cooks.size else float("nan"),
        n_cooks_above_threshold=int((cooks > threshold).sum()),
    )


def top_k_drop_path(
    frame: pd.DataFrame,
    *,
    scheme: WeightScheme,
    exposure_column: str = "exposure_continuous",
    controls: Sequence[str] = DEFAULT_CONTROLS,
    depths: Sequence[int] = DEFAULT_DROP_DEPTHS,
    seed: int = 20260815,
    bootstrap_draws: int = 500,
) -> tuple[DropPathStep, ...]:
    """Re-estimate beta dropping the k most exposed firms, for each k.

    Ranking is by each firm's **maximum absolute exposure across events**, so a
    firm that is extreme once is caught. Whole firms are dropped, not
    individual rows: a firm appears once per event, and dropping a single row
    would leave the rest of its influence in the fit.
    """
    baseline = estimate_dose_response(
        frame,
        scheme=scheme,
        exposure_column=exposure_column,
        controls=controls,
        seed=seed,
        bootstrap_draws=bootstrap_draws,
        randomisation_draws=1,
    )

    ranked = (
        frame.assign(_abs=frame[exposure_column].abs())
        .groupby("unit_id")["_abs"]
        .max()
        .sort_values(ascending=False)
    )

    steps: list[DropPathStep] = []
    required = [exposure_column, "car", *controls]
    for depth in depths:
        dropped = tuple(str(unit) for unit in ranked.index[:depth])
        reduced = frame[~frame["unit_id"].isin(dropped)]
        # Counted here, once, so both branches below report the SAME quantity.
        #
        # They did not. The success branch used `result.n_observations`, which
        # `estimate_dose_response` reports AFTER dropping rows with a missing
        # control; the failure branch used `len(reduced)`, which is before. The
        # drop path therefore printed n RISING from 664 to 666 as a second firm
        # was removed -- an impossible number that looked plausible enough to
        # reach `reports/results.md` section 4.3. Neither branch was wrong on
        # its own; they were answering different questions under one column
        # name, which is the failure mode this project keeps re-finding.
        complete = len(reduced.dropna(subset=required))
        try:
            result = estimate_dose_response(
                reduced,
                scheme=scheme,
                exposure_column=exposure_column,
                controls=controls,
                seed=seed,
                bootstrap_draws=bootstrap_draws,
                randomisation_draws=1,
            )
        except ValueError:
            # Dropping the most exposed firms can remove all within-event
            # variation. That is itself the finding.
            steps.append(
                DropPathStep(
                    k=depth,
                    dropped_units=dropped,
                    beta=float("nan"),
                    p_wild_bootstrap=float("nan"),
                    n_observations=complete,
                    share_of_beta_retained=0.0,
                )
            )
            continue
        steps.append(
            DropPathStep(
                k=depth,
                dropped_units=dropped,
                beta=result.beta,
                p_wild_bootstrap=result.p_wild_bootstrap,
                n_observations=complete,
                share_of_beta_retained=(
                    result.beta / baseline.beta if baseline.beta != 0 else float("nan")
                ),
            )
        )
    return tuple(steps)


def winsorised_variant(
    frame: pd.DataFrame,
    *,
    scheme: WeightScheme,
    exposure_column: str = "exposure_continuous",
    controls: Sequence[str] = DEFAULT_CONTROLS,
    quantiles: tuple[float, float] = WINSOR_QUANTILES,
    seed: int = 20260815,
    bootstrap_draws: int = 500,
) -> DoseResponseResult:
    """Re-estimate with exposure clipped at the given quantiles, within event.

    Clipping then re-standardising within event, rather than clipping the
    pooled column, keeps the treatment consistent with how exposure was built.
    """
    clipped = frame.copy()

    def _clip(values: pd.Series) -> pd.Series:
        lower, upper = values.quantile(quantiles[0]), values.quantile(quantiles[1])
        bounded = values.clip(lower=lower, upper=upper)
        spread = float(bounded.std(ddof=1))
        return (bounded - bounded.mean()) / spread if spread > 0 else bounded * 0.0

    clipped[exposure_column] = clipped.groupby("event_id")[exposure_column].transform(
        _clip
    )
    return estimate_dose_response(
        clipped,
        scheme=scheme,
        exposure_column=exposure_column,
        controls=controls,
        seed=seed,
        bootstrap_draws=bootstrap_draws,
        randomisation_draws=1,
    )


def functional_form_comparison(
    frame: pd.DataFrame,
    *,
    scheme: WeightScheme,
    controls: Sequence[str] = DEFAULT_CONTROLS,
    seed: int = 20260815,
    bootstrap_draws: int = 500,
) -> tuple[float, float, float]:
    """Continuous against rank exposure, head to head.

    Returns
    -------
    tuple[float, float, float]
        ``(beta_continuous, beta_rank, spearman_correlation)``. The correlation
        is between the two exposure columns, so a low value explains a
        divergence in beta without needing to guess at one.
    """
    continuous = estimate_dose_response(
        frame,
        scheme=scheme,
        exposure_column="exposure_continuous",
        controls=controls,
        seed=seed,
        bootstrap_draws=bootstrap_draws,
        randomisation_draws=1,
    )
    rank = estimate_dose_response(
        frame,
        scheme=scheme,
        exposure_column="exposure_rank",
        controls=controls,
        seed=seed,
        bootstrap_draws=bootstrap_draws,
        randomisation_draws=1,
    )
    correlation = float(
        frame["exposure_continuous"].corr(frame["exposure_rank"], method="spearman")
    )
    return continuous.beta, rank.beta, correlation


def influence_report(
    frame: pd.DataFrame,
    *,
    scheme: WeightScheme,
    exposure_column: str = "exposure_continuous",
    controls: Sequence[str] = DEFAULT_CONTROLS,
    depths: Sequence[int] = DEFAULT_DROP_DEPTHS,
    seed: int = 20260815,
    bootstrap_draws: int = 500,
) -> InfluenceReport:
    """Run the whole influence battery. Required before any beta is reported."""
    baseline = estimate_dose_response(
        frame,
        scheme=scheme,
        exposure_column=exposure_column,
        controls=controls,
        seed=seed,
        bootstrap_draws=bootstrap_draws,
        randomisation_draws=1,
    )
    leverage = leverage_report(
        frame, exposure_column=exposure_column, controls=controls
    )
    drop_path = top_k_drop_path(
        frame,
        scheme=scheme,
        exposure_column=exposure_column,
        controls=controls,
        depths=depths,
        seed=seed,
        bootstrap_draws=bootstrap_draws,
    )
    winsorised = winsorised_variant(
        frame,
        scheme=scheme,
        exposure_column=exposure_column,
        controls=controls,
        seed=seed,
        bootstrap_draws=bootstrap_draws,
    )
    continuous_beta, rank_beta, correlation = functional_form_comparison(
        frame,
        scheme=scheme,
        controls=controls,
        seed=seed,
        bootstrap_draws=bootstrap_draws,
    )

    notes: list[str] = []
    if leverage.participation_fraction < 0.2:
        notes.append(
            f"Only {leverage.effective_firms:.0f} of {leverage.nominal_firms:.0f} "
            "firms effectively contribute to beta. The nominal cross-section is "
            "not the identifying one."
        )
    if leverage.n_cooks_above_threshold > 0:
        notes.append(
            f"{leverage.n_cooks_above_threshold} observation(s) exceed the "
            "conventional Cook's distance threshold of 4/n."
        )

    return InfluenceReport(
        leverage=leverage,
        drop_path=drop_path,
        winsorised_beta=winsorised.beta,
        winsorised_p=winsorised.p_wild_bootstrap,
        continuous_beta=continuous_beta,
        rank_beta=rank_beta,
        rank_correlation=correlation,
        baseline_beta=baseline.beta,
        baseline_p=baseline.p_wild_bootstrap,
        notes=tuple(notes),
    )
