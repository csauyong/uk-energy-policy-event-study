r"""Dose-response estimator: do firms move in proportion to policy exposure.

The question this design asks is "did the announcement move firms *in
proportion to their exposure*?", replacing "did it move the treated firms?".

The estimand
------------
Stacked across events, one row per firm x event:

.. math:: CAR_{ie} = \alpha_e + \beta\,\text{Exposure}_{ie}
                     + \gamma' \text{Controls}_{ie} + \varepsilon_{ie}

:math:`\beta` is the estimand and :math:`H_0: \beta = 0` is the test.

Why this identifies where the SC design could not
-------------------------------------------------
The synthetic-control design asked "did the announcement move the treated
firms?" and identified from a handful of treated units against a donor pool of
23. `reports/event_study.md` §3 showed that floors the attainable p-value at
0.042 and puts the 20-day MDE at 12-24% cumulative abnormal return -- larger
than any plausible policy effect.

This design asks a different question: "did it move firms *in proportion to
their exposure*?" Identification then comes from cross-sectional variation in
exposure across several hundred listed firms, which is abundant, rather than
from a handful of treated units, which is not. Three consequences follow:

* **Zero-exposure firms become informative.** They are not discarded as
  irrelevant; they pin down :math:`\alpha_e`, which is what absorbs the common
  market move on the announcement date. In the SC design they were donors at
  best and noise at worst.
* **Common shocks are absorbed by construction.** A macro release on the
  announcement day hits high- and low-exposure firms alike and lands entirely
  in :math:`\alpha_e`. It biases :math:`\beta` only if it is *correlated with
  exposure*, which is a far weaker requirement than the SC design's.
* **Power scales with the cross-section**, not with the number of treated
  units. See :func:`dose_response_mde`.

What this design does *not* buy
-------------------------------
It does not rescue a confounded event. A same-day announcement that happens to
hit exactly the exposed firms -- a construction-sector shock landing on a
housing-policy day -- is correlated with exposure and biases :math:`\beta`
directly. Event fixed effects absorb the common component, not the
exposure-correlated one. Confounded events remain confounded and are still
reported separately.

Inference
---------
Three procedures, reported together because they disagree informatively.

``cluster_event``
    Standard errors clustered by event. The natural cluster: firms share an
    announcement date, so their residuals are correlated within it.
``wild_cluster_bootstrap``
    Rademacher wild cluster bootstrap on the restricted (null-imposed) model.
    With few clusters -- and the event count here will be single digits -- the
    cluster-robust asymptotics fail badly and over-reject. This is the honest
    test and it is the headline.
``randomisation``
    Permutes the exposure vector *within each event*, holding returns fixed.
    This is the sharper null: it asks whether the observed exposure-return
    gradient is unusual against the distribution of gradients obtainable by
    reassigning exposure among the same firms on the same day. It conditions
    on the realised returns entirely, so no distributional assumption enters.
"""

from __future__ import annotations

import enum
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Final, TypeAlias, cast

import numpy as np
import pandas as pd
from scipy import stats

#: Controls required unless the caller explicitly overrides. `size` and
#: `book_to_market` guard against beta picking up a value or size tilt;
#: `momentum` against a trend; `pre_event_vol` against exposure proxying for
#: riskiness, which for small-cap building-products names it plausibly would.
#: Dense float array. Named so the casts around numpy's untyped linalg
#: functions say what they mean.
FloatArray: TypeAlias = "np.ndarray[Any, np.dtype[np.float64]]"

DEFAULT_CONTROLS: Final[tuple[str, ...]] = (
    "size",
    "book_to_market",
    "momentum",
    "pre_event_vol",
)


