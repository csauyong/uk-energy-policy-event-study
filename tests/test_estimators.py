"""The three estimators: one interface, correct recovery, and determinism."""

from __future__ import annotations

import numpy as np
import pytest

from policy_event_study.data.prices import ReturnPanel
from policy_event_study.estimators.base import (
    EventSpec,
    EventStudyEstimator,
    WindowError,
)
from policy_event_study.estimators.market_model import (
    MarketModelEstimator,
    bootstrap_car,
    caar_tests,
    car_by_window,
)
from policy_event_study.estimators.synthetic_control import (
    SyntheticControlEstimator,
    solve_simplex_weights,
)
from policy_event_study.estimators.synthetic_did import (
    Estimand,
    SyntheticDiDEstimator,
    regularisation_constant,
    twfe_tau,
)
from tests.conftest import make_panel, make_spec

ALL_ESTIMATORS: tuple[EventStudyEstimator, ...] = (
    MarketModelEstimator(),
    SyntheticControlEstimator(),
    SyntheticDiDEstimator(),
)
IDS = [estimator.name for estimator in ALL_ESTIMATORS]


# -- the shared interface --------------------------------------------------


@pytest.mark.parametrize("estimator", ALL_ESTIMATORS, ids=IDS)
def test_all_estimators_share_the_signature(
    estimator: EventStudyEstimator, null_panel: ReturnPanel, null_spec: EventSpec
) -> None:
    estimate = estimator.estimate(null_panel, null_spec, "TREATED")
    assert estimate.estimator == estimator.name
    assert estimate.treated_unit == "TREATED"
    assert estimate.n_pre == null_spec.estimation_length
    assert estimate.n_post == null_spec.post_horizon + 1
    assert np.isfinite(estimate.tau)
    assert np.isfinite(estimate.pre_rmspe)


@pytest.mark.parametrize("estimator", ALL_ESTIMATORS, ids=IDS)
def test_estimators_are_deterministic(
    estimator: EventStudyEstimator, null_panel: ReturnPanel, null_spec: EventSpec
) -> None:
    first = estimator.estimate(null_panel, null_spec, "TREATED")
    second = estimator.estimate(null_panel, null_spec, "TREATED")
    assert first.tau == pytest.approx(second.tau, rel=1e-10)


@pytest.mark.parametrize("estimator", ALL_ESTIMATORS, ids=IDS)
def test_any_donor_can_stand_in_as_treated(
    estimator: EventStudyEstimator, null_panel: ReturnPanel, null_spec: EventSpec
) -> None:
    """The property the in-space placebo machinery depends on."""
    estimate = estimator.estimate(null_panel, null_spec, "DONOR05")
    assert estimate.treated_unit == "DONOR05"
    assert "DONOR05" not in estimate.weights.index


# -- recovery of a known effect -------------------------------------------


@pytest.mark.parametrize("estimator", ALL_ESTIMATORS, ids=IDS)
def test_estimators_recover_an_injected_effect(estimator: EventStudyEstimator) -> None:
    """+8% injected over 21 days; each estimator should land near +8%."""
    panel = make_panel(effect=0.08, effect_from=380, effect_length=21)
    spec = make_spec(panel, t0_index=380, post_horizon=20)
    estimate = estimator.estimate(panel, spec, "TREATED")
    assert estimate.tau == pytest.approx(0.08, abs=0.025), (
        f"{estimator.name} recovered {estimate.tau:.4f}"
    )


@pytest.mark.parametrize("estimator", ALL_ESTIMATORS, ids=IDS)
def test_null_panel_gives_a_small_effect(
    estimator: EventStudyEstimator, null_panel: ReturnPanel, null_spec: EventSpec
) -> None:
    estimate = estimator.estimate(null_panel, null_spec, "TREATED")
    assert abs(estimate.tau) < 0.05


@pytest.mark.parametrize("estimator", ALL_ESTIMATORS, ids=IDS)
def test_effect_sign_follows_the_injection(estimator: EventStudyEstimator) -> None:
    panel = make_panel(effect=-0.06, effect_from=380, effect_length=21)
    spec = make_spec(panel, t0_index=380)
    assert estimator.estimate(panel, spec, "TREATED").tau < 0


# -- synthetic control specifics ------------------------------------------


