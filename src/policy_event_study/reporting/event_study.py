"""Assemble `reports/event_study.md`.

This module holds the project's one hard reporting rule, and holds it as code
rather than as a convention:

    **No point estimate is rendered without its placebo distribution.**

:class:`EventResult` refuses to construct if an estimator contributed a
:class:`~policy_event_study.estimators.base.EffectEstimate` without a matching
:class:`~policy_event_study.diagnostics.placebo_space.PlaceboDistribution`.
There is no flag to disable it. A tau that has not been permuted cannot reach
the report, because the object that carries taus into the report cannot be
built without one.

The second rule is about anticipation. Events flagged
`anticipation_risk: high` -- and events carrying a confounder or a leak note --
are rendered in their own section with an identification discussion, and are
excluded from any pooled figure. See :func:`render_report`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import pandas as pd

from policy_event_study.data.prices import ReturnPanel
from policy_event_study.diagnostics.leave_one_out import (
    LeaveOneOutResult,
    leave_one_donor_out,
)
from policy_event_study.diagnostics.placebo_space import (
    PlaceboDistribution,
    in_space_placebos,
    p_value_table,
)
from policy_event_study.diagnostics.placebo_time import (
    InTimePlaceboResult,
    in_time_placebos,
)
from policy_event_study.diagnostics.power import PowerAnalysis, power_analysis
from policy_event_study.diagnostics.pretrends import (
    PreFitReport,
    PretrendTest,
    pre_fit_report,
    pretrend_test,
)
from policy_event_study.estimators.base import (
    EffectEstimate,
    EventSpec,
    EventStudyEstimator,
)
from policy_event_study.estimators.market_model import MarketModelEstimator
from policy_event_study.estimators.synthetic_control import SyntheticControlEstimator
from policy_event_study.estimators.synthetic_did import SyntheticDiDEstimator
from policy_event_study.events.schema import AnticipationRisk, PolicyEvent
from policy_event_study.reporting.tables import markdown_table as _markdown_table


class MissingPlaceboError(ValueError):
    """Raised when a point estimate would be reported without its placebos.

    The project brief states the rule as "never report a point estimate
    without its placebo distribution". This is that rule, enforced at the only
    point where estimates become report content.
    """


@dataclass(frozen=True)
class EventResult:
    """Everything the report needs about one event and one treated unit."""

    event: PolicyEvent
    spec: EventSpec
    treated_unit: str
    estimates: Mapping[str, EffectEstimate]
    placebos: Mapping[str, PlaceboDistribution]
    in_time: Mapping[str, InTimePlaceboResult] = field(default_factory=dict)
    pre_fit: Mapping[str, PreFitReport] = field(default_factory=dict)
    pretrends: Mapping[str, PretrendTest] = field(default_factory=dict)
    leave_one_out: Mapping[str, LeaveOneOutResult] = field(default_factory=dict)
    power: Mapping[str, PowerAnalysis] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Enforce the placebo rule at construction."""
        unpermuted = sorted(set(self.estimates) - set(self.placebos))
        if unpermuted:
            msg = (
                f"estimator(s) {unpermuted} produced a point estimate for "
                f"{self.treated_unit!r} on event {self.event.event_id!r} with no "
                "placebo distribution. Every reported effect carries its "
                "permutation reference distribution; there is no option to omit it"
            )
            raise MissingPlaceboError(msg)

    @property
    def separately_reported(self) -> bool:
        """True where pooling this event into a headline figure is unsound."""
        return self.event.requires_separate_reporting

    def effects_table(self) -> pd.DataFrame:
        """One row per estimator: effect, both placebo p-values, diagnostics."""
        rows: list[dict[str, object]] = []
        for name, estimate in self.estimates.items():
            placebo = self.placebos[name]
            pretrend = self.pretrends.get(name)
            loo = self.leave_one_out.get(name)
            analysis = self.power.get(name)
            timed = self.in_time.get(name)
            rows.append(
                {
                    "estimator": name,
                    "tau": estimate.tau,
                    "rmspe_ratio": estimate.rmspe_ratio,
                    "p_in_space": placebo.p_value("ratio"),
                    "p_in_time": timed.p_value("tau") if timed else float("nan"),
                    "min_attainable_p": placebo.min_attainable_p,
                    "pre_rmspe": estimate.pre_rmspe,
                    "pretrend_violated": pretrend.violated if pretrend else None,
                    "loo_sign_stable": loo.sign_stable if loo else None,
                    "loo_relative_shift": loo.relative_shift if loo else float("nan"),
                    "effective_donors": estimate.effective_weight_count,
                    "mde_80": analysis.mde if analysis else float("nan"),
                    "detectable": analysis.feasible if analysis else None,
                }
            )
        return pd.DataFrame(rows)