@dataclass(frozen=True)
class DoseResponseResult:
    """Estimated exposure gradient, with three inference procedures."""

    beta: float
    se_cluster: float
    t_cluster: float
    p_cluster: float
    p_wild_bootstrap: float
    p_randomisation: float
    weight_scheme: WeightScheme
    p_floor_bootstrap: float
    n_observations: int
    n_events: int
    n_firms: int
    exposure_column: str
    controls: tuple[str, ...]
    coefficients: pd.Series
    residual_sd: float
    exposure_sd: float
    r_squared: float
    bootstrap_draws: int = 0
    randomisation_draws: int = 0
    notes: tuple[str, ...] = ()

    @property
    def headline_p(self) -> float:
        """The wild cluster bootstrap p-value.

        Chosen as headline because the event count is small: cluster-robust
        asymptotics need many clusters and over-reject with few, so the
        clustered p-value is reported for comparison rather than for belief.
        """
        return self.p_wild_bootstrap

    def detectable_at(self, alpha: float = 0.05) -> bool:
        """Whether this design can reach `alpha` at all.

        False when the bootstrap's p-value floor exceeds the level being
        claimed -- in which case no data can produce a rejection and the
        p-value beside it is uninformative about significance.
        """
        return self.p_floor_bootstrap <= alpha

    @property
    def at_the_floor(self) -> bool:
        """True when the p-value is pinned at the design's floor.

        A p-value sitting exactly on the floor is not evidence of a very small
        p-value; it is evidence that the design ran out of resolution.
        """
        return bool(
            np.isfinite(self.p_wild_bootstrap)
            and self.p_wild_bootstrap <= self.p_floor_bootstrap * 1.0001
        )

    def summary(self) -> pd.Series:
        """One-line summary for a report table."""
        return pd.Series(
            {
                "beta": self.beta,
                "se_cluster": self.se_cluster,
                "p_cluster": self.p_cluster,
                "p_wild_bootstrap": self.p_wild_bootstrap,
                "p_floor_bootstrap": self.p_floor_bootstrap,
                "weight_scheme": str(self.weight_scheme),
                "p_randomisation": self.p_randomisation,
                "n_obs": self.n_observations,
                "n_events": self.n_events,
                "n_firms": self.n_firms,
                "exposure": self.exposure_column,
                "r_squared": self.r_squared,
            }
        )


def _design_matrix(
    frame: pd.DataFrame, exposure_column: str, controls: Sequence[str]
) -> tuple[np.ndarray, list[str], np.ndarray]:
    """Build [exposure | controls | event dummies] and the cluster index.

    Event fixed effects enter as explicit dummies, so the design is full rank
    and `alpha_e` is recoverable for the report rather than partialled out
    invisibly.

    **Fixed effects and clusters are deliberately at different levels.** The
    dummies are per *event*, because each announcement date has its own common
    market move to absorb. Clustering is per *group* when a `cluster_id` column
    is present, because events closer together than the spacing threshold share
    return days and are not independent draws
    (`docs/event_curation_protocol.md` Step 6). Collapsing the fixed effects to
    the group level instead would leave one date's shock partly in the
    residual; clustering at the event level instead would overstate the number
    of independent clusters and, through that, lower the bootstrap's p-value
    floor exactly when dependence should raise it.
    """
    exposure = frame[exposure_column].to_numpy(dtype=float).reshape(-1, 1)
    names = [exposure_column]

    blocks = [exposure]
    for control in controls:
        blocks.append(frame[control].to_numpy(dtype=float).reshape(-1, 1))
        names.append(control)

    events = pd.Categorical(frame["event_id"])
    dummies = pd.get_dummies(events, drop_first=False).to_numpy(dtype=float)
    blocks.append(dummies)
    names.extend(f"event[{code}]" for code in events.categories)

    cluster_source = "cluster_id" if "cluster_id" in frame.columns else "event_id"
    clusters = pd.Categorical(frame[cluster_source]).codes.astype(int)

    return np.hstack(blocks), names, clusters


def _ols(design: np.ndarray, response: np.ndarray) -> np.ndarray:
    """Least squares via lstsq, tolerant of the rank deficiency dummies cause."""
    solution, *_ = np.linalg.lstsq(design, response, rcond=None)
    # numpy's stubs type lstsq's result as Any, which `warn_return_any` rejects.
    # Casting is the narrowest fix and does not change behaviour.
    return cast("FloatArray", np.asarray(solution, dtype=float))


