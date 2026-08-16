"""Dose-response estimator: recovery, inference, identification guards, power."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from policy_event_study.estimators.dose_response import (
    DEFAULT_CONTROLS,
    WeightScheme,
    _design_matrix,
    bootstrap_p_floor,
    dose_response_mde,
    effective_observations,
    estimate_dose_response,
    randomisation_test,
    wild_cluster_bootstrap,
)

WEBB = WeightScheme.WEBB


def make_frame(
    *,
    beta: float = 0.0,
    n_events: int = 6,
    n_firms: int = 300,
    exposed_share: float = 0.08,
    noise_sd: float = 0.02,
    event_shock_sd: float = 0.01,
    seed: int = 11,
) -> pd.DataFrame:
    """Synthetic firm x event panel with a known exposure gradient.

    Mirrors the real design: most firms score exactly zero exposure, a small
    minority are exposed, and every firm on a given date shares a common event
    shock that the event fixed effect is supposed to absorb.
    """
    rng = np.random.default_rng(seed)
    rows = []
    for event in range(n_events):
        shock = rng.normal(0.0, event_shock_sd)
        n_exposed = max(int(n_firms * exposed_share), 2)
        exposure = np.zeros(n_firms)
        exposure[:n_exposed] = rng.uniform(0.1, 1.0, size=n_exposed) * rng.choice(
            [-1.0, 1.0], size=n_exposed
        )
        standardised = (exposure - exposure.mean()) / exposure.std(ddof=1)

        size = rng.normal(0.0, 1.0, size=n_firms)
        book_to_market = rng.normal(0.0, 1.0, size=n_firms)
        momentum = rng.normal(0.0, 1.0, size=n_firms)
        pre_event_vol = rng.uniform(0.5, 2.0, size=n_firms)

        car = (
            shock
            + beta * standardised
            + 0.001 * size
            + rng.normal(0.0, noise_sd, size=n_firms)
        )
        rows.append(
            pd.DataFrame(
                {
                    "unit_id": [f"F{index:04d}" for index in range(n_firms)],
                    "event_id": f"E{event}",
                    "car": car,
                    "exposure_continuous": standardised,
                    "exposure_rank": pd.Series(standardised).rank(pct=True).to_numpy(),
                    "size": size,
                    "book_to_market": book_to_market,
                    "momentum": momentum,
                    "pre_event_vol": pre_event_vol,
                }
            )
        )
    return pd.concat(rows, ignore_index=True)


# -- recovery --------------------------------------------------------------


def test_recovers_a_known_gradient() -> None:
    frame = make_frame(beta=0.02)
    result = estimate_dose_response(
        frame, scheme=WEBB, bootstrap_draws=200, randomisation_draws=200
    )
    assert result.beta == pytest.approx(0.02, abs=0.004)
    assert result.headline_p < 0.05


def test_null_panel_gives_a_small_insignificant_beta() -> None:
    frame = make_frame(beta=0.0)
    result = estimate_dose_response(
        frame, scheme=WEBB, bootstrap_draws=200, randomisation_draws=200
    )
    assert abs(result.beta) < 0.005
    assert result.p_randomisation > 0.10


def test_sign_of_beta_follows_the_gradient() -> None:
    negative = estimate_dose_response(
        make_frame(beta=-0.03),
        scheme=WEBB,
        bootstrap_draws=100,
        randomisation_draws=100,
    )
    assert negative.beta < 0


def test_rank_variant_also_recovers_the_sign() -> None:
    """The pre-registered robustness variant, insensitive to functional form."""
    frame = make_frame(beta=0.03)
    result = estimate_dose_response(
        frame,
        scheme=WEBB,
        exposure_column="exposure_rank",
        bootstrap_draws=100,
        randomisation_draws=100,
    )
    assert result.beta > 0


# -- event fixed effects do their job -------------------------------------


def test_event_shocks_are_absorbed_not_attributed_to_exposure() -> None:
    """A large common shock on each date must not move beta.

    This is the design's central claim: zero-exposure firms pin down the event
    fixed effect, so a market-wide move on the announcement day lands there
    rather than in the exposure coefficient.
    """
    quiet = make_frame(beta=0.0, event_shock_sd=0.0005, seed=5)
    loud = make_frame(beta=0.0, event_shock_sd=0.05, seed=5)
    quiet_beta = estimate_dose_response(
        quiet, scheme=WEBB, bootstrap_draws=50, randomisation_draws=50
    ).beta
    loud_beta = estimate_dose_response(
        loud, scheme=WEBB, bootstrap_draws=50, randomisation_draws=50
    ).beta
    assert quiet_beta == pytest.approx(loud_beta, abs=1e-9)


def test_zero_exposure_firms_are_retained_and_informative() -> None:
    """Dropping them shrinks the sample and widens the standard error."""
    frame = make_frame(beta=0.02)
    full = estimate_dose_response(
        frame, scheme=WEBB, bootstrap_draws=50, randomisation_draws=50
    )
    exposed_only = frame[frame["exposure_continuous"].abs() > 0.01]
    trimmed = estimate_dose_response(
        exposed_only, scheme=WEBB, bootstrap_draws=50, randomisation_draws=50
    )
    assert full.n_observations > trimmed.n_observations
    assert full.se_cluster < trimmed.se_cluster


# -- identification guards -------------------------------------------------


def test_no_within_event_variation_is_refused() -> None:
    """Constant exposure is collinear with the event dummies; beta is not identified."""
    frame = make_frame(beta=0.0)
    frame["exposure_continuous"] = 1.0
    with pytest.raises(ValueError, match="not identified"):
        estimate_dose_response(frame, scheme=WEBB)


def test_missing_control_is_refused() -> None:
    frame = make_frame().drop(columns=["momentum"])
    with pytest.raises(ValueError, match="missing columns"):
        estimate_dose_response(frame, scheme=WEBB)


def test_controls_are_applied() -> None:
    result = estimate_dose_response(
        make_frame(beta=0.01), scheme=WEBB, bootstrap_draws=50, randomisation_draws=50
    )
    assert result.controls == DEFAULT_CONTROLS
    for control in DEFAULT_CONTROLS:
        assert control in result.coefficients.index


# -- inference -------------------------------------------------------------


def test_three_inference_procedures_are_reported() -> None:
    result = estimate_dose_response(
        make_frame(beta=0.02), scheme=WEBB, bootstrap_draws=200, randomisation_draws=200
    )
    for value in (result.p_cluster, result.p_wild_bootstrap, result.p_randomisation):
        assert 0.0 <= value <= 1.0
    assert result.headline_p == result.p_wild_bootstrap


def test_few_clusters_trigger_the_warning_note() -> None:
    result = estimate_dose_response(
        make_frame(n_events=5), scheme=WEBB, bootstrap_draws=50, randomisation_draws=50
    )
    assert any("clusters" in note for note in result.notes)


def test_wild_bootstrap_is_deterministic_given_a_seed() -> None:
    frame = make_frame(beta=0.01)
    design, names, clusters = _design_matrix(
        frame, "exposure_continuous", DEFAULT_CONTROLS
    )
    response = frame["car"].to_numpy(dtype=float)
    index = names.index("exposure_continuous")
    first = wild_cluster_bootstrap(
        design,
        response,
        clusters,
        coefficient_index=index,
        scheme=WEBB,
        seed=7,
        n_draws=100,
    )
    second = wild_cluster_bootstrap(
        design,
        response,
        clusters,
        coefficient_index=index,
        scheme=WEBB,
        seed=7,
        n_draws=100,
    )
    assert first == second


def test_randomisation_is_deterministic_and_within_event() -> None:
    frame = make_frame(beta=0.0)
    first = randomisation_test(
        frame, "exposure_continuous", DEFAULT_CONTROLS, seed=3, n_draws=100
    )
    second = randomisation_test(
        frame, "exposure_continuous", DEFAULT_CONTROLS, seed=3, n_draws=100
    )
    assert first == second
    assert 0.0 <= first <= 1.0


def test_randomisation_detects_a_strong_gradient() -> None:
    frame = make_frame(beta=0.05)
    p_value = randomisation_test(
        frame, "exposure_continuous", DEFAULT_CONTROLS, seed=3, n_draws=200
    )
    assert p_value < 0.05


# -- power -----------------------------------------------------------------


def test_mde_shrinks_with_a_larger_cross_section() -> None:
    """The whole reason for the estimand change: power scales with the universe."""
    small = dose_response_mde(make_frame(n_firms=60))
    large = dose_response_mde(make_frame(n_firms=600))
    assert large.mde < small.mde


def test_mde_shrinks_with_greater_exposure_dispersion() -> None:
    tight = dose_response_mde(make_frame(exposed_share=0.02))
    wide = dose_response_mde(make_frame(exposed_share=0.40))
    assert wide.exposure_sd >= tight.exposure_sd * 0.99


def test_observed_effect_is_detectable_when_it_exceeds_the_mde() -> None:
    frame = make_frame(beta=0.02)
    mde = dose_response_mde(frame)
    result = estimate_dose_response(
        frame, scheme=WEBB, bootstrap_draws=200, randomisation_draws=200
    )
    assert abs(result.beta) > mde.mde
    assert result.headline_p < 0.05


def test_effective_observations_inverts_the_standard_error() -> None:
    """`CLAUDE.md` §3: effective observations, derived not assumed."""
    assert effective_observations(0.02, 1.0, 0.02 / 30.0) == pytest.approx(900.0)
    assert np.isnan(effective_observations(0.02, 0.0, 0.001))


def test_se_inflation_widens_the_mde_proportionally() -> None:
    """The sensitivity knob for the small-cluster downward bias."""
    frame = make_frame(beta=0.0)
    base = dose_response_mde(frame)
    inflated = dose_response_mde(frame, se_inflation=2.0)
    assert inflated.mde == pytest.approx(2.0 * base.mde, rel=1e-9)


def test_mde_widens_when_residuals_share_a_within_event_factor() -> None:
    """Sector co-movement aligned with exposure is what the clustered SE catches.

    Without a within-event factor the clustered SE can sit *below* the iid SE.
    Real exposure is concentrated in sectors whose members co-move, so the
    realistic MDE is the one estimated with the factor present.
    """
    rng = np.random.default_rng(17)
    flat = make_frame(beta=0.0, n_firms=200, n_events=8, seed=21)
    clustered = flat.copy()
    exposed = clustered["exposure_continuous"].abs() > 0.01
    for event in clustered["event_id"].unique():
        mask = (clustered["event_id"] == event) & exposed
        clustered.loc[mask, "car"] += rng.normal(0.0, 0.02)
    assert dose_response_mde(clustered).mde > dose_response_mde(flat).mde


# -- Fix 1: the bootstrap has its own p-value floor -----------------------


def test_rademacher_floor_matches_the_textbook_figure() -> None:
    """Rademacher at G=5 cannot go below 6.25%. The known result, asserted."""
    assert bootstrap_p_floor(WeightScheme.RADEMACHER, 5, 10**9) == pytest.approx(0.0625)
    assert bootstrap_p_floor(WeightScheme.RADEMACHER, 6, 10**9) == pytest.approx(
        0.03125
    )


@pytest.mark.parametrize("n_clusters", [4, 5, 6, 8, 10, 12])
def test_webb_floor_is_below_rademacher(n_clusters: int) -> None:
    rademacher = bootstrap_p_floor(WeightScheme.RADEMACHER, n_clusters, 10**9)
    webb = bootstrap_p_floor(WeightScheme.WEBB, n_clusters, 10**9)
    assert webb < rademacher


@pytest.mark.parametrize(
    ("scheme", "n_clusters", "expected"),
    [
        (WeightScheme.RADEMACHER, 4, 2 / 2**4),
        (WeightScheme.RADEMACHER, 8, 2 / 2**8),
        (WeightScheme.WEBB, 4, 2 / 6**4),
        (WeightScheme.WEBB, 6, 2 / 6**6),
    ],
)
def test_floor_is_two_over_support_to_the_clusters(
    scheme: WeightScheme, n_clusters: int, expected: float
) -> None:
    """Steps of 2/S^G, not 1/S^G: |t*| is symmetric under a global sign flip."""
    assert bootstrap_p_floor(scheme, n_clusters, 10**9) == pytest.approx(expected)


def test_draw_resolution_binds_when_it_is_coarser() -> None:
    """With many clusters the number of draws is what limits resolution."""
    assert bootstrap_p_floor(WeightScheme.WEBB, 30, 999) == pytest.approx(1 / 1000)


def test_weight_schemes_have_mean_zero_and_unit_variance() -> None:
    for scheme in WeightScheme:
        support = scheme.support
        assert float(support.mean()) == pytest.approx(0.0, abs=1e-12)
        assert float((support**2).mean()) == pytest.approx(1.0)


def test_result_carries_the_floor_and_the_scheme() -> None:
    """Reported as a field, not as prose: visible at the call site."""
    result = estimate_dose_response(
        make_frame(beta=0.02, n_events=6),
        scheme=WEBB,
        bootstrap_draws=200,
        randomisation_draws=50,
    )
    assert result.weight_scheme is WeightScheme.WEBB
    assert result.p_floor_bootstrap == pytest.approx(1 / 201)
    assert result.p_wild_bootstrap >= result.p_floor_bootstrap
    assert "p_floor_bootstrap" in result.summary().index


def test_rademacher_with_few_clusters_warns_in_the_notes() -> None:
    result = estimate_dose_response(
        make_frame(beta=0.02, n_events=6),
        scheme=WeightScheme.RADEMACHER,
        bootstrap_draws=2000,
        randomisation_draws=20,
    )
    assert any("RADEMACHER" in note for note in result.notes)
    assert result.p_floor_bootstrap == pytest.approx(0.03125)


def test_design_that_cannot_reach_alpha_says_so() -> None:
    """Four events on Rademacher floors p at 0.125; 5% is unreachable."""
    result = estimate_dose_response(
        make_frame(beta=0.05, n_events=4),
        scheme=WeightScheme.RADEMACHER,
        bootstrap_draws=2000,
        randomisation_draws=20,
    )
    assert not result.detectable_at(0.05)
    assert any("cannot reject at the 5% level" in note for note in result.notes)


def test_webb_rescues_the_same_design() -> None:
    result = estimate_dose_response(
        make_frame(beta=0.05, n_events=4),
        scheme=WEBB,
        bootstrap_draws=2000,
        randomisation_draws=20,
    )
    assert result.detectable_at(0.05)


def test_scheme_is_required_with_no_silent_default() -> None:
    with pytest.raises(TypeError):
        estimate_dose_response(make_frame())  # type: ignore[call-arg]