def run_event(
    panel: ReturnPanel,
    event: PolicyEvent,
    spec: EventSpec,
    treated_unit: str,
    *,
    estimators: Sequence[EventStudyEstimator] | None = None,
    n_time_placebos: int = 12,
) -> EventResult:
    """Run all three estimators and the full diagnostic battery for one unit.

    The market model is always included, whatever `estimators` says, because
    `CLAUDE.md` §4 requires every headline number to appear beside its named
    baseline on identical data and identical windows -- and because the
    pre-fit comparison in
    :func:`~policy_event_study.diagnostics.pretrends.pre_fit_report` is
    defined against it.
    """
    engines = list(
        estimators
        if estimators is not None
        else (
            MarketModelEstimator(),
            SyntheticControlEstimator(),
            SyntheticDiDEstimator(),
        )
    )
    if not any(isinstance(engine, MarketModelEstimator) for engine in engines):
        engines.insert(0, MarketModelEstimator())

    baseline = MarketModelEstimator().estimate(panel, spec, treated_unit)

    estimates: dict[str, EffectEstimate] = {}
    placebos: dict[str, PlaceboDistribution] = {}
    timed: dict[str, InTimePlaceboResult] = {}
    fits: dict[str, PreFitReport] = {}
    trends: dict[str, PretrendTest] = {}
    loos: dict[str, LeaveOneOutResult] = {}
    powers: dict[str, PowerAnalysis] = {}

    for engine in engines:
        estimate = engine.estimate(panel, spec, treated_unit)
        estimates[engine.name] = estimate
        placebos[engine.name] = in_space_placebos(engine, panel, spec, treated_unit)
        timed[engine.name] = in_time_placebos(
            engine, panel, spec, treated_unit, n_offsets=n_time_placebos
        )
        fits[engine.name] = pre_fit_report(estimate, baseline, panel, spec)
        trends[engine.name] = pretrend_test(estimate, spec, panel)
        loos[engine.name] = leave_one_donor_out(engine, panel, spec, treated_unit)
        powers[engine.name] = power_analysis(placebos[engine.name])

    return EventResult(
        event=event,
        spec=spec,
        treated_unit=treated_unit,
        estimates=estimates,
        placebos=placebos,
        in_time=timed,
        pre_fit=fits,
        pretrends=trends,
        leave_one_out=loos,
        power=powers,
    )


