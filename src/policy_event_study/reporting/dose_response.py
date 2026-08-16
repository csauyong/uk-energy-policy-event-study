"""Assemble the dose-response section of `reports/dose_response.md`.

Carries the same class of hard rule as
:mod:`policy_event_study.reporting.event_study`, which refuses to render a
point estimate without its placebo distribution. Here there are two:

**No beta is rendered without its influence diagnostics.**
:class:`DoseResponseSection` refuses to construct without an
:class:`~policy_event_study.diagnostics.influence.InfluenceReport`. Several
hundred observations with five influential ones is the small-N problem wearing
a large-N regression as a costume, and a beta reported without the leverage
distribution behind it invites exactly that misreading.

**No beta is rendered without its bootstrap p-value floor.** That is enforced
one level down, as a required field on
:class:`~policy_event_study.estimators.dose_response.DoseResponseResult`, so a
design that cannot reach the level being claimed is visible at the call site
rather than discovered in review.

The sign-consistency falsification check is *not* required to construct --
curated events may legitimately contain no loosening announcement, in which
case the test cannot run. But its absence is rendered as an explicit
limitation rather than passing unremarked.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from policy_event_study.diagnostics.influence import InfluenceReport
from policy_event_study.diagnostics.sign_consistency import SignConsistencyResult
from policy_event_study.estimators.dose_response import (
    DoseResponseMDE,
    DoseResponseResult,
)
from policy_event_study.reporting.tables import markdown_table


class MissingInfluenceError(ValueError):
    """Raised when a beta would be reported without its influence diagnostics.

    The counterpart to
    :class:`~policy_event_study.reporting.event_study.MissingPlaceboError`, and
    enforced the same way: at the only point where an estimate becomes report
    content, with no flag to disable it.
    """


@dataclass(frozen=True)
class DoseResponseSection:
    """One estimated specification, with everything the report must carry."""

    result: DoseResponseResult
    mde: DoseResponseMDE
    influence: InfluenceReport | None
    sign_consistency: SignConsistencyResult | None = None
    label: str = "headline"

    def __post_init__(self) -> None:
        """Enforce the influence rule at construction."""
        if self.influence is None:
            msg = (
                f"specification {self.label!r} would report beta="
                f"{self.result.beta:.6f} with no influence diagnostics. Exposure "
                "is heavily right-skewed, so several hundred observations can be "
                "identified off a handful of names; the leverage distribution and "
                "top-k drop path are required alongside every beta, exactly as a "
                "placebo distribution is required alongside every synthetic-"
                "control effect"
            )
            raise MissingInfluenceError(msg)

    @property
    def trustworthy(self) -> bool:
        """Whether every structural check passed.

        Deliberately conjunctive, and deliberately *not* about the p-value. A
        significant beta that fails the drop path or the sign test is not a
        result; an insignificant one that passes both is an informative null.
        """
        checks = [
            self.result.detectable_at(0.05),
            not self.result.at_the_floor,
            self.influence is not None and self.influence.survives_drop_path,
            self.influence is not None and self.influence.functional_form_agrees,
        ]
        if self.sign_consistency is not None and not self.sign_consistency.underpowered:
            checks.append(self.sign_consistency.passes)
        return all(checks)

    def headline_table(self) -> pd.DataFrame:
        """Build the one table a reader must see: floor and effective N included."""
        assert self.influence is not None  # guaranteed by __post_init__
        return pd.DataFrame(
            [
                {
                    "specification": self.label,
                    "beta": self.result.beta,
                    "p_wild": self.result.p_wild_bootstrap,
                    "p_floor": self.result.p_floor_bootstrap,
                    "weights": str(self.result.weight_scheme),
                    "p_randomisation": self.result.p_randomisation,
                    "mde_80": self.mde.mde,
                    "nominal_firms": self.influence.leverage.nominal_firms,
                    "effective_firms": self.influence.leverage.effective_firms,
                    "n_events": self.result.n_events,
                    "drop_path_survives": self.influence.survives_drop_path,
                    "forms_agree": self.influence.functional_form_agrees,
                }
            ]
        )

    def caveats(self) -> tuple[str, ...]:
        """Disclosures the report is required to carry for this specification."""
        assert self.influence is not None
        notes: list[str] = []
        if not self.result.detectable_at(0.05):
            notes.append(
                f"P-VALUE FLOOR: {self.result.weight_scheme} weights with "
                f"{self.result.n_events} clusters floor p at "
                f"{self.result.p_floor_bootstrap:.4f}, above 0.05. This design "
                "cannot reject at 5% for any effect size."
            )
        if self.result.at_the_floor:
            notes.append(
                "AT THE FLOOR: the bootstrap p-value is pinned at the design's "
                "minimum. That is a statement about resolution, not about how "
                "small the p-value is."
            )
        notes.append(f"INFLUENCE: {self.influence.verdict}")
        notes.extend(self.influence.notes)
        if self.sign_consistency is None:
            notes.append(
                "FALSIFICATION NOT RUN: the mandate-versus-repeal sign test was "
                "not evaluated. The pooled beta is reported without it and that "
                "limitation stands."
            )
        else:
            notes.append(f"FALSIFICATION: {self.sign_consistency.verdict()}")
        return tuple(notes)

    def render(self) -> str:
        """Markdown for this specification."""
        assert self.influence is not None
        lines = [
            f"### {self.label}",
            "",
            "**MDE first.** " + self.mde.interpretation,
            "",
            markdown_table(self.headline_table()),
            "",
            "**Top-k drop path.** A beta that dies at k = 3 is a statement about "
            "three firms, not about exposure.",
            "",
            markdown_table(self.influence.table()),
            "",
            "**Leverage.**",
            "",
            markdown_table(
                self.influence.leverage.summary()
                .to_frame("value")
                .reset_index(names="metric")
            ),
            "",
        ]
        if self.sign_consistency is not None:
            lines += [
                "**Falsification: mandate versus repeal.**",
                "",
                markdown_table(
                    self.sign_consistency.summary()
                    .to_frame("value")
                    .reset_index(names="metric")
                ),
                "",
            ]
        lines += ["**Caveats.**", ""]
        lines += [f"- {note}" for note in self.caveats()]
        lines += [""]
        return "\n".join(lines)