def _cluster_vcov(
    design: np.ndarray, residuals: np.ndarray, clusters: np.ndarray
) -> np.ndarray:
    """Cluster-robust sandwich covariance, with the standard finite-sample scaling."""
    n_obs, n_params = design.shape
    gram_inv = np.linalg.pinv(design.T @ design)

    meat = np.zeros((n_params, n_params))
    unique = np.unique(clusters)
    for cluster in unique:
        mask = clusters == cluster
        scores = design[mask].T @ residuals[mask]
        meat += np.outer(scores, scores)

    n_clusters = len(unique)
    correction = (n_clusters / max(n_clusters - 1, 1)) * (
        (n_obs - 1) / max(n_obs - n_params, 1)
    )
    return cast("FloatArray", correction * gram_inv @ meat @ gram_inv)


class WeightScheme(enum.StrEnum):
    r"""Auxiliary weight distribution for the wild cluster bootstrap.

    The choice is not cosmetic: it sets a hard floor on the attainable
    p-value, and with few clusters that floor can exceed the significance
    level being claimed.

    ``RADEMACHER``
        Two-point, :math:`\pm 1`. Only :math:`2^G` distinct weight vectors
        exist, so with 6 clusters the smallest attainable p-value is 0.031 --
        the same defect as the permutation design's 1/(J+1) floor, arriving
        through a different mechanism.
    ``WEBB``
        Webb's six-point distribution,
        :math:`\pm\sqrt{3/2}, \pm 1, \pm\sqrt{1/2}`, each with probability
        1/6. Mean zero and unit variance like Rademacher, but :math:`6^G`
        distinct vectors: at 6 clusters the floor drops from 0.031 to
        0.000043. The standard recommendation below roughly 12 clusters.
    """

    RADEMACHER = "rademacher"
    WEBB = "webb"

    @property
    def support(self) -> FloatArray:
        """Support points. Both have mean zero and unit variance."""
        if self is WeightScheme.RADEMACHER:
            return cast("FloatArray", np.array([-1.0, 1.0]))
        root_high = float(np.sqrt(1.5))
        root_low = float(np.sqrt(0.5))
        return cast(
            "FloatArray",
            np.array([-root_high, -1.0, -root_low, root_low, 1.0, root_high]),
        )

    @property
    def n_support(self) -> int:
        """Number of support points."""
        return int(self.support.size)


def bootstrap_p_floor(scheme: WeightScheme, n_clusters: int, n_draws: int) -> float:
    r"""Smallest p-value this bootstrap can produce, whatever the data.

    Two things bound it, and the binding one is whichever is larger.

    **Discreteness of the weight distribution.** With :math:`G` clusters and
    :math:`S` support points there are only :math:`S^G` distinct weight
    vectors. The two-sided statistic is symmetric under a global sign flip --
    :math:`w` and :math:`-w` give the same :math:`|t^*|` -- so attainable
    p-values come in steps of :math:`2/S^G`, **not** :math:`1/S^G`. The
    familiar result that Rademacher at :math:`G=5` cannot go below 6.25% is
    exactly :math:`2/2^5`.

    **Resolution of the draws.** Under the ``(1 + count)/(B + 1)`` convention
    used here -- matching the permutation p-values elsewhere in this project,
    so no result is ever exactly zero -- the floor is :math:`1/(B+1)`.

    Returns
    -------
    float
        The larger of the two. Carried as a field on
        :class:`DoseResponseResult` rather than described in prose, so a
        design that cannot reach the level being claimed is visible at the
        call site.
    """
    log_enumeration = float(np.log(2.0) - n_clusters * np.log(scheme.n_support))
    enumeration_floor = (
        float(np.exp(log_enumeration)) if log_enumeration > -700 else 0.0
    )
    draw_floor = 1.0 / (n_draws + 1.0)
    return max(min(enumeration_floor, 1.0), draw_floor)


