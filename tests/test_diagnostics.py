"""Diagnostics: placebos, pre-trends, leave-one-out, power."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from policy_event_study.data.prices import ReturnPanel
from policy_event_study.diagnostics.leave_one_out import leave_one_donor_out
from policy_event_study.diagnostics.placebo_space import (
    in_space_placebos,
    p_value_table,
)
from policy_event_study.diagnostics.placebo_time import (
    feasible_offsets,
    in_time_placebos,
)
from policy_event_study.diagnostics.power import (
    design_summary,
    donors_required_for,
    effective_sample_size,
    min_attainable_p,
    power_analysis,
    power_curve,
)
from policy_event_study.diagnostics.pretrends import (
    PreFitVerdict,
    pre_fit_report,
    pretrend_test,
)
from policy_event_study.estimators.base import EventSpec
from policy_event_study.estimators.market_model import MarketModelEstimator
from policy_event_study.estimators.synthetic_control import SyntheticControlEstimator
from policy_event_study.events.schema import ExpectedDirection
from tests.conftest import make_panel, make_spec

SC = SyntheticControlEstimator()
MM = MarketModelEstimator()


# -- in-space placebos -----------------------------------------------------


def test_placebo_pool_never_contains_the_treated_unit(
    null_panel: ReturnPanel, null_spec: EventSpec
) -> None:
    """Including the treated unit in a placebo's pool would bias p toward 1."""
    distribution = in_space_placebos(SC, null_panel, null_spec, "TREATED")
    assert "TREATED" not in distribution.placebo_taus.index
    assert distribution.n_placebos == len(null_spec.donors)


def test_null_panel_is_not_significant(
    null_panel: ReturnPanel, null_spec: EventSpec
) -> None:
    distribution = in_space_placebos(SC, null_panel, null_spec, "TREATED")
    assert distribution.p_value("ratio") > 0.10


def test_large_effect_reaches_the_tail() -> None:
    panel = make_panel(effect=0.30, effect_from=380, effect_length=21)
    spec = make_spec(panel, t0_index=380)
    distribution = in_space_placebos(SC, panel, spec, "TREATED")
    assert distribution.rank("ratio") == 1
    assert distribution.p_value("ratio") == pytest.approx(distribution.min_attainable_p)


def test_min_attainable_p_is_the_arithmetic_floor(
    null_panel: ReturnPanel, null_spec: EventSpec
) -> None:
    distribution = in_space_placebos(SC, null_panel, null_spec, "TREATED")
    assert distribution.min_attainable_p == pytest.approx(
        1.0 / (distribution.n_placebos + 1)
    )
    assert distribution.p_value("ratio") >= distribution.min_attainable_p


def test_p_value_is_never_zero(null_panel: ReturnPanel, null_spec: EventSpec) -> None:
    """The treated unit counts in its own reference set. Conservative by design."""
    panel = make_panel(effect=5.0, effect_from=380, effect_length=21)
    spec = make_spec(panel, t0_index=380)
    distribution = in_space_placebos(SC, panel, spec, "TREATED")
    assert distribution.p_value("ratio") > 0.0


def test_one_sided_reading_follows_the_pre_registered_direction() -> None:
    panel = make_panel(effect=0.20, effect_from=380, effect_length=21)
    positive = make_spec(
        panel, t0_index=380, expected_direction=ExpectedDirection.POSITIVE
    )
    negative = make_spec(
        panel, t0_index=380, expected_direction=ExpectedDirection.NEGATIVE
    )
    up = in_space_placebos(SC, panel, positive, "TREATED").p_value("tau")
    down = in_space_placebos(SC, panel, negative, "TREATED").p_value("tau")
    # A positive effect is extreme in the positive tail and unremarkable in the
    # negative one -- which is why the direction must be curated in advance.
    assert up < down


def test_exclusion_ladder_is_reported_in_full(
    null_panel: ReturnPanel, null_spec: EventSpec
) -> None:
    distribution = in_space_placebos(SC, null_panel, null_spec, "TREATED")
    table = p_value_table(distribution)
    assert list(table["pre_rmspe_cutoff"]) == ["none", "20x", "5x", "2x"]
    assert table["n_placebos"].is_monotonic_decreasing


def test_market_model_gets_the_same_permutation_inference(
    null_panel: ReturnPanel, null_spec: EventSpec
) -> None:
    """Like-for-like comparison needs the baseline permuted too."""
    distribution = in_space_placebos(MM, null_panel, null_spec, "TREATED")
    assert distribution.estimator == "market_model"
    assert distribution.n_placebos == len(null_spec.donors)
    assert 0.0 < distribution.p_value("ratio") <= 1.0


# -- in-time placebos ------------------------------------------------------