def render_event_section(result: EventResult) -> str:
    """Markdown for one event/unit, with every diagnostic attached."""
    event = result.event
    timing = result.spec.timing
    lines: list[str] = [
        f"### {event.event_id} — {result.treated_unit}",
        "",
        f"**Policy.** {event.policy}",
        "",
        f"**Source.** <{event.source_url}>",
        "",
        f"**Announcement.** {event.announcement_ts_utc.isoformat()} "
        f"({'time recovered' if event.time_known else 'TIME NOT RECOVERED'})",
        "",
        f"**Event-day resolution.** t0 = {timing.t0.date()} "
        f"({timing.convention}); "
        + (
            f"the {timing.straddling_day.date()} close-to-close return straddles "
            "the announcement and is excluded from day 0."
            if timing.straddle_is_excluded and timing.straddling_day is not None
            else "no trading day's return straddles the announcement."
        ),
        "",
        f"**Anticipation risk.** `{event.anticipation_risk}` — "
        f"expected direction `{event.expected_direction}`.",
        "",
    ]

    if result.separately_reported:
        lines += [
            "> **Reported separately; excluded from any pooled figure.**",
            ">",
            *_identification_caveat(event),
            "",
        ]

    lines += [
        "**Effects, with placebo inference.** Every row carries its own "
        "permutation p-value; none is reported without one.",
        "",
        _markdown_table(result.effects_table()),
        "",
    ]

    for name in result.estimates:
        placebo = result.placebos[name]
        lines += [
            f"<details><summary>{name}: exclusion ladder and power</summary>",
            "",
            _markdown_table(p_value_table(placebo)),
            "",
            result.power[name].narrative() if name in result.power else "",
            "",
            "</details>",
            "",
        ]

    return "\n".join(lines)


def _identification_caveat(event: PolicyEvent) -> list[str]:
    """Build the identification discussion a flagged event is required to carry."""
    lines: list[str] = []
    if event.anticipation_risk is AnticipationRisk.HIGH:
        lines += [
            "> *Anticipation.* The market already knew. A null estimate here is "
            "consistent both with 'the policy did not move these firms' and with "
            "'it moved them a fortnight earlier, when it was trailed'. The "
            "announcement-date return cannot separate the two, and no estimator "
            "in this study can either — the limitation is in the event, not in "
            "the method. Read the estimate as a bound on the *residual* surprise "
            "at the podium, not as the policy's effect.",
        ]
        if event.leak_note:
            lines += [f"> Curator's note: {event.leak_note}"]
    if event.confounders:
        lines += [
            "> *Confounding.* Same-day events: "
            f"{', '.join(event.confounders)}. `docs/research_plan.md` Phase B0 "
            "class (c): an announcement made inside a fiscal statement is "
            "essentially uninterpretable for a firm-level event study, because "
            "the donor pool cannot absorb a shock that hits UK domestic "
            "cyclicals through a different channel on the same day.",
        ]
    if event.leak_note and event.anticipation_risk is not AnticipationRisk.HIGH:
        lines += [
            f"> *Leak.* {event.leak_note} The effective event date is the leak, "
            "not the podium (`CLAUDE.md` §2.5); the estimate below uses the "
            "podium date and is therefore attenuated by an unknown amount.",
        ]
    return lines


def render_report(
    results: Sequence[EventResult],
    *,
    title: str = "Event study results",
    preamble: str = "",
) -> str:
    """Render the full report.

    Flagged events -- high anticipation, a confounder, or a recorded leak --
    are rendered in their own section and never enter a pooled figure. That
    separation is structural rather than editorial: the pooled section is
    built from `clean` and cannot see `flagged`.
    """
    clean = [result for result in results if not result.separately_reported]
    flagged = [result for result in results if result.separately_reported]

    sections = [f"# {title}", ""]
    if preamble:
        sections += [preamble, ""]

    sections += [
        "## Clean events",
        "",
        f"_{len(clean)} event/unit pair(s) with low or medium anticipation, no "
        "recorded confounder, and no recorded leak._",
        "",
    ]
    sections += [render_event_section(result) for result in clean] or [
        "_None yet._",
        "",
    ]

    sections += [
        "## Events reported separately",
        "",
        f"_{len(flagged)} event/unit pair(s). These are estimated and reported "
        "in full, with identification discussed. They are excluded from every "
        "pooled figure above._",
        "",
    ]
    sections += [render_event_section(result) for result in flagged] or [
        "_None yet._",
        "",
    ]

    return "\n".join(sections)