def wild_cluster_bootstrap(
    design: FloatArray,
    response: FloatArray,
    clusters: FloatArray,
    *,
    coefficient_index: int,
    scheme: WeightScheme,
    seed: int,
    n_draws: int = 2000,
) -> float:
    """Wild cluster bootstrap p-value for one coefficient.

    Imposes the null by refitting without the coefficient of interest, then
    resamples the restricted residuals with a cluster-level auxiliary weight.
    Imposing the null is what makes this work with few clusters -- the
    unrestricted variant under-rejects badly.

    Parameters
    ----------
    scheme
        Required, with no default. The weight distribution sets the floor on
        the attainable p-value (see :func:`bootstrap_p_floor`), which is a
        design property the caller must choose deliberately rather than
        inherit silently.

    Notes
    -----
    Uses the ``(1 + count)/(B + 1)`` convention, so the p-value is never
    exactly zero. Deterministic given `seed`, per `CLAUDE.md` §7.
    """
    n_obs, n_params = design.shape
    keep = [index for index in range(n_params) if index != coefficient_index]
    restricted = design[:, keep]

    restricted_beta = _ols(restricted, response)
    restricted_fitted = restricted @ restricted_beta
    restricted_residuals = response - restricted_fitted

    full_beta = _ols(design, response)
    full_residuals = response - design @ full_beta
    observed_vcov = _cluster_vcov(design, full_residuals, clusters)
    observed_se = float(
        np.sqrt(max(observed_vcov[coefficient_index, coefficient_index], 0.0))
    )
    if observed_se <= 0:
        return float("nan")
    observed_t = float(full_beta[coefficient_index] / observed_se)

    rng = np.random.default_rng(seed)
    unique = np.unique(clusters)
    support = scheme.support
    draws = np.empty(n_draws, dtype=float)

    for draw in range(n_draws):
        weights = rng.choice(support, size=len(unique))
        weight_by_obs = np.empty(n_obs, dtype=float)
        for position, cluster in enumerate(unique):
            weight_by_obs[clusters == cluster] = weights[position]

        synthetic = restricted_fitted + restricted_residuals * weight_by_obs
        boot_beta = _ols(design, synthetic)
        boot_residuals = synthetic - design @ boot_beta
        boot_vcov = _cluster_vcov(design, boot_residuals, clusters)
        boot_se = float(
            np.sqrt(max(boot_vcov[coefficient_index, coefficient_index], 0.0))
        )
        draws[draw] = boot_beta[coefficient_index] / boot_se if boot_se > 0 else np.nan

    finite = draws[np.isfinite(draws)]
    if finite.size == 0:
        return float("nan")
    extreme = int((np.abs(finite) >= abs(observed_t)).sum())
    return float((1.0 + extreme) / (finite.size + 1.0))


def randomisation_test(
    frame: pd.DataFrame,
    exposure_column: str,
    controls: Sequence[str],
    *,
    seed: int,
    n_draws: int = 2000,
) -> float:
    """Permute exposure within each event, holding returns fixed.

    The sharper null for this design. It asks whether the observed
    exposure-return gradient is unusual against the distribution of gradients
    obtainable by reassigning the *same* exposure values among the *same*
    firms on the *same* day. Returns are never resampled, so no distributional
    assumption about them enters, and the common market move on each date is
    held fixed by construction.

    Permutation is **within** event. Permuting across events would break the
    event fixed effects and test a different, weaker null.
    """
    design, names, _ = _design_matrix(frame, exposure_column, controls)
    index = names.index(exposure_column)
    response = frame["car"].to_numpy(dtype=float)
    observed = float(_ols(design, response)[index])

    rng = np.random.default_rng(seed)
    draws = np.empty(n_draws, dtype=float)
    working = frame.copy()

    for draw in range(n_draws):
        permuted = working.groupby("event_id", group_keys=False)[
            exposure_column
        ].transform(
            lambda values: pd.Series(
                rng.permutation(values.to_numpy()), index=values.index
            )
        )
        working[exposure_column] = permuted
        permuted_design, _, _ = _design_matrix(working, exposure_column, controls)
        draws[draw] = float(_ols(permuted_design, response)[index])

    return float((np.abs(draws) >= abs(observed)).mean())