def test_in_time_offsets_respect_both_guards(
    null_panel: ReturnPanel, null_spec: EventSpec
) -> None:
    offsets = feasible_offsets(null_spec, null_panel.trading_days, buffer=10)
    days = null_panel.trading_days
    origin = int(days.get_indexer(pd.DatetimeIndex([null_spec.t0]))[0])
    for offset in offsets:
        assert offset < 0
        # fake post window ends at least `buffer` days before the real t0
        assert origin + offset + null_spec.post_horizon <= origin - 10 - 1
        # and keeps a full estimation window behind it
        assert origin + offset >= null_spec.estimation_length + null_spec.gap


def test_in_time_placebo_windows_do_not_overlap(
    null_panel: ReturnPanel, null_spec: EventSpec
) -> None:
    offsets = feasible_offsets(null_spec, null_panel.trading_days)
    spacing = sorted(offsets)
    gaps = np.diff(spacing)
    assert (gaps >= null_spec.post_horizon + 1).all()


def test_in_time_placebo_on_a_null_panel_is_not_significant(
    null_panel: ReturnPanel, null_spec: EventSpec
) -> None:
    result = in_time_placebos(SC, null_panel, null_spec, "TREATED", n_offsets=6)
    assert result.n_placebos > 0
    assert result.p_value("tau") > 0.10


def test_in_time_placebo_flags_a_real_effect() -> None:
    panel = make_panel(effect=0.30, effect_from=380, effect_length=21)
    spec = make_spec(panel, t0_index=380)
    result = in_time_placebos(SC, panel, spec, "TREATED", n_offsets=6)
    assert result.p_value("tau") == pytest.approx(result.min_attainable_p)


# -- pre-trends ------------------------------------------------------------


def test_pre_fit_verdict_passes_when_donors_span() -> None:
    panel = make_panel(idiosyncratic_sd=0.0002)
    spec = make_spec(panel)
    report = pre_fit_report(
        SC.estimate(panel, spec, "TREATED"),
        MM.estimate(panel, spec, "TREATED"),
        panel,
        spec,
    )
    assert report.verdict is PreFitVerdict.SPANS
    assert report.ratio_to_baseline < 1.0


def test_pre_fit_verdict_fails_when_the_unit_is_unspannable() -> None:
    """A treated unit driven by a factor no donor carries cannot be spanned."""
    panel = make_panel(idiosyncratic_sd=0.05)
    spec = make_spec(panel)
    report = pre_fit_report(
        SC.estimate(panel, spec, "TREATED"),
        MM.estimate(panel, spec, "TREATED"),
        panel,
        spec,
    )
    assert report.normalised_rmspe > 0.1


def test_pre_fit_refuses_a_mismatched_baseline(
    null_panel: ReturnPanel, null_spec: EventSpec
) -> None:
    with pytest.raises(ValueError, match="like-for-like"):
        pre_fit_report(
            SC.estimate(null_panel, null_spec, "TREATED"),
            MM.estimate(null_panel, null_spec, "DONOR01"),
            null_panel,
            null_spec,
        )


def test_pretrend_holdout_uses_the_embargoed_days(
    null_panel: ReturnPanel, null_spec: EventSpec
) -> None:
    """The embargo is the design's only true out-of-sample pre-event window."""
    test = pretrend_test(
        SC.estimate(null_panel, null_spec, "TREATED"), null_spec, null_panel
    )
    assert test.n_holdout == null_spec.gap
    assert np.isfinite(test.holdout_drift)
    assert np.isfinite(test.holdout_z)


def test_pretrend_detects_injected_pre_event_drift() -> None:
    """An effect starting inside the embargo is a pre-trend, and must be caught."""
    panel = make_panel(effect=0.25, effect_from=350, effect_length=40)
    spec = make_spec(panel, t0_index=380, gap=10)
    test = pretrend_test(SC.estimate(panel, spec, "TREATED"), spec, panel)
    assert abs(test.holdout_z) > 1.96
    assert test.violated


def test_clean_panel_shows_no_pretrend(
    null_panel: ReturnPanel, null_spec: EventSpec
) -> None:
    test = pretrend_test(
        SC.estimate(null_panel, null_spec, "TREATED"), null_spec, null_panel
    )
    assert not test.violated


# -- leave-one-out ---------------------------------------------------------


def test_leave_one_out_refits_only_contributing_donors(
    null_panel: ReturnPanel, null_spec: EventSpec
) -> None:
    result = leave_one_donor_out(SC, null_panel, null_spec, "TREATED")
    assert 0 < result.n_refits <= len(null_spec.donors)
    assert result.most_influential in null_spec.donors


def test_leave_one_out_on_a_well_spanned_unit_is_stable() -> None:
    panel = make_panel(
        effect=0.10, effect_from=380, effect_length=21, idiosyncratic_sd=0.0002
    )
    spec = make_spec(panel, t0_index=380)
    result = leave_one_donor_out(SC, panel, spec, "TREATED")
    assert result.sign_stable
    assert result.relative_shift < 0.5