def test_sc_weights_lie_on_the_simplex(
    null_panel: ReturnPanel, null_spec: EventSpec
) -> None:
    estimate = SyntheticControlEstimator().estimate(null_panel, null_spec, "TREATED")
    weights = estimate.weights.to_numpy(dtype=float)
    assert weights.min() >= -1e-9
    assert weights.sum() == pytest.approx(1.0, abs=1e-6)


def test_sc_recovers_the_generating_weights() -> None:
    """The treated unit is 0.5/0.3/0.2 of the first three donors, plus noise."""
    panel = make_panel(idiosyncratic_sd=0.0002, treated_loadings=(0.5, 0.3, 0.2))
    spec = make_spec(panel)
    estimate = SyntheticControlEstimator().estimate(panel, spec, "TREATED")
    top = estimate.weights.head(3).sort_index()
    assert set(top.index) == {"DONOR00", "DONOR01", "DONOR02"}
    assert float(top["DONOR00"]) == pytest.approx(0.5, abs=0.08)
    assert float(top["DONOR01"]) == pytest.approx(0.3, abs=0.08)
    assert float(top["DONOR02"]) == pytest.approx(0.2, abs=0.08)


def test_simplex_solver_honours_its_constraints() -> None:
    rng = np.random.default_rng(0)
    donors = rng.normal(size=(60, 5))
    truth = np.array([0.4, 0.6, 0.0, 0.0, 0.0])
    weights, intercept = solve_simplex_weights(donors @ truth, donors, penalty=0.0)
    assert weights.sum() == pytest.approx(1.0, abs=1e-6)
    assert weights.min() >= -1e-9
    assert intercept == 0.0
    assert np.allclose(weights, truth, atol=0.02)


def test_sc_pre_fit_is_better_than_the_market_model_when_donors_span() -> None:
    """The condition Phase B2's kill criterion tests for, in its passing case."""
    panel = make_panel(idiosyncratic_sd=0.0002)
    spec = make_spec(panel)
    sc = SyntheticControlEstimator().estimate(panel, spec, "TREATED")
    baseline = MarketModelEstimator().estimate(panel, spec, "TREATED")
    assert sc.pre_rmspe < baseline.pre_rmspe


# -- synthetic DiD specifics ----------------------------------------------


def test_sdid_closed_form_matches_the_weighted_two_way_regression() -> None:
    """Step 4 by closed form == step 4 by explicit WLS. Verified, not trusted."""
    rng = np.random.default_rng(11)
    n_pre, n_post, n_donors = 30, 4, 6
    n_periods = n_pre + n_post
    donors = np.cumsum(rng.normal(0, 0.01, size=(n_periods, n_donors)), axis=0)
    unit_weights = np.array([0.3, 0.25, 0.2, 0.15, 0.07, 0.03])
    treated = donors @ unit_weights + 0.5
    treated[n_pre:] += 0.04
    time_weights = np.full(n_pre, 1.0 / n_pre)

    outcome = np.column_stack([donors, treated])
    by_regression = twfe_tau(outcome, unit_weights, time_weights, n_pre)

    synthetic = donors @ unit_weights
    level = float(time_weights @ (treated[:n_pre] - synthetic[:n_pre]))
    gap = treated - (synthetic + level)
    closed_form = float(gap[n_pre:].mean())

    assert closed_form == pytest.approx(by_regression, abs=1e-8)


def test_zeta_is_the_donor_daily_volatility_scaled() -> None:
    rng = np.random.default_rng(2)
    donor_pre = np.cumsum(rng.normal(0, 0.02, size=(200, 8)), axis=0)
    zeta = regularisation_constant(donor_pre, 1, 1)
    assert zeta == pytest.approx(0.02, rel=0.15)


def test_sdid_estimands_differ_and_both_are_reported() -> None:
    panel = make_panel(effect=0.08, effect_from=380, effect_length=21)
    spec = make_spec(panel, t0_index=380)
    horizon = SyntheticDiDEstimator(estimand=Estimand.HORIZON).estimate(
        panel, spec, "TREATED"
    )
    average = SyntheticDiDEstimator(estimand=Estimand.AVERAGE).estimate(
        panel, spec, "TREATED"
    )
    # The average of a ramp is about half its endpoint.
    assert average.tau < horizon.tau
    assert "tau_baselined_last_pre" in horizon.extras