def estimate_dose_response(
    frame: pd.DataFrame,
    *,
    scheme: WeightScheme,
    exposure_column: str = "exposure_continuous",
    controls: Sequence[str] = DEFAULT_CONTROLS,
    seed: int = 20260815,
    bootstrap_draws: int = 2000,
    randomisation_draws: int = 2000,
) -> DoseResponseResult:
    """Fit the stacked dose-response regression with all three inference procedures.

    Parameters
    ----------
    frame
        One row per firm x event, with columns `unit_id`, `event_id`, `car`,
        the exposure column, and every control.
    scheme
        Wild bootstrap weight distribution. **Required, no default.** It fixes
        the floor on the attainable p-value, which with few clusters can
        exceed the level being tested -- `WeightScheme.WEBB` is the right
        choice below roughly 12 clusters and `RADEMACHER` is retained for
        comparison. See :func:`bootstrap_p_floor`.
    exposure_column
        `exposure_continuous` (standardised) or `exposure_rank` (decile). Both
        are pre-registered in `config/exposure.yaml`; disagreement between
        them means the scoring function's functional form is doing the work.

    Raises
    ------
    ValueError
        If a required column is absent, or if exposure has no within-event
        variation -- in which case beta is not identified and a fitted number
        would be an artefact of collinearity with the event dummies.
    """
    required = {"unit_id", "event_id", "car", exposure_column, *controls}
    missing = sorted(required - set(frame.columns))
    if missing:
        msg = f"dose-response frame is missing columns {missing}"
        raise ValueError(msg)

    working = frame.dropna(subset=list(required)).copy()
    if working.empty:
        msg = "no complete observations after dropping missing values"
        raise ValueError(msg)

    within_event_sd = working.groupby("event_id")[exposure_column].std(ddof=1)
    if float(within_event_sd.fillna(0.0).max()) <= 0:
        msg = (
            f"{exposure_column!r} has no within-event variation, so beta is "
            "collinear with the event fixed effects and is not identified. "
            "This is a design failure, not a numerical one: with no dispersion "
            "in exposure there is nothing for a dose-response test to detect"
        )
        raise ValueError(msg)

    design, names, clusters = _design_matrix(working, exposure_column, controls)
    response = working["car"].to_numpy(dtype=float)
    index = names.index(exposure_column)

    beta_vector = _ols(design, response)
    residuals = response - design @ beta_vector
    vcov = _cluster_vcov(design, residuals, clusters)
    se = float(np.sqrt(max(vcov[index, index], 0.0)))
    beta = float(beta_vector[index])
    t_stat = beta / se if se > 0 else float("nan")

    # Clusters, which are event *groups* when the panel carries `cluster_id`.
    # This is what the p-value floor is computed from -- see events/grouping.py.
    n_events = len(np.unique(clusters))
    n_distinct_events = int(working["event_id"].nunique())
    p_cluster = (
        float(2.0 * stats.t.sf(abs(t_stat), df=max(n_events - 1, 1)))
        if np.isfinite(t_stat)
        else float("nan")
    )

    p_wild = wild_cluster_bootstrap(
        design,
        response,
        clusters,
        coefficient_index=index,
        scheme=scheme,
        seed=seed,
        n_draws=bootstrap_draws,
    )
    p_floor = bootstrap_p_floor(scheme, n_events, bootstrap_draws)
    p_random = randomisation_test(
        working, exposure_column, controls, seed=seed, n_draws=randomisation_draws
    )

    total_ss = float(np.sum((response - response.mean()) ** 2))
    r_squared = 1.0 - float(residuals @ residuals) / total_ss if total_ss > 0 else 0.0

    notes: list[str] = []
    if "cluster_id" not in working.columns:
        notes.append(
            "NO GROUPING APPLIED: the panel carries no `cluster_id`, so each event "
            "is treated as an independent cluster. If any two announcements are "
            "closer than the spacing threshold they share return days, and the "
            "p-value floor below is optimistic. See events/grouping.py."
        )
    elif n_events < n_distinct_events:
        notes.append(
            f"GROUPED: {n_distinct_events} events collapse to {n_events} "
            "independent clusters. Event fixed effects remain per event; "
            "clustering and the p-value floor use the group count."
        )
    if n_events < 12:
        notes.append(
            f"{n_events} clusters: cluster-robust asymptotics are unreliable "
            "below roughly 30 and over-reject. The wild cluster bootstrap "
            "p-value is the headline; p_cluster is shown for comparison only."
        )
    if scheme is WeightScheme.RADEMACHER and n_events < 12:
        notes.append(
            f"RADEMACHER weights with {n_events} clusters floor the p-value at "
            f"{p_floor:.4f}. WEBB weights lower that floor to "
            f"{bootstrap_p_floor(WeightScheme.WEBB, n_events, bootstrap_draws):.6f} "
            "and are the standard recommendation below roughly 12 clusters."
        )
    if p_floor > 0.05:
        notes.append(
            f"p-value floor {p_floor:.4f} exceeds 0.05: this design cannot "
            "reject at the 5% level for any effect size. The bootstrap p-value "
            "beside it is uninformative about significance."
        )

    return DoseResponseResult(
        beta=beta,
        se_cluster=se,
        t_cluster=t_stat,
        p_cluster=p_cluster,
        p_wild_bootstrap=p_wild,
        p_randomisation=p_random,
        weight_scheme=scheme,
        p_floor_bootstrap=p_floor,
        n_observations=len(working),
        n_events=n_events,
        n_firms=int(working["unit_id"].nunique()),
        exposure_column=exposure_column,
        controls=tuple(controls),
        coefficients=pd.Series(beta_vector, index=names),
        residual_sd=float(np.std(residuals, ddof=1)),
        exposure_sd=float(working[exposure_column].std(ddof=1)),
        r_squared=r_squared,
        bootstrap_draws=bootstrap_draws,
        randomisation_draws=randomisation_draws,
        notes=tuple(notes),
    )


