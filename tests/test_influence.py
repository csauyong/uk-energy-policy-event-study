"""Influence diagnostics and the mandate-versus-repeal falsification test."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from policy_event_study.diagnostics.influence import (
    effective_firm_count,
    functional_form_comparison,
    influence_report,
    leverage_report,
    top_k_drop_path,
    winsorised_variant,
)
from policy_event_study.diagnostics.sign_consistency import sign_consistency
from policy_event_study.estimators.dose_response import (
    WeightScheme,
    dose_response_mde,
    estimate_dose_response,
)
from policy_event_study.events.schema import PolicyDirection
from policy_event_study.reporting.dose_response import (
    DoseResponseSection,
    MissingInfluenceError,
)
from tests.test_dose_response import make_frame

WEBB = WeightScheme.WEBB


def skewed_frame(
    *,
    beta: float = 0.0,
    n_firms: int = 200,
    n_events: int = 6,
    n_exposed: int = 6,
    whale_beta: float | None = None,
    seed: int = 3,
) -> pd.DataFrame:
    """Panel where exposure sits on a handful of names, as in the real design.

    `whale_beta` puts the entire gradient on the single most exposed firm, so
    the drop path has something real to catch.
    """
    rng = np.random.default_rng(seed)
    rows = []
    for event in range(n_events):
        exposure = np.zeros(n_firms)
        exposure[:n_exposed] = np.linspace(1.0, 0.2, n_exposed)
        standardised = (exposure - exposure.mean()) / exposure.std(ddof=1)
        car = rng.normal(0.0, 0.02, size=n_firms) + beta * standardised
        if whale_beta is not None:
            car[0] += whale_beta
        rows.append(
            pd.DataFrame(
                {
                    "unit_id": [f"F{index:04d}" for index in range(n_firms)],
                    "event_id": f"E{event}",
                    "car": car,
                    "exposure_continuous": standardised,
                    "exposure_rank": pd.Series(standardised).rank(pct=True).to_numpy(),
                    "size": rng.normal(size=n_firms),
                    "book_to_market": rng.normal(size=n_firms),
                    "momentum": rng.normal(size=n_firms),
                    "pre_event_vol": rng.uniform(0.5, 2.0, size=n_firms),
                }
            )
        )
    return pd.concat(rows, ignore_index=True)


# -- leverage --------------------------------------------------------------


def test_leverage_sums_to_the_parameter_count() -> None:
    """Trace of the hat matrix equals the number of fitted parameters."""
    report = leverage_report(make_frame())
    assert float(report.hat_values.sum()) == pytest.approx(
        report.n_parameters, rel=0.02
    )


def test_skewed_exposure_concentrates_leverage() -> None:
    concentrated = leverage_report(skewed_frame(n_exposed=4))
    diffuse = leverage_report(make_frame(exposed_share=0.5))
    assert concentrated.leverage_share_top_5pct > diffuse.leverage_share_top_5pct


def test_effective_firm_count_is_an_inverse_herfindahl() -> None:
    equal = pd.Series([0.1] * 10)
    units = pd.Series([f"F{i}" for i in range(10)])
    effective, nominal = effective_firm_count(equal, units)
    assert nominal == 10
    assert effective == pytest.approx(10.0)

    lopsided = pd.Series([1.0, *([1e-9] * 9)])
    effective, _ = effective_firm_count(lopsided, units)
    assert effective == pytest.approx(1.0, abs=0.01)


def test_effective_firms_below_nominal_when_exposure_is_skewed() -> None:
    report = leverage_report(skewed_frame(n_exposed=5))
    assert report.effective_firms < report.nominal_firms
    assert 0.0 < report.participation_fraction < 1.0


def test_cooks_distance_flags_an_outlier() -> None:
    frame = skewed_frame(whale_beta=0.5)
    report = leverage_report(frame)
    assert report.n_cooks_above_threshold > 0
    assert report.max_cooks > 0


# -- top-k drop path -------------------------------------------------------


def test_drop_path_kills_a_beta_carried_by_one_firm() -> None:
    """The check's whole purpose: a beta resting on one name must not survive."""
    frame = skewed_frame(beta=0.0, whale_beta=0.30)
    baseline = estimate_dose_response(
        frame, scheme=WEBB, bootstrap_draws=100, randomisation_draws=1
    )
    assert abs(baseline.beta) > 0.001, "fixture must produce a beta to destroy"

    path = top_k_drop_path(frame, scheme=WEBB, bootstrap_draws=100)
    assert path[0].k == 1
    assert path[0].dropped_units == ("F0000",)
    assert abs(path[0].share_of_beta_retained) < 0.5


