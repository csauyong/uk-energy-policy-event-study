"""Deductive event discovery. Invoked by `make chronology`.

Inverts the earlier workflow. Rather than sweeping gov.uk search and filtering
the results -- a search-ranking exercise whose recall cannot be audited -- this
walks the declared `taxonomy` grid of policy families x lifecycle stages and
answers each cell from a published chronology.

Writes `data/events/chronology_<vintage>.md`: the completeness grid, the dated
instrument references behind it with page-level citations, and an explicit
list of the cells no source answered. **An unanswered cell is a result**, and
it is the thing a search sweep can never show you.

Discovery only. Timestamps come from the gov.uk content API.
"""

from __future__ import annotations

import sys
from collections import defaultdict

import pandas as pd

from policy_event_study.events.chronology import (
    Briefing,
    DatedReference,
    briefing_pages,
    enumerate_collection,
    extract_dated_references,
    search_briefings,
)
from policy_event_study.events.taxonomy import FAMILIES, LifecycleStage
from policy_event_study.paths import EVENTS_DIR

#: Words that mark a reference as belonging to a lifecycle stage. Coarse on
#: purpose: the grid is a prompt for a curator, not a classifier whose output
#: is trusted.
STAGE_MARKERS: dict[LifecycleStage, tuple[str, ...]] = {
    LifecycleStage.CONSULTATION_LAUNCH: (
        "consultation on",
        "consulted on",
        "sought views",
    ),
    LifecycleStage.CONSULTATION_OUTCOME: (
        "consultation response",
        "response to the consultation",
        "government response",
    ),
    LifecycleStage.STRATEGY: ("strategy", "roadmap", "plan"),
    LifecycleStage.REGULATIONS_LAID: (
        "regulations",
        "laid before",
        "came into force",
        "statutory instrument",
    ),
    LifecycleStage.SCHEME_LAUNCH: (
        "launched",
        "opened",
        "introduced",
        "came into effect",
    ),
    LifecycleStage.SCHEME_AMENDMENT: (
        "amended",
        "uplift",
        "increased",
        "raised",
        "changed",
    ),
    LifecycleStage.SCHEME_EXTENSION: ("extended", "extension"),
    LifecycleStage.SCHEME_CLOSURE: (
        "closed",
        "scrapped",
        "cancelled",
        "ended",
        "withdrawn",
    ),
    LifecycleStage.TARGET_CHANGE: (
        "target",
        "phase out",
        "phased out",
        "delayed",
        "pushed back",
        "commitment",
    ),
    LifecycleStage.REVIEW: ("review", "evaluation", "reported on"),
}


def classify(reference: DatedReference) -> list[LifecycleStage]:
    """Which lifecycle stages a reference plausibly speaks to."""
    lowered = reference.sentence.lower()
    return [
        stage
        for stage, markers in STAGE_MARKERS.items()
        if any(marker in lowered for marker in markers)
    ]