# --------------------------------------------------------------------------
# power
# --------------------------------------------------------------------------


def effective_observations(
    residual_sd: float, exposure_sd: float, se_beta: float
) -> float:
    r"""Effective independent observations implied by a standard error.

    Inverting :math:`se(\beta) = \sigma_\varepsilon / (\sigma_x \sqrt{N})`
    gives :math:`N_{\text{eff}} = (\sigma_\varepsilon / (\sigma_x\,
    se(\beta)))^2`. Feeding in the *cluster-robust* standard error makes
    :math:`N_{\text{eff}}` the sample size an independent-observations design
    would have needed to achieve the same precision -- which is exactly the
    quantity `CLAUDE.md` §3 asks be reported instead of the row count.

    Derived from the fitted dependence structure rather than from an assumed
    intraclass correlation. That matters here: **the obvious design-effect
    route does not work in this model.** Event fixed effects demean the
    residuals within each date, so the average pairwise residual correlation
    across firms is mechanically about :math:`-1/(n-1)`, not positive, and a
    haircut computed from it would be meaningless. The dependence that
    actually inflates :math:`se(\beta)` is the part correlated *with
    exposure*, and the cluster-robust sandwich already measures precisely
    that.
    """
    if exposure_sd <= 0 or se_beta <= 0 or not np.isfinite(se_beta):
        return float("nan")
    return float((residual_sd / (exposure_sd * se_beta)) ** 2)


@dataclass(frozen=True)
class DoseResponseMDE:
    """Minimum detectable exposure gradient for this design.

    Reported **above** the estimates, as `reports/event_study.md` §3 was, and
    for the same reason: a null means nothing until the reader knows what the
    design could have found.
    """

    alpha: float
    target_power: float
    n_observations: int
    n_events: int
    residual_sd: float
    exposure_sd: float
    se_beta: float
    mde: float
    design_effect: float
    effective_n: float
    interpretation: str = ""

    def summary(self) -> pd.Series:
        """One-line summary for a report table."""
        return pd.Series(
            {
                "n_obs": self.n_observations,
                "n_events": self.n_events,
                "effective_n": self.effective_n,
                "design_effect": self.design_effect,
                "residual_sd": self.residual_sd,
                "exposure_sd": self.exposure_sd,
                "se_beta": self.se_beta,
                f"mde_at_{int(self.target_power * 100)}pct": self.mde,
            }
        )


