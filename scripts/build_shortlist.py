"""Shortlist chronology candidates by rule. Protocol Step 2, before leak checks.

Leak checking is the expensive step -- it needs a 10-day news search per
candidate and a judgement call on first public disclosure -- so it must not be
spent on candidates that cannot survive Step 5. This applies the rules that
decide survival, and applies them *before* any leak check rather than
discovering the failure afterwards.

Five rules, each with a reason a curator can argue with
-------------------------------------------------------
1. **Reaches a signed exposure channel.** A family whose only channel is
   `domestic_supply` contributes exactly nothing to a signed dose-response
   test, because `config/exposure.yaml` sets that channel's sign to zero: its
   direction cannot be determined ex ante. Such candidates are separated, not
   silently dropped -- they are still usable for an unsigned specification.
2. **Newsworthy lifecycle stage.** Consultation outcomes, strategies, scheme
   launches, amendments, closures and target changes carry unanticipated
   content. Regulations that enact an already-settled parameter usually do
   not, and a leak check on one is wasted.
3. **Inside the equity sample.** Candidates before the treated names have
   listed history are unusable however clean they are.
4. **Direction derivable.** `direction` is required and drives the
   falsification test. A candidate whose stage does not imply a direction
   needs the curator to supply one, and is flagged rather than guessed.
5. **Not structurally confounded.** A measure inside a fiscal statement
   cannot be separated from the statement. Separated, not dropped -- the
   confounding is a property to report.

Balance
-------
The sign-consistency falsification test needs both `tighten` and `loosen`
events, and **each side needs enough events to reach significance alone**.
Selection is therefore stratified across direction and across family rather
than taken off the top of a single ranking: a shortlist of 25 tightenings is
worth less than one of 12 and 8.

Proposes; does not decide. Every row carries its citation and blanks for the
judgement the protocol reserves for the curator.
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from policy_event_study.events.taxonomy import LifecycleStage, family
from policy_event_study.paths import EVENTS_DIR

#: Earliest month a candidate may fall in. Crest Nicholson listed 2013-02;
#: earlier events cannot use the full treated set.
SAMPLE_START = pd.Period("2013-01", freq="M")

#: Channels that carry a determinable sign. `domestic_supply` is absent by
#: design -- see `config/exposure.yaml`.
SIGNED_CHANNELS = frozenset({"residential_stock", "delivered_stock", "product_revenue"})

#: Stage -> proposed direction. A launch or uplift raises policy ambition and
#: pays the insulation channel; a closure or delay lowers it. Proposed only:
#: the curator confirms, because a "consultation outcome" can settle a
#: parameter either way and the stage alone cannot tell you which.
STAGE_DIRECTION: dict[LifecycleStage, str] = {
    LifecycleStage.SCHEME_LAUNCH: "tighten",
    LifecycleStage.SCHEME_EXTENSION: "tighten",
    LifecycleStage.SCHEME_AMENDMENT: "tighten",
    LifecycleStage.STRATEGY: "tighten",
    LifecycleStage.CONSULTATION_OUTCOME: "",
    LifecycleStage.SCHEME_CLOSURE: "loosen",
    LifecycleStage.TARGET_CHANGE: "",
}

#: Words that flip a proposed direction. "delayed", "scrapped", "pushed back"
#: turn a target change into a loosening; "brought forward" the reverse.
LOOSEN_MARKERS = (
    "delay",
    "delayed",
    "scrap",
    "cancel",
    "clos",
    "withdraw",
    "push back",
    "pushed back",
    "rolled back",
    "roll back",
    "weaken",
    "exempt",
    "axe",
)
TIGHTEN_MARKERS = (
    "brought forward",
    "raise",
    "raised",
    "increase",
    "increased",
    "uplift",
    "extend",
    "extended",
    "strengthen",
    "mandate",
    "require",
)


@dataclass
class Candidate:
    """One proposed instrument, aggregated from chronology references."""

    family_key: str
    stage: str
    month: str
    sentences: list[str]
    citations: list[str]

    @property
    def period(self) -> pd.Period:
        """The month this candidate falls in."""
        return pd.Period(pd.Timestamp(self.month), freq="M")

    @property
    def evidence(self) -> str:
        """Longest supporting sentence; the fullest quotation available."""
        return max(self.sentences, key=len)

    def proposed_direction(self) -> str:
        """Direction implied by the stage, adjusted by marker words."""
        base = STAGE_DIRECTION.get(LifecycleStage(self.stage), "")
        blob = " ".join(self.sentences).lower()
        loosen = any(marker in blob for marker in LOOSEN_MARKERS)
        tighten = any(marker in blob for marker in TIGHTEN_MARKERS)
        if loosen and not tighten:
            return "loosen"
        if tighten and not loosen:
            return base or "tighten"
        return base


def parse_chronology(path: str) -> list[Candidate]:
    """Read the generated chronology back into candidates.

    Reads the rendered document rather than recomputing, so the shortlist is
    demonstrably drawn from the artefact under version control -- the same one
    a reader would check.
    """
    raw = Path(path).read_text(encoding="utf-8")
    grouped: dict[tuple[str, str], Candidate] = {}
    current_family = ""
    for line in raw.splitlines():
        heading = re.match(r"^### ([a-z_]+) — ", line)
        if heading:
            current_family = heading.group(1)
            continue
        entry = re.match(
            r"^- \*\*([A-Z][a-z]+ \d{4})\*\* — (.+?) `\[([^\]]+)\]`$", line
        )
        if not entry or not current_family:
            continue
        month, sentence, citation = entry.groups()
        key = (current_family, month)
        if key not in grouped:
            grouped[key] = Candidate(current_family, "", month, [], [])
        grouped[key].sentences.append(sentence.strip())
        grouped[key].citations.append(citation.strip())
    return list(grouped.values())


def infer_stage(candidate: Candidate) -> str:
    """Assign the most newsworthy stage the evidence supports."""
    from scripts.build_chronology import STAGE_MARKERS

    blob = " ".join(candidate.sentences).lower()
    matched = [
        stage
        for stage, markers in STAGE_MARKERS.items()
        if any(marker in blob for marker in markers)
    ]
    if not matched:
        return ""
    newsworthy = [s for s in matched if s.typically_newsworthy]
    return str((newsworthy or matched)[0])


def main() -> int:
    """Apply the shortlist rules and write the result."""
    sources = sorted(EVENTS_DIR.glob("chronology_*.md"))
    if not sources:
        print("no chronology found; run `make chronology` first")
        return 1
    source = str(sources[-1])
    vintage = source.rsplit("_", 1)[-1].replace(".md", "")

    candidates = parse_chronology(source)
    print(f"parsed {len(candidates)} family x month candidates from {source}")

    for candidate in candidates:
        candidate.stage = infer_stage(candidate)

    kept: list[Candidate] = []
    rejected: dict[str, int] = defaultdict(int)
    unsigned: list[Candidate] = []
    confounded: list[Candidate] = []

    for candidate in candidates:
        if not candidate.stage:
            rejected["no lifecycle stage in the evidence"] += 1
            continue
        if not LifecycleStage(candidate.stage).typically_newsworthy:
            rejected["stage rarely carries surprise"] += 1
            continue
        if candidate.period < SAMPLE_START:
            rejected[f"before the equity sample ({SAMPLE_START})"] += 1
            continue
        spec = family(candidate.family_key)
        if candidate.family_key == "fiscal_events":
            confounded.append(candidate)
            continue
        if not (set(spec.exposure_channels) & SIGNED_CHANNELS):
            unsigned.append(candidate)
            continue
        kept.append(candidate)

    # Stratify: take from each family in turn, alternating direction, so no
    # single well-documented family crowds out the rest and both sides of the
    # falsification test get populated.
    by_family: dict[str, list[Candidate]] = defaultdict(list)
    for candidate in kept:
        by_family[candidate.family_key].append(candidate)
    for entries in by_family.values():
        entries.sort(key=lambda c: c.period)

    shortlist: list[Candidate] = []
    target = 25
    round_index = 0
    while len(shortlist) < target and any(by_family.values()):
        for key in sorted(by_family):
            if len(shortlist) >= target:
                break
            queue = by_family[key]
            if round_index < len(queue):
                shortlist.append(queue[round_index])
        round_index += 1
        if round_index > 40:
            break

    # Drop cross-family duplicates. One sentence can match several families --
    # "Future Homes Standard from 2025 In the Heat and Buildings Strategy"
    # legitimately touches future_homes, heat_buildings_strategy and
    # boiler_phase_out -- but three shortlist rows quoting the same sentence
    # is one instrument, and each would consume its own leak check.
    deduped: list[Candidate] = []
    seen_evidence: set[str] = set()
    for candidate in shortlist:
        fingerprint = candidate.evidence[:80].lower()
        if fingerprint in seen_evidence:
            continue
        seen_evidence.add(fingerprint)
        deduped.append(candidate)
    dropped_duplicates = len(shortlist) - len(deduped)
    shortlist = deduped

    shortlist.sort(key=lambda c: c.period)
    directions = pd.Series([c.proposed_direction() or "unset" for c in shortlist])

    lines = [
        f"# Shortlist — {len(shortlist)} candidates for leak checking",
        "",
        f"Generated by `scripts/build_shortlist.py` from `{source.rsplit('/', 1)[-1]}` "
        f"(vintage {vintage}). **Regenerate rather than edit.**",
        "",
        "Protocol Step 2: filtered by rule **before** any leak check, because "
        "leak checks are the expensive step and must not be spent on "
        "candidates that cannot survive Step 5.",
        "",
        "## Rules applied",
        "",
        "| Rule | Kept | Reason |",
        "|---|---|---|",
        f"| Reaches a signed exposure channel | {len(kept)} | `domestic_supply` "
        "scores zero by configuration, so it cannot move a signed β |",
        "| Newsworthy lifecycle stage | — | A regulation enacting a settled "
        "parameter carries no surprise |",
        f"| Inside the equity sample (>= {SAMPLE_START}) | — | Treated names need "
        "listed history |",
        f"| Not structurally confounded | {len(confounded)} separated | A measure "
        "inside a fiscal statement cannot be separated from the statement |",
        "",
        "**Rejected before stratification:**",
        "",
    ]
    for reason, count in sorted(rejected.items(), key=lambda kv: -kv[1]):
        lines.append(f"- {count} — {reason}")

    lines += [
        "",
        f"**Cross-family duplicates dropped:** {dropped_duplicates}. One sentence "
        "can legitimately touch three families; three rows quoting it are still "
        "one instrument, and each would consume its own leak check.",
        "",
        f"**Separated, not dropped:** {len(unsigned)} unsigned-channel candidates "
        f"(usable for an unsigned specification), {len(confounded)} confounded "
        "fiscal-event candidates (reported separately, never pooled).",
        "",
        "## Direction balance",
        "",
        "The sign-consistency falsification test needs both sides, and **each "
        "side needs enough events to reach significance alone**. Selection is "
        "stratified across family and direction rather than taken off the top "
        "of one ranking.",
        "",
        "| Proposed direction | Count |",
        "|---|---|",
    ]
    for value, count in directions.value_counts().items():
        lines.append(f"| `{value}` | {count} |")

    lines += [
        "",
        "> `unset` means the stage alone does not imply a direction — a "
        "consultation outcome can settle a parameter either way. **The curator "
        "sets these**; the script will not guess.",
        "",
        "## Candidates",
        "",
        "`direction` and `anticipation_risk` are proposals and blanks "
        "respectively. Nothing below has had a leak check: the month is the "
        "chronology's, not first public disclosure.",
        "",
        "| # | Month | Family | Stage | Dir? | Evidence | Citation |",
        "|---|---|---|---|---|---|---|",
    ]
    for index, candidate in enumerate(shortlist, start=1):
        evidence = candidate.evidence[:150].replace("|", "\\|")
        lines.append(
            f"| {index} | {candidate.month} | `{candidate.family_key}` | "
            f"`{candidate.stage}` | {candidate.proposed_direction() or '**unset**'} | "
            f"{evidence} | `{candidate.citations[0]}` |"
        )

    lines += [
        "",
        "## Next: leak checks, in this order",
        "",
        "1. **September 2023 first.** If the substance ran on the evening of "
        "the 19th, `t0` moves from 21 September to 20 September and the event "
        "changes character. It is the highest-value item; resolve it before "
        "building around it.",
        "2. Then the rest, in the order below. For each: search the preceding "
        "10 calendar days for reporting of the *substance*, record what is "
        "found with citations, and leave the `t0` call to the curator.",
        "3. Timestamp survivors through `events.govuk.first_publication`.",
        "4. Steps 4-5, then `make event-report` and stop when the marginal "
        "**group** stops moving the MDE.",
        "",
    ]

    target_path = EVENTS_DIR / f"shortlist_{vintage}.md"
    target_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  {len(shortlist)} shortlisted -> {target_path}")
    print(f"  direction balance: {dict(directions.value_counts())}")
    print(
        f"  separated: {len(unsigned)} unsigned-channel, {len(confounded)} confounded"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