def test_drop_path_survives_a_genuinely_diffuse_gradient() -> None:
    frame = make_frame(beta=0.03, exposed_share=0.4, n_firms=200)
    path = top_k_drop_path(frame, scheme=WEBB, bootstrap_draws=100)
    baseline = estimate_dose_response(
        frame, scheme=WEBB, bootstrap_draws=100, randomisation_draws=1
    )
    for step in path:
        assert np.sign(step.beta) == np.sign(baseline.beta)
        assert step.share_of_beta_retained > 0.5


def test_drop_path_removes_whole_firms_not_single_rows() -> None:
    frame = skewed_frame()
    path = top_k_drop_path(frame, scheme=WEBB, depths=(2,), bootstrap_draws=50)
    n_events = frame["event_id"].nunique()
    assert path[0].n_observations == len(frame) - 2 * n_events


def test_drop_path_records_loss_of_identification_rather_than_raising() -> None:
    """Dropping every exposed firm removes all variation. That is the finding."""
    frame = skewed_frame(n_exposed=2)
    path = top_k_drop_path(frame, scheme=WEBB, depths=(1, 2, 3), bootstrap_draws=50)
    assert np.isnan(path[-1].beta)
    assert path[-1].share_of_beta_retained == 0.0


# -- winsorisation and functional form ------------------------------------


def test_winsorised_variant_runs_and_stays_standardised() -> None:
    frame = make_frame(beta=0.02)
    result = winsorised_variant(frame, scheme=WEBB, bootstrap_draws=100)
    assert np.isfinite(result.beta)
    assert result.n_observations == len(frame)


def test_functional_form_comparison_agrees_on_a_clean_gradient() -> None:
    continuous, rank, correlation = functional_form_comparison(
        make_frame(beta=0.03), scheme=WEBB, bootstrap_draws=100
    )
    assert np.sign(continuous) == np.sign(rank)
    assert correlation > 0.9


# -- the assembled report --------------------------------------------------


def test_influence_report_verdict_flags_a_fragile_beta() -> None:
    report = influence_report(
        skewed_frame(whale_beta=0.30), scheme=WEBB, bootstrap_draws=100
    )
    assert not report.survives_drop_path
    assert "FRAGILE" in report.verdict


def test_influence_report_verdict_passes_a_diffuse_beta() -> None:
    report = influence_report(
        make_frame(beta=0.03, exposed_share=0.4, n_firms=200),
        scheme=WEBB,
        bootstrap_draws=100,
    )
    assert report.survives_drop_path
    assert report.functional_form_agrees
    assert report.verdict.startswith(("ROBUST", "CAUTION"))


# -- reporting enforcement -------------------------------------------------


def test_beta_without_influence_diagnostics_is_refused() -> None:
    """The counterpart to MissingPlaceboError, enforced the same way."""
    frame = make_frame(beta=0.02)
    result = estimate_dose_response(
        frame, scheme=WEBB, bootstrap_draws=100, randomisation_draws=1
    )
    with pytest.raises(MissingInfluenceError, match="no influence diagnostics"):
        DoseResponseSection(result=result, mde=dose_response_mde(frame), influence=None)


def test_section_renders_floor_and_effective_firms() -> None:
    frame = make_frame(beta=0.02)
    section = DoseResponseSection(
        result=estimate_dose_response(
            frame, scheme=WEBB, bootstrap_draws=200, randomisation_draws=1
        ),
        mde=dose_response_mde(frame),
        influence=influence_report(frame, scheme=WEBB, bootstrap_draws=100),
    )
    table = section.headline_table()
    for column in ("p_floor", "effective_firms", "nominal_firms", "weights"):
        assert column in table.columns
    rendered = section.render()
    assert "MDE first" in rendered
    assert "drop path" in rendered
    assert "FALSIFICATION NOT RUN" in rendered


