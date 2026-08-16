"""Reporting: the placebo rule is enforced, and flagged events stay separate."""

from __future__ import annotations

import pandas as pd
import pytest

from policy_event_study.diagnostics.placebo_space import in_space_placebos
from policy_event_study.estimators.market_model import MarketModelEstimator
from policy_event_study.estimators.synthetic_control import SyntheticControlEstimator
from policy_event_study.events.schema import (
    AnticipationRisk,
    ExpectedDirection,
    PolicyDirection,
    PolicyEvent,
)
from policy_event_study.reporting.event_study import (
    EventResult,
    MissingPlaceboError,
    render_report,
    run_event,
)
from tests.conftest import make_panel, make_spec

SC = SyntheticControlEstimator()
MM = MarketModelEstimator()


def make_event(**overrides: object) -> PolicyEvent:
    fields: dict[str, object] = {
        "event_id": "2023-09-20-rollback",
        "date": pd.Timestamp("2023-09-20"),
        "announcement_ts_utc": pd.Timestamp("2023-09-20T19:00:00Z"),
        "policy": "PM speech rowing back the boiler phase-out",
        "source_url": "https://www.gov.uk/government/speeches/pm-speech",
        "anticipation_risk": AnticipationRisk.LOW,
        "expected_direction": ExpectedDirection.NEGATIVE,
        "affected_sectors": ("insulation_and_materials",),
        "direction": PolicyDirection.LOOSEN,
    }
    fields.update(overrides)
    return PolicyEvent(**fields)  # type: ignore[arg-type]  # kwargs are typed above


def test_point_estimate_without_placebos_is_refused() -> None:
    """The project's hard rule, enforced by the type rather than by review."""
    panel = make_panel()
    spec = make_spec(panel)
    with pytest.raises(MissingPlaceboError, match="no placebo distribution"):
        EventResult(
            event=make_event(),
            spec=spec,
            treated_unit="TREATED",
            estimates={"synthetic_control": SC.estimate(panel, spec, "TREATED")},
            placebos={},
        )


def test_partial_placebo_coverage_is_also_refused() -> None:
    panel = make_panel()
    spec = make_spec(panel)
    with pytest.raises(MissingPlaceboError, match="market_model"):
        EventResult(
            event=make_event(),
            spec=spec,
            treated_unit="TREATED",
            estimates={
                "synthetic_control": SC.estimate(panel, spec, "TREATED"),
                "market_model": MM.estimate(panel, spec, "TREATED"),
            },
            placebos={
                "synthetic_control": in_space_placebos(SC, panel, spec, "TREATED")
            },
        )


def test_run_event_produces_all_three_with_full_diagnostics() -> None:
    panel = make_panel(effect=0.10, effect_from=380, effect_length=21)
    spec = make_spec(panel, t0_index=380)
    result = run_event(panel, make_event(), spec, "TREATED", n_time_placebos=4)

    assert set(result.estimates) == {
        "market_model",
        "synthetic_control",
        "synthetic_did",
    }
    assert set(result.placebos) == set(result.estimates)
    table = result.effects_table()
    assert len(table) == 3
    for column in ("tau", "p_in_space", "p_in_time", "min_attainable_p", "mde_80"):
        assert column in table.columns
    assert table["p_in_space"].notna().all()


def test_market_model_is_always_included_even_if_omitted() -> None:
    """`CLAUDE.md` §4: the baseline is not optional."""
    panel = make_panel()
    spec = make_spec(panel)
    result = run_event(
        panel, make_event(), spec, "TREATED", estimators=[SC], n_time_placebos=3
    )
    assert "market_model" in result.estimates


@pytest.mark.parametrize(
    "overrides",
    [
        {"anticipation_risk": AnticipationRisk.HIGH, "leak_note": "trailed"},
        {"confounders": ("autumn_statement",)},
        {"leak_note": "BBC ran it the night before"},
    ],
)
def test_flagged_events_are_kept_out_of_the_pooled_section(
    overrides: dict[str, object],
) -> None:
    panel = make_panel()
    spec = make_spec(panel)
    result = run_event(
        panel, make_event(**overrides), spec, "TREATED", n_time_placebos=3
    )
    assert result.separately_reported

    report = render_report([result])
    clean, flagged = report.split("## Events reported separately")
    assert "_None yet._" in clean
    assert result.treated_unit in flagged


def test_high_anticipation_section_discusses_identification() -> None:
    panel = make_panel()
    spec = make_spec(panel)
    result = run_event(
        panel,
        make_event(anticipation_risk=AnticipationRisk.HIGH, leak_note="pre-briefed"),
        spec,
        "TREATED",
        n_time_placebos=3,
    )
    report = render_report([result])
    assert "The market already knew" in report
    assert "residual" in report
    assert "pre-briefed" in report


def test_clean_event_lands_in_the_pooled_section() -> None:
    panel = make_panel()
    spec = make_spec(panel)
    result = run_event(panel, make_event(), spec, "TREATED", n_time_placebos=3)
    assert not result.separately_reported
    report = render_report([result])
    clean, flagged = report.split("## Events reported separately")
    assert "TREATED" in clean
    assert "_None yet._" in flagged


def test_report_renders_a_table_with_the_placebo_columns() -> None:
    panel = make_panel()
    spec = make_spec(panel)
    result = run_event(panel, make_event(), spec, "TREATED", n_time_placebos=3)
    report = render_report([result])
    assert "| p_in_space |" in report.replace("|p_in_space|", "| p_in_space |")
    assert "min_attainable_p" in report
    assert "exclusion ladder" in report