def dose_response_mde(
    frame: pd.DataFrame,
    *,
    exposure_column: str = "exposure_continuous",
    controls: Sequence[str] = DEFAULT_CONTROLS,
    alpha: float = 0.05,
    target_power: float = 0.80,
    se_inflation: float = 1.0,
) -> DoseResponseMDE:
    r"""Minimum detectable exposure gradient, computed on the actual design.

    .. math:: \text{MDE} = (z_{1-\alpha/2} + z_{\pi})\, se(\beta)

    with :math:`se(\beta)` the **cluster-robust** standard error from the
    fitted model. Using the clustered SE rather than a design-effect haircut on
    an assumed intraclass correlation is deliberate, and the reason is not
    cosmetic:

    Event fixed effects demean residuals within each date, so the average
    pairwise residual correlation across firms is mechanically about
    :math:`-1/(n-1)` rather than positive. An intraclass correlation read off
    the event-level variance share collapses to zero, and an MDE built on it
    comes out roughly five times too optimistic -- silently, with a plausible
    looking number. The dependence that genuinely inflates :math:`se(\beta)` is
    the component correlated with exposure, which is exactly what the
    cluster-robust sandwich measures.

    `CLAUDE.md` §3's effective-observation count is then *derived* from that
    standard error by :func:`effective_observations`, rather than assumed.

    Parameters
    ----------
    se_inflation
        Multiplier on the clustered standard error, for a deliberately
        conservative reading. With single-digit event counts the clustered SE
        is itself downward-biased -- the same small-cluster problem that makes
        the wild bootstrap the headline test -- so a value above 1 is a
        defensible sensitivity and should be reported as one rather than
        applied silently.
    """
    required = {"unit_id", "event_id", "car", exposure_column, *controls}
    missing = sorted(required - set(frame.columns))
    if missing:
        msg = f"frame is missing columns {missing}"
        raise ValueError(msg)

    working = frame.dropna(subset=list(required)).copy()
    design, names, clusters = _design_matrix(working, exposure_column, controls)
    response = working["car"].to_numpy(dtype=float)
    index = names.index(exposure_column)

    beta_vector = _ols(design, response)
    residuals = response - design @ beta_vector
    vcov = _cluster_vcov(design, residuals, clusters)

    residual_sd = float(np.std(residuals, ddof=1))
    exposure_sd = float(working[exposure_column].std(ddof=1))
    n_obs = len(working)
    n_events = len(np.unique(clusters))

    se_beta = se_inflation * float(np.sqrt(max(vcov[index, index], 0.0)))
    critical = float(stats.norm.ppf(1.0 - alpha / 2.0))
    power_z = float(stats.norm.ppf(target_power))
    mde = (critical + power_z) * se_beta

    effective_n = effective_observations(residual_sd, exposure_sd, se_beta)
    design_effect = (
        n_obs / effective_n
        if effective_n and np.isfinite(effective_n)
        else float("nan")
    )

    interpretation = (
        f"A one-standard-deviation increase in exposure must move the "
        f"cumulative abnormal return by at least {mde:.2%} to be detected "
        f"{target_power:.0%} of the time at the {alpha:.0%} level. "
        f"{n_obs} rows across {n_events} events carry the precision of "
        f"{effective_n:.0f} independent observations "
        f"(design effect {design_effect:.1f}), derived from the cluster-robust "
        f"standard error rather than from an assumed correlation."
    )

    return DoseResponseMDE(
        alpha=alpha,
        target_power=target_power,
        n_observations=n_obs,
        n_events=n_events,
        residual_sd=residual_sd,
        exposure_sd=exposure_sd,
        se_beta=se_beta,
        mde=mde,
        design_effect=design_effect,
        effective_n=effective_n,
        interpretation=interpretation,
    )


@dataclass(frozen=True)
class PlaceboDateResult:
    """Beta distribution on matched non-event dates."""

    observed_beta: float
    placebo_betas: pd.Series
    p_value: float
    n_dates: int
    matched_on: tuple[str, ...] = field(default=("day_of_week", "volatility_regime"))

    def summary(self) -> pd.Series:
        """One-line summary for a report table."""
        return pd.Series(
            {
                "observed_beta": self.observed_beta,
                "placebo_mean": float(self.placebo_betas.mean()),
                "placebo_sd": float(self.placebo_betas.std(ddof=1))
                if self.n_dates > 1
                else float("nan"),
                "p_placebo_dates": self.p_value,
                "n_placebo_dates": self.n_dates,
            }
        )