def test_section_flags_a_design_that_cannot_reach_five_percent() -> None:
    frame = make_frame(beta=0.02, n_events=4)
    section = DoseResponseSection(
        result=estimate_dose_response(
            frame,
            scheme=WeightScheme.RADEMACHER,
            bootstrap_draws=2000,
            randomisation_draws=1,
        ),
        mde=dose_response_mde(frame),
        influence=influence_report(frame, scheme=WEBB, bootstrap_draws=100),
    )
    assert not section.trustworthy
    assert any("P-VALUE FLOOR" in note for note in section.caveats())


# -- Fix 3: sign consistency ----------------------------------------------


def directional_frame(
    *, beta_tighten: float, beta_loosen: float, seed: int = 5
) -> pd.DataFrame:
    """Panel with three tightening and three loosening events."""
    rng = np.random.default_rng(seed)
    rows = []
    for index in range(6):
        direction = PolicyDirection.TIGHTEN if index < 3 else PolicyDirection.LOOSEN
        gradient = beta_tighten if index < 3 else beta_loosen
        n_firms = 150
        neutral = np.zeros(n_firms)
        neutral[:20] = rng.uniform(0.2, 1.0, 20) * rng.choice([-1.0, 1.0], 20)
        rows.append(
            pd.DataFrame(
                {
                    "unit_id": [f"F{j:04d}" for j in range(n_firms)],
                    "event_id": f"E{index}",
                    "direction": str(direction),
                    "car": rng.normal(0, 0.02, n_firms) + gradient * neutral,
                    "exposure_channel_signed": neutral,
                    "exposure_continuous": neutral,
                    "exposure_rank": pd.Series(neutral).rank(pct=True).to_numpy(),
                    "size": rng.normal(size=n_firms),
                    "book_to_market": rng.normal(size=n_firms),
                    "momentum": rng.normal(size=n_firms),
                    "pre_event_vol": rng.uniform(0.5, 2.0, n_firms),
                }
            )
        )
    return pd.concat(rows, ignore_index=True)


def test_falsification_passes_when_signs_oppose() -> None:
    """A mandate and its repeal must move exposed firms opposite ways."""
    result = sign_consistency(
        directional_frame(beta_tighten=0.05, beta_loosen=-0.05),
        scheme=WEBB,
        bootstrap_draws=200,
    )
    assert result.signs_oppose
    assert result.passes
    assert "PASSES" in result.verdict()


def test_falsification_fails_when_signs_agree() -> None:
    """The disconfirmation: exposure is proxying for something persistent."""
    result = sign_consistency(
        directional_frame(beta_tighten=0.05, beta_loosen=0.05),
        scheme=WEBB,
        bootstrap_draws=200,
    )
    assert not result.signs_oppose
    assert not result.passes
    assert "FAILS" in result.verdict()
    assert "other than policy exposure" in result.verdict()


def test_falsification_reports_when_one_side_is_absent() -> None:
    frame = directional_frame(beta_tighten=0.05, beta_loosen=-0.05)
    only_tighten = frame[frame["direction"] == str(PolicyDirection.TIGHTEN)]
    result = sign_consistency(only_tighten, scheme=WEBB, bootstrap_draws=100)
    assert result.n_events_loosen == 0
    assert "NOT RUN" in result.verdict()


def test_falsification_flags_an_underpowered_split() -> None:
    frame = directional_frame(beta_tighten=0.05, beta_loosen=-0.05)
    thin = frame[frame["event_id"].isin(["E0", "E3"])]
    result = sign_consistency(thin, scheme=WEBB, bootstrap_draws=100)
    assert result.underpowered
    assert "UNDERPOWERED" in result.verdict()


def test_falsification_requires_the_direction_column() -> None:
    frame = directional_frame(beta_tighten=0.05, beta_loosen=-0.05).drop(
        columns=["direction"]
    )
    with pytest.raises(ValueError, match="no `direction` column"):
        sign_consistency(frame, scheme=WEBB)
