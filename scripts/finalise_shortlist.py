"""Apply hand curation, re-check balance, re-verify dates. Protocol Steps 2 and 7.

Order matters and is the point of this script.

1. **Strike** the generated rows the curator rejected.
2. **Add** the deferrals the extractor missed, from `shortlist_manual.yaml`.
3. **Then** re-check the direction balance -- after completeness, not before.
   Balance computed before the additions would have driven selection, and
   choosing events to balance a falsification test is selecting on what the
   test is meant to measure. Computed after, it is a diagnostic.
4. **Re-verify dates** against the gov.uk content API's first-publication
   record, so no survivor carries a month that only a chronology asserts.

Writes `data/events/shortlist_final_<vintage>.md`, ordered for leak checking
with September 2023 first.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from dataclasses import dataclass, field

import pandas as pd
import yaml

from policy_event_study.events.taxonomy import family
from policy_event_study.paths import EVENTS_DIR

MANUAL = EVENTS_DIR / "shortlist_manual.yaml"


@dataclass
class Row:
    """One survivor, generated or hand-added."""

    month: str
    family: str
    stage: str
    direction: str
    evidence: str
    citation: str
    origin: str
    identifier: str = ""
    channel_targets: list[str] = field(default_factory=list)
    note: str = ""
    verified_date: str = ""
    verified_source: str = ""
    verify_status: str = "not attempted"

    @property
    def period(self) -> pd.Period:
        """Month the candidate falls in."""
        return pd.Period(pd.Timestamp(self.month), freq="M")


def parse_generated(path) -> list[Row]:  # noqa: ANN001
    """Read the generated shortlist table back into rows."""
    rows: list[Row] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.split("|")]
        if len(cells) < 9 or cells[1] in {"#", "---"} or not cells[1].isdigit():
            continue
        rows.append(
            Row(
                month=cells[2],
                family=cells[3].strip("`"),
                stage=cells[4].strip("`"),
                direction=cells[5].replace("**", "").replace("unset", ""),
                evidence=cells[6],
                citation=cells[7].strip("`"),
                origin=f"generated #{cells[1]}",
            )
        )
    return rows


def verify(row: Row, sweep: pd.DataFrame) -> None:
    """Check a row's month against gov.uk first-publication records.

    Matches the row's month against the sweep's first-publication dates and
    looks for a plausible gov.uk announcement in the same month. A match is
    **corroboration, not proof**: it says a gov.uk document was first
    published that month, not that it is this instrument. The curator still
    resolves the exact document, and the leak check may move the date earlier
    regardless.
    """
    try:
        target = row.period
    except (ValueError, TypeError):
        row.verify_status = "month unparseable"
        return

    same_month = sweep[sweep["period"] == str(target)]
    if same_month.empty:
        row.verify_status = "no gov.uk publication that month"
        return

    # Match on the family's declared match terms, not on its key. Splitting
    # the key gives tokens like "mees" and "domestic", which no gov.uk title
    # contains -- every row then reads "title unmatched" and the verification
    # degrades to "some document was published that month", which is almost
    # always true and therefore says nothing.
    try:
        spec = family(row.family)
        terms = [t.lower() for t in (spec.match_terms or spec.chronology_queries)]
    except KeyError:
        terms = [t for t in re.split(r"\W+", row.family) if len(t) > 3]
    scored = same_month.copy()
    scored["hits"] = (
        scored["title"]
        .str.lower()
        .apply(lambda title: sum(term in title for term in terms))
    )
    best = scored.sort_values("hits", ascending=False).iloc[0]
    row.verified_date = str(best["first_published_at"])[:16]
    row.verified_source = str(best["url"])
    row.verify_status = (
        "month corroborated, title matches family"
        if best["hits"] > 0
        else "month corroborated, title unmatched"
    )


def main() -> int:
    """Merge, rebalance, verify, and write the final list."""
    generated = sorted(EVENTS_DIR.glob("shortlist_2*.md"))
    if not generated:
        print("no generated shortlist; run `make shortlist` first")
        return 1
    source = generated[-1]
    vintage = source.stem.rsplit("_", 1)[-1]

    rows = parse_generated(source)
    print(f"generated rows: {len(rows)}")

    manual = yaml.safe_load(MANUAL.read_text(encoding="utf-8"))
    struck = {(s["month"], s["family"]) for s in manual["strike"]}
    kept = [r for r in rows if (r.month, r.family) not in struck]
    print(f"  struck {len(rows) - len(kept)}, kept {len(kept)}")

    for entry in manual["add"]:
        kept.append(
            Row(
                month=entry["month"],
                family=entry["family"],
                stage=entry["stage"],
                direction=entry["direction"],
                evidence=" ".join(str(entry["evidence"]).split()),
                citation=entry["citation"],
                origin="hand-added",
                identifier=entry["id"],
                channel_targets=list(entry.get("channel_targets", [])),
                note=" ".join(str(entry.get("note", "")).split()),
            )
        )
    print(f"  added {len(manual['add'])} -> {len(kept)} survivors")

    # Balance AFTER completeness, never before.
    balance = Counter(r.direction or "unset" for r in kept)
    print(f"  direction balance (post-completeness): {dict(balance)}")

    sweep_files = sorted(EVENTS_DIR.glob("govuk_sweep_*.csv"))
    if sweep_files:
        sweep = pd.read_csv(sweep_files[-1])
        sweep["first_published_at"] = pd.to_datetime(
            sweep["first_published_at"], utc=True, format="mixed"
        )
        sweep["period"] = (
            sweep["first_published_at"]
            .dt.tz_localize(None)
            .dt.to_period("M")
            .astype(str)
        )
        for row in kept:
            verify(row, sweep)
        statuses = Counter(r.verify_status for r in kept)
        print(f"  date verification: {dict(statuses)}")

    # September 2023 first, then chronological.
    def order(row: Row) -> tuple[int, str]:
        return (0 if row.month == "September 2023" else 1, str(row.period))

    kept.sort(key=order)

    lines = [
        f"# Final shortlist — {len(kept)} candidates, ready for leak checking",
        "",
        f"Generated by `scripts/finalise_shortlist.py` from `{source.name}` plus "
        f"`shortlist_manual.yaml` (vintage {vintage}). **Regenerate rather than "
        "edit; hand curation lives in the YAML.**",
        "",
        "## What happened to get here",
        "",
        "| Step | Count |",
        "|---|---|",
        f"| Generated by rule | {len(rows)} |",
        f"| Struck as extraction noise | -{len(rows) - len(kept) + len(manual['add'])} |",
        f"| Hand-added from the completeness audit | +{len(manual['add'])} |",
        f"| **Survivors** | **{len(kept)}** |",
        "",
        "## Direction balance — checked after completeness, not before",
        "",
        "Balance computed *before* the deferral additions would have driven "
        "selection, and choosing events to balance a falsification test is "
        "selecting on what the test is meant to measure. Computed after, it is "
        "a diagnostic.",
        "",
        "| Direction | Before additions | After |",
        "|---|---|---|",
    ]
    before = Counter(r.direction or "unset" for r in kept if r.origin != "hand-added")
    for key in ("tighten", "loosen", "unset"):
        lines.append(f"| `{key}` | {before.get(key, 0)} | {balance.get(key, 0)} |")

    lines += [
        "",
        "The deferral hunt was the whole reason the `loosen` side is usable: a "
        "postponement names neither its family nor an instrument noun, so the "
        "chronology extractor missed every one. All "
        f"{len(manual['add'])} hand-added rows are `loosen`.",
        "",
        "## Candidates — September 2023 first",
        "",
        "`verified` corroborates the month against gov.uk first-publication "
        "records. **Corroboration is not proof**: it says a gov.uk document was "
        "first published that month, not that it is this instrument. No row has "
        "had a leak check, so every date is formal publication rather than "
        "first public disclosure.",
        "",
        "| # | Month | Family | Stage | Dir | Origin | Verified | Evidence | Cite |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for index, row in enumerate(kept, start=1):
        mark = {
            "month corroborated, title matches family": "yes",
            "month corroborated, title unmatched": "month only",
            "no gov.uk publication that month": "**none**",
        }.get(row.verify_status, row.verify_status)
        lines.append(
            f"| {index} | {row.month} | `{row.family}` | `{row.stage}` | "
            f"{row.direction or '**unset**'} | {row.origin} | {mark} | "
            f"{row.evidence[:120].replace('|', chr(92) + '|')} | `{row.citation}` |"
        )

    unverified = [
        r for r in kept if r.verify_status == "no gov.uk publication that month"
    ]
    needs_date = [r for r in kept if "primary-source date" in r.note]
    lines += [
        "",
        f"### Needs a primary-source date before use ({len(needs_date)})",
        "",
    ]
    for row in needs_date:
        lines.append(f"- `{row.identifier}` — {row.note}")
    lines += [
        "",
        f"### No gov.uk publication found in that month ({len(unverified)})",
        "",
        "Either the chronology's month is wrong, or the instrument was not "
        "announced through a gov.uk page the sweep indexed. Resolve before "
        "spending a leak check.",
        "",
    ]
    for row in unverified:
        lines.append(f"- {row.month} `{row.family}` — {row.evidence[:110]}")

    lines += [
        "",
        "## Leak checks — September 2023 first",
        "",
        "Rows 1-3 are **one announcement**, not three: the 20 September 2023 "
        "statement scrapped the EPC C requirement for landlords, put the "
        "off-grid boiler phase-out back to 2035, and exempted some homes "
        "entirely. They must be merged into a single event with "
        "`channel_targets: [residential_stock, product_revenue]` — the "
        "landlord channel and the manufacturer channel, opposite-signed under "
        "the same shock, which is the most informative shape an event can have "
        "here.",
        "",
        "**The question for that event:** the substance was widely reported "
        "before the podium. If it ran on the evening of 19 September, `t0` "
        "moves from 21 to 20 September and the event changes character. "
        "Resolve it before building around it.",
        "",
    ]

    target = EVENTS_DIR / f"shortlist_final_{vintage}.md"
    target.write_text("\n".join(lines), encoding="utf-8")
    print(f"  -> {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