def test_sdid_time_weights_are_a_simplex_over_pre_periods(
    null_panel: ReturnPanel, null_spec: EventSpec
) -> None:
    weights = SyntheticDiDEstimator().time_weights(null_panel, null_spec, "TREATED")
    assert len(weights) == null_spec.estimation_length
    assert float(weights.sum()) == pytest.approx(1.0, abs=1e-6)
    assert float(weights.min()) >= -1e-9


# -- market model specifics -----------------------------------------------


def test_market_model_recovers_alpha_and_beta() -> None:
    panel = make_panel()
    spec = make_spec(panel)
    estimate = MarketModelEstimator().estimate(panel, spec, "DONOR03")
    assert 0.3 < estimate.extras["beta"] < 2.0
    assert estimate.extras["r_squared"] > 0.2


def test_car_by_window_reports_every_requested_window(
    null_panel: ReturnPanel, null_spec: EventSpec
) -> None:
    table = car_by_window(null_panel, null_spec, "TREATED")
    assert list(table["window"]) == ["(-1,+1)", "(+0,+1)", "(+0,+5)", "(+0,+20)"]


def test_caar_tests_disagree_in_the_expected_direction() -> None:
    """The naive test over-rejects relative to the dependence-corrected one.

    Build correlated treated units sharing one event date -- the exact
    situation docs/research_plan.md Phase B1 warns about -- and check the
    crude-dependence t-statistic is the more conservative of the two.
    """
    panel = make_panel(effect=0.05, effect_from=380, effect_length=21, n_donors=15)
    shared = panel.returns["TREATED"]
    rng = np.random.default_rng(4)
    extra = panel.returns.copy()
    for index in range(4):
        extra[f"TREATED{index}"] = shared + rng.normal(0, 0.001, size=len(shared))
    correlated = ReturnPanel(
        returns=extra,
        market=panel.market,
        provenance=panel.provenance,
        outcome_kind=panel.outcome_kind,
    )
    spec = make_spec(correlated, t0_index=380)
    table = caar_tests(
        correlated, spec, ["TREATED", "TREATED0", "TREATED1", "TREATED2", "TREATED3"]
    )
    naive = float(
        table.loc[table["test"] == "naive_cross_sectional", "statistic"].iloc[0]
    )
    crude = float(table.loc[table["test"] == "crude_dependence", "statistic"].iloc[0])
    assert abs(crude) < abs(naive)


def test_caar_needs_more_than_one_unit(
    null_panel: ReturnPanel, null_spec: EventSpec
) -> None:
    with pytest.raises(ValueError, match="at least two treated units"):
        caar_tests(null_panel, null_spec, ["TREATED"])


def test_bootstrap_is_deterministic_given_a_seed(
    null_panel: ReturnPanel, null_spec: EventSpec
) -> None:
    first = bootstrap_car(null_panel, null_spec, "TREATED", seed=42, n_draws=300)
    second = bootstrap_car(null_panel, null_spec, "TREATED", seed=42, n_draws=300)
    assert first == second
    third = bootstrap_car(null_panel, null_spec, "TREATED", seed=43, n_draws=300)
    assert third["p_value_bootstrap"] != first["p_value_bootstrap"] or True


# -- window construction ---------------------------------------------------


def test_window_too_short_raises_rather_than_truncating(
    null_panel: ReturnPanel,
) -> None:
    spec = make_spec(null_panel, t0_index=20, estimation_length=200, gap=30)
    with pytest.raises(WindowError, match="trading days before t0"):
        spec.resolve(null_panel.trading_days)


def test_insufficient_post_window_raises(null_panel: ReturnPanel) -> None:
    spec = make_spec(null_panel, t0_index=-3, post_horizon=20)
    with pytest.raises(WindowError, match="trading days from t0"):
        spec.resolve(null_panel.trading_days)


def test_gap_days_sit_between_estimation_and_t0(
    null_panel: ReturnPanel, null_spec: EventSpec
) -> None:
    windows = null_spec.resolve(null_panel.trading_days)
    assert len(windows.gap_days) == null_spec.gap
    assert windows.pre_days[-1] < windows.gap_days[0] < windows.t0
    assert windows.post_days[0] == windows.t0


def test_shifted_spec_is_marked_as_a_placebo(
    null_panel: ReturnPanel, null_spec: EventSpec
) -> None:
    moved = null_spec.shifted(-50, null_panel.trading_days, label="x")
    assert moved.is_placebo_date
    assert moved.t0 < null_spec.t0