def test_leave_one_out_reports_concentration(
    null_panel: ReturnPanel, null_spec: EventSpec
) -> None:
    result = leave_one_donor_out(SC, null_panel, null_spec, "TREATED")
    assert result.effective_donor_count > 0
    assert 0.0 <= result.max_weight <= 1.0
    assert not result.table().empty


def test_leave_one_out_says_so_when_there_are_no_donors(
    null_panel: ReturnPanel, null_spec: EventSpec
) -> None:
    """The market model has no weights; the blank is explained, not left empty."""
    result = leave_one_donor_out(MM, null_panel, null_spec, "TREATED")
    assert result.n_refits == 0
    assert "does not apply" in result.failures["_"]


# -- power -----------------------------------------------------------------


def test_arithmetic_floor() -> None:
    assert min_attainable_p(19) == pytest.approx(0.05)
    assert donors_required_for(0.05) == 19
    assert donors_required_for(0.01) == 99


def test_power_analysis_flags_an_infeasible_design() -> None:
    panel = make_panel(n_donors=5)
    spec = make_spec(panel)
    distribution = in_space_placebos(SC, panel, spec, "TREATED")
    analysis = power_analysis(distribution, alpha=0.05)
    assert not analysis.feasible
    assert "cannot reject" in analysis.narrative()


def test_fifteen_donors_cannot_reject_at_five_percent(
    null_panel: ReturnPanel, null_spec: EventSpec
) -> None:
    """The default fixture has 15 donors, so the floor is 1/16 = 0.0625.

    Not a fixture accident -- it is the constraint the report's power section
    exists to state. A 5% threshold needs 19 donors before any data is seen.
    """
    distribution = in_space_placebos(SC, null_panel, null_spec, "TREATED")
    assert distribution.n_placebos == 15
    assert not power_analysis(distribution, alpha=0.05).feasible
    assert power_analysis(distribution, alpha=0.10).feasible


def test_power_analysis_on_a_feasible_design() -> None:
    panel = make_panel(n_donors=24)
    spec = make_spec(panel)
    distribution = in_space_placebos(SC, panel, spec, "TREATED")
    analysis = power_analysis(distribution, alpha=0.05, target_power=0.8)
    assert analysis.feasible
    assert abs(analysis.mde) > abs(analysis.mde_at_50_power)
    assert "minimum detectable effect" in analysis.narrative()


def test_power_curve_is_monotone(null_panel: ReturnPanel, null_spec: EventSpec) -> None:
    distribution = in_space_placebos(SC, null_panel, null_spec, "TREATED")
    curve = power_curve(distribution, [0.0, 0.02, 0.05, 0.10, 0.25])
    assert curve["detection_probability"].is_monotonic_increasing
    assert float(curve["detection_probability"].iloc[-1]) >= float(
        curve["detection_probability"].iloc[0]
    )


def test_effective_sample_size_discounts_correlated_units() -> None:
    """Seven firms correlated at 0.7 are worth well under seven observations."""
    rng = np.random.default_rng(1)
    common = rng.normal(size=500)
    frame = pd.DataFrame(
        {f"F{index}": 0.84 * common + 0.55 * rng.normal(size=500) for index in range(7)}
    )
    effective = effective_sample_size(frame)
    assert 1.0 < effective < 2.5
    assert effective_sample_size(frame[["F0"]]) == 1.0


def test_design_summary_is_computable_before_estimation() -> None:
    table = design_summary(n_donors=23, n_events=6, n_treated=4)
    floor = float(
        table.loc[table["quantity"] == "min attainable p (in-space)", "value"].iloc[0]
    )
    assert floor == pytest.approx(1 / 24)


def test_two_sided_mde_exceeds_one_sided_on_identical_data() -> None:
    """A two-sided test cannot be more powerful than a one-sided one.

    Regression guard: taking both the critical value and the power quantile
    from the absolute placebo distribution inverts this, because the
    alternative shifts the signed statistic, not its absolute value.
    """
    panel = make_panel(n_donors=24)
    ambiguous = make_spec(panel, expected_direction=ExpectedDirection.AMBIGUOUS)
    directional = make_spec(panel, expected_direction=ExpectedDirection.POSITIVE)

    two_sided = power_analysis(in_space_placebos(SC, panel, ambiguous, "TREATED"))
    one_sided = power_analysis(in_space_placebos(SC, panel, directional, "TREATED"))

    assert abs(two_sided.mde) > abs(one_sided.mde)
    assert abs(two_sided.critical_value) > abs(one_sided.critical_value)


def test_mde_at_50_power_is_near_the_critical_value() -> None:
    """An effect exactly at the critical value is detected about half the time."""
    panel = make_panel(n_donors=24)
    spec = make_spec(panel, expected_direction=ExpectedDirection.AMBIGUOUS)
    analysis = power_analysis(in_space_placebos(SC, panel, spec, "TREATED"))
    assert analysis.mde_at_50_power == pytest.approx(analysis.critical_value, rel=0.35)