def main() -> int:
    """Walk the taxonomy and build the chronology document."""
    vintage = pd.Timestamp.now(tz="UTC").date().isoformat()
    print(f"building chronology (vintage {vintage}) ...")

    briefings: dict[str, Briefing] = {}
    family_terms: dict[str, tuple[str, ...]] = {}
    for family in FAMILIES:
        # Match terms classify sentences; queries only find documents.
        family_terms[family.key] = family.match_terms or family.chronology_queries
        for query in family.chronology_queries:
            for briefing in search_briefings(query, limit=4):
                briefings.setdefault(briefing.code, briefing)
    print(f"  {len(briefings)} distinct briefing(s) discovered")

    references: list[DatedReference] = []
    unreadable: list[Briefing] = []
    html_only: list[str] = []
    for briefing in briefings.values():
        pages = briefing_pages(briefing)
        if len(pages) == 1:
            html_only.append(briefing.code)
        if not pages:
            unreadable.append(briefing)
            continue
        found = extract_dated_references(briefing, pages)
        references.extend(found)
        print(
            f"    {briefing.code:12} {len(pages):3d}p  {len(found):4d} refs  {briefing.title[:44]}"
        )
    print(
        f"  {len(references)} dated reference(s); {len(unreadable)} briefing(s) unreadable"
    )

    # Assign references to families and stages.
    cells: dict[tuple[str, str], list[DatedReference]] = defaultdict(list)
    for reference in references:
        for family in FAMILIES:
            if not reference.matches_family(family_terms[family.key]):
                continue
            for stage in classify(reference):
                cells[(family.key, str(stage))].append(reference)

    collections: dict[str, int] = {}
    for family in FAMILIES:
        for slug in family.collection_hints:
            documents = enumerate_collection(slug)
            if documents:
                collections[slug] = len(documents)

    total_cells = len(FAMILIES) * len(LifecycleStage)
    answered = sum(1 for key in cells if cells[key])
    newsworthy_gaps = [
        (family.key, stage)
        for family in FAMILIES
        for stage in LifecycleStage
        if stage.typically_newsworthy and not cells.get((family.key, str(stage)))
    ]

    lines = [
        "# Policy chronology — deductive discovery",
        "",
        f"Generated by `scripts/build_chronology.py`, vintage {vintage}. "
        "**Regenerate rather than edit.**",
        "",
        "## Why this replaces the search sweep",
        "",
        "The earlier `candidates.md` was built by sweeping gov.uk search and "
        "filtering. That is a search-ranking exercise, and its recall cannot be "
        "audited — you cannot enumerate what a ranking did not return. It also "
        "failed *directionally*: twelve technical queries did not surface the "
        "September 2023 rollback at all, because large cross-cutting "
        "announcements are written in general language and scheme adjustments "
        "in technical language.",
        "",
        "This document answers a declared grid of policy families x lifecycle "
        "stages from published chronologies instead. **An unanswered cell is a "
        "result**: a reader can open the same briefing and check it.",
        "",
        "## Sources read",
        "",
        f"- {len(briefings)} House of Commons Library research briefings "
        f"({len(briefings) - len(unreadable)} readable, {len(html_only)} HTML-only)",
        f"- {len(collections)} gov.uk document collections enumerated",
        f"- {len(references)} dated instrument references extracted, each with a "
        "page-level citation",
        "",
    ]
    if unreadable:
        lines += [
            "**Unreadable briefings** (HTML-only; no PDF on the documents host). "
            "Recorded so the gap is visible:",
            "",
        ]
        lines += [f"- `{b.code}` — [{b.title}]({b.url})" for b in unreadable]
        lines += [""]
    if collections:
        lines += ["**Collections enumerated:**", ""]
        lines += [
            f"- `{slug}` — {count} documents" for slug, count in collections.items()
        ]
        lines += [""]

    lines += [
        "## Completeness grid",
        "",
        f"{answered} of {total_cells} cells answered. Cells are family x "
        "lifecycle stage; a cell is answered when at least one dated reference "
        "in a chronology speaks to it.",
        "",
        "| Family | " + " | ".join(s.value[:12] for s in LifecycleStage) + " |",
        "|---" * (len(LifecycleStage) + 1) + "|",
    ]
    for family in FAMILIES:
        row = [family.key]
        for stage in LifecycleStage:
            found = cells.get((family.key, str(stage)), [])
            mark = (
                str(len(found))
                if found
                else ("**·**" if stage.typically_newsworthy else "·")
            )
            row.append(mark)
        lines.append("| " + " | ".join(row) + " |")

    lines += [
        "",
        "`·` = no reference found. A **bold** dot marks a *newsworthy* stage "
        "with no reference — the cells most likely to be a genuine gap rather "
        "than a stage that family never reached.",
        "",
        f"### Newsworthy gaps ({len(newsworthy_gaps)})",
        "",
        "Check these against the briefings by hand before concluding the family "
        "never reached the stage.",
        "",
    ]
    for family_key, stage in newsworthy_gaps:
        lines.append(f"- `{family_key}` x `{stage.value}`")

    lines += [
        "",
        "## Dated references by family",
        "",
        "Each carries its briefing code and page. Months are as the chronology "
        "writes them — **no day is invented**; exact timestamps come from the "
        "gov.uk content API at the timestamping step.",
        "",
    ]
    for family in FAMILIES:
        family_refs = {
            id(ref): ref
            for stage in LifecycleStage
            for ref in cells.get((family.key, str(stage)), [])
        }
        if not family_refs:
            continue
        ordered = sorted(family_refs.values(), key=lambda r: r.period)
        lines += [
            f"### {family.key} — {family.label}",
            "",
            f"_Channels: {', '.join(family.exposure_channels)}. "
            f"{len(ordered)} reference(s)._",
            "",
        ]
        if family.note:
            lines += [f"> {family.note}", ""]
        for ref in ordered[:14]:
            lines.append(
                f"- **{ref.month_year}** — {ref.sentence[:220]} "
                f"`[{ref.source_code} p.{ref.page}]`"
            )
        if len(ordered) > 14:
            lines.append(f"- _… {len(ordered) - 14} more_")
        lines.append("")

    lines += [
        "## Next",
        "",
        "1. Read the grid for gaps; add instruments the briefings name but the "
        "extractor missed.",
        "2. Shortlist to ~25 by rule, before any leak checking — leak checks are "
        "the expensive step.",
        "3. Timestamp each survivor through "
        "`events.govuk.first_publication`, which reads the content API's change "
        "history. Never the search API's `public_timestamp`.",
        "4. Then Steps 2, 4 and 5 of `docs/event_curation_protocol.md`.",
        "",
    ]

    target = EVENTS_DIR / f"chronology_{vintage}.md"
    target.write_text("\n".join(lines), encoding="utf-8")
    print(f"  -> {target}")
    print(
        f"  grid: {answered}/{total_cells} cells answered, {len(newsworthy_gaps)} newsworthy gaps"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
