"""Completeness audit and deferral hunt. Protocol Step 7, before leak checks.

Two jobs the automated pipeline cannot do for itself.

**Audit.** The chronology extractor matches sentence-locally, so a family's
reference count understates its coverage: a chronology names its subject once
and then writes "the scheme". This measures the gap directly -- for each
family, how many sentences in the raw corpus mention it at all, against how
many the extractor kept -- so a thin family can be told apart from a genuinely
absent one before anybody calls it a gap.

**Deferrals.** Postponements are systematically under-extracted and they are
the events the design most needs. A deferral sentence usually names neither
the family nor an instrument word -- "this was pushed back to 2028" -- so it
fails both filters. It is also almost always a `loosen` event, and the
shortlist's loosen side is its thin side. Missing deferrals therefore biases
the sign-consistency test toward the side that cannot be tested.

Nothing here invents an instrument. Every candidate it surfaces is a quotation
from the cached corpus with its briefing code, for a curator to accept or
reject.
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict

import pandas as pd

from policy_event_study.events.chronology import (
    MONTH_YEAR,
    is_apparatus,
)
from policy_event_study.events.taxonomy import FAMILIES
from policy_event_study.paths import EVENTS_DIR

#: Language that marks a postponement, withdrawal or weakening. Deliberately
#: wider than the chronology extractor's `INSTRUMENT_WORDS`: the point is to
#: catch sentences that carry no instrument noun at all.
DEFERRAL_MARKERS: tuple[str, ...] = (
    "delay",
    "delayed",
    "postpone",
    "postponed",
    "pushed back",
    "put back",
    "deferred",
    "defer",
    "scrapped",
    "scrap",
    "cancelled",
    "cancel",
    "abandoned",
    "dropped",
    "rolled back",
    "roll back",
    "watered down",
    "weakened",
    "exempt",
    "exemption",
    "no longer",
    "will not proceed",
    "not proceed",
    "shelved",
    "paused",
    "axed",
    "reversed",
    "u-turn",
    "moved back",
    "extended the deadline",
    "relaxed",
)

#: A deferral quotation is only useful if it says *when*. Sentences with a
#: marker but no year cannot be dated and are counted, not listed.
YEAR = re.compile(r"\b(?:19|20)\d{2}\b")


def load_corpus() -> dict[str, list[str]]:
    """Load cached briefing text, keyed by briefing code."""
    directory = EVENTS_DIR / "briefing_cache"
    if not directory.exists():
        return {}
    return {
        path.stem: path.read_text(encoding="utf-8").split("\x0c")
        for path in sorted(directory.glob("*.txt"))
    }


def sentences_of(pages: list[str]) -> list[tuple[int, str]]:
    """Split cached pages into (page, sentence) pairs."""
    output: list[tuple[int, str]] = []
    for number, text in enumerate(pages, start=1):
        flattened = " ".join(text.split())
        for sentence in re.split(r"(?<=[.!?])\s+", flattened):
            if 40 < len(sentence) < 400:
                output.append((number, sentence))
    return output


def main() -> int:
    """Run the audit and write the report."""
    corpus = load_corpus()
    if not corpus:
        print("no cached briefings; run `make chronology` first")
        return 1
    vintage = pd.Timestamp.now(tz="UTC").date().isoformat()
    print(f"auditing {len(corpus)} cached briefings ...")

    all_sentences: list[tuple[str, int, str]] = [
        (code, page, sentence)
        for code, pages in corpus.items()
        for page, sentence in sentences_of(pages)
    ]
    print(f"  {len(all_sentences)} sentences in corpus")

    # --- coverage audit --------------------------------------------------
    coverage: list[dict[str, object]] = []
    for spec in FAMILIES:
        terms = spec.match_terms or spec.chronology_queries
        mentions = [
            (code, page, sentence)
            for code, page, sentence in all_sentences
            if any(term.lower() in sentence.lower() for term in terms)
        ]
        clean = [m for m in mentions if not is_apparatus(m[2])]
        dated = [m for m in clean if MONTH_YEAR.search(m[2])]
        coverage.append(
            {
                "family": spec.key,
                "mentions": len(mentions),
                "not_apparatus": len(clean),
                "dated": len(dated),
                "apparatus_share": (
                    1 - len(clean) / len(mentions) if mentions else 0.0
                ),
            }
        )

    # --- deferral hunt ---------------------------------------------------
    deferrals: dict[str, list[tuple[str, int, str]]] = defaultdict(list)
    undated = 0
    for code, page, sentence in all_sentences:
        lowered = sentence.lower()
        if not any(marker in lowered for marker in DEFERRAL_MARKERS):
            continue
        if is_apparatus(sentence):
            continue
        if not YEAR.search(sentence):
            undated += 1
            continue
        for spec in FAMILIES:
            terms = spec.match_terms or spec.chronology_queries
            if any(term.lower() in lowered for term in terms):
                deferrals[spec.key].append((code, page, sentence))
                break
        else:
            deferrals["_unattributed"].append((code, page, sentence))

    total_deferrals = sum(len(v) for v in deferrals.values())
    print(f"  {total_deferrals} dated deferral candidates ({undated} undated, skipped)")

    frame = pd.DataFrame(coverage).sort_values("dated", ascending=False)
    lines = [
        f"# Completeness audit — vintage {vintage}",
        "",
        f"Generated by `scripts/audit_completeness.py` over {len(corpus)} cached "
        f"briefings ({len(all_sentences)} sentences). **Regenerate rather than "
        "edit.**",
        "",
        "## 1. Coverage: what the extractor kept against what the corpus holds",
        "",
        "The chronology extractor matches sentence-locally, so a family's "
        "reference count understates its coverage — a chronology names its "
        'subject once and then writes "the scheme". This table separates a '
        "**thin** family from a genuinely **absent** one.",
        "",
        "| Family | Mentions | Not apparatus | Dated | Apparatus share |",
        "|---|---|---|---|---|",
    ]
    for row in frame.to_dict("records"):
        lines.append(
            f"| `{row['family']}` | {row['mentions']} | {row['not_apparatus']} | "
            f"{row['dated']} | {row['apparatus_share']:.0%} |"
        )

    absent = [r["family"] for r in frame.to_dict("records") if r["mentions"] == 0]
    thin = [
        r["family"]
        for r in frame.to_dict("records")
        if 0 < int(r["dated"]) < 3  # type: ignore[call-overload]
    ]
    lines += [
        "",
        f"**Genuinely absent** (no mention anywhere in the corpus): "
        f"{', '.join(f'`{f}`' for f in absent) if absent else '_none_'}. These "
        "need a different source, not a better extractor.",
        "",
        f"**Thin but present** (mentioned, few dated references): "
        f"{', '.join(f'`{f}`' for f in thin) if thin else '_none_'}. The "
        "instruments are in the corpus; the extractor is missing them. Check "
        "these by hand before calling them gaps.",
        "",
        "## 2. Deferrals — the systematically missing events",
        "",
        "A postponement usually names neither its family nor an instrument "
        'noun: *"this was pushed back to 2028"* fails both of the chronology '
        "extractor's filters. Deferrals are also almost always `loosen` "
        "events, and `loosen` is the thin side of the shortlist — so missing "
        "them biases the sign-consistency falsification test toward the side "
        "that cannot be tested.",
        "",
        f"{total_deferrals} dated candidates below, {undated} further undated "
        "ones skipped. Each is a quotation for a curator to accept or reject.",
        "",
    ]
    for key in sorted(deferrals, key=lambda k: -len(deferrals[k])):
        entries = deferrals[key]
        label = "unattributed to any family" if key == "_unattributed" else f"`{key}`"
        lines += [f"### {label} — {len(entries)}", ""]
        for code, page, sentence in entries[:10]:
            lines.append(f"- {sentence[:260]} `[{code} p.{page}]`")
        if len(entries) > 10:
            lines.append(f"- _… {len(entries) - 10} more_")
        lines.append("")

    lines += [
        "## 3. What to do with this",
        "",
        "1. Accept deferral candidates that are real instruments; each becomes "
        "a `loosen` shortlist row added **by hand**, with the citation above.",
        "2. Check the thin families by hand against their briefings.",
        "3. **Only then** re-check the direction balance. Balance is an outcome "
        "of completeness, not a selection criterion — choosing events to "
        "balance the test would be selecting on what the test is meant to "
        "measure.",
        "4. Re-verify every survivor's date through `events.govuk.first_publication`.",
        "",
    ]

    target = EVENTS_DIR / f"completeness_audit_{vintage}.md"
    target.write_text("\n".join(lines), encoding="utf-8")
    print(f"  -> {target}")
    print(f"  absent: {absent or 'none'}")
    print(f"  thin:   {thin or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
