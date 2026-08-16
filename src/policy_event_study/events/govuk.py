"""Fetch candidate announcements from the gov.uk APIs.

`docs/event_curation_protocol.md` Steps 1-3, executed by rule rather than by
hand, so the candidate list is reproducible and auditable rather than a
product of whoever swept and what they remembered.

The timestamp trap
------------------
**The search API's ``public_timestamp`` is the last-updated stamp, not first
publication.** For the MEES landlord guidance it reads 2026-05-05 against a
true first publication of 2017-10-01 -- an 8.5-year error that would silently
redate the event and put the "announcement return" nowhere near the
announcement.

So discovery and dating are split:

* the **search API** finds candidates (it is a search index, and that is all
  it is used for);
* the **content API** dates them, from ``details.change_history``, where the
  entry noted "First published." is authoritative. ``first_published_at`` is
  used as a fallback and is itself occasionally the migration date rather than
  the original, which is why the change history is preferred.

Time of day
-----------
Many gov.uk pages carry a midnight ``first_published_at``, meaning the time was
never recorded. That is reported as ``time_known=False`` rather than guessed,
and the event-day resolver already forces the conservative convention for such
rows. Press releases and speeches more often carry a real time.

What this module does not do
----------------------------
It does not decide anything. It returns candidates with their provenance for a
human to filter, date-check against Step 2's leak search, and score for
surprise. Steps 4-6 are judgement and are not automated.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Final

import pandas as pd

SEARCH_ENDPOINT: Final[str] = "https://www.gov.uk/api/search.json"
CONTENT_ENDPOINT: Final[str] = "https://www.gov.uk/api/content"
USER_AGENT: Final[str] = "uk-energy-policy-event-study/0.1 (research)"

#: Document types that can carry a datable announcement. Guidance pages are
#: included because some policy changes appear only there, but they are the
#: most likely to carry an update timestamp rather than an announcement one.
ANNOUNCEMENT_TYPES: Final[tuple[str, ...]] = (
    "press_release",
    "news_story",
    "speech",
    "written_statement",
    "oral_statement",
    "policy_paper",
    "consultation_outcome",
    "detailed_guide",
    "guidance",
    "impact_assessment",
    "statutory_guidance",
)

#: Protocol Step 1 sweep categories. Deliberately category terms rather than
#: headlines -- sweeping headlines finds what was memorable, which is
#: selection on the outcome by another route.
SWEEP_QUERIES: Final[tuple[tuple[str, str], ...]] = (
    ("mees_domestic", "minimum energy efficiency standard private rented"),
    ("mees_nondomestic", "non-domestic minimum energy efficiency standard"),
    ("epc_reform", "energy performance certificate reform assessment"),
    ("future_homes", "Future Homes Standard building regulations"),
    ("part_l", "building regulations conservation of fuel and power"),
    ("boiler_policy", "gas boiler phase out heating buildings"),
    ("heat_pump", "boiler upgrade scheme heat pump grant"),
    ("retrofit_schemes", "energy company obligation insulation scheme"),
    ("gbis", "Great British Insulation Scheme"),
    ("warm_homes", "Warm Homes Plan home upgrade grant"),
    ("heat_buildings", "heat and buildings strategy"),
    ("uk_ets", "UK Emissions Trading Scheme scope buildings"),
    # Cross-cutting queries. Added after the first sweep missed the September
    # 2023 net-zero rollback -- docs/data_inventory.md §8 calls it the
    # highest-value single event in the study. The technical queries above did
    # not rank it, because a major cross-cutting announcement is written in
    # general language ("net zero", "cost of living") while a scheme change is
    # written in technical language. Sweeping only the technical vocabulary
    # biases the list toward small scheme adjustments and away from the large
    # directional shocks, which is the wrong direction to be biased in.
    ("net_zero_direction", "net zero approach households costs"),
    ("net_zero_rollback", "net zero delay boiler cars pragmatic"),
    ("energy_bills", "energy bills support households heating costs"),
    ("housing_standards", "decent homes standard social rented housing"),
)


@dataclass(frozen=True)
class Candidate:
    """One discovered announcement with its provenance."""

    query_key: str
    title: str
    url: str
    document_type: str
    organisations: tuple[str, ...]
    search_timestamp: str
    first_published_at: str | None
    first_published_note: str | None
    change_history_entries: int

    @property
    def time_known(self) -> bool:
        """False where the recorded first publication carries no time of day."""
        if not self.first_published_at:
            return False
        stamp = pd.Timestamp(self.first_published_at)
        london = stamp.tz_convert("Europe/London") if stamp.tzinfo else stamp
        return not (london.hour == 0 and london.minute == 0)

    @property
    def redating_gap_days(self) -> int | None:
        """Days between the search stamp and true first publication.

        The size of the error that using the search API's timestamp would have
        introduced. Reported so the trap is visible per row rather than
        asserted once in a docstring.
        """
        if not self.first_published_at:
            return None
        return int(
            (
                pd.Timestamp(self.search_timestamp).tz_convert("UTC")
                - pd.Timestamp(self.first_published_at).tz_convert("UTC")
            ).days
        )


def _get(url: str, *, timeout: int = 30) -> dict[str, Any]:
    """Fetch and parse JSON from a gov.uk endpoint."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload: dict[str, Any] = json.loads(response.read())
    return payload


def search(
    query: str,
    *,
    count: int = 40,
    organisations: Sequence[str] = ("department-for-energy-security-and-net-zero",),
    document_types: Sequence[str] = ANNOUNCEMENT_TYPES,
) -> list[dict[str, Any]]:
    """Discover candidates via the gov.uk search API.

    Source: https://www.gov.uk/api/search.json
    Licence: OGL v3.
    Vintage: live index; the sweep caches its output with a download date.
    Publication lag: none for the index. **The `public_timestamp` it returns is
        the last-updated stamp and must not be used as an announcement date** --
        see :func:`first_publication`.

    `organisations` is passed as a filter but deliberately left overridable and
    can be set empty: energy-efficiency policy moves between departments over
    the sample (DECC, BEIS, DESNZ, MHCLG), and filtering to today's owner would
    silently truncate the early history.
    """
    params: list[tuple[str, str]] = [
        ("q", query),
        ("count", str(count)),
        (
            "fields",
            "title,link,public_timestamp,content_store_document_type,organisations",
        ),
    ]
    params.extend(
        ("filter_content_store_document_type", kind) for kind in document_types
    )
    params.extend(("filter_organisations", org) for org in organisations)
    payload = _get(f"{SEARCH_ENDPOINT}?{urllib.parse.urlencode(params)}")
    results: list[dict[str, Any]] = payload.get("results", [])
    return results


def first_publication(path: str) -> tuple[str | None, str | None, int]:
    """Read true first publication from the content API's change history.

    Returns
    -------
    tuple[str | None, str | None, int]
        ``(timestamp, note, n_change_history_entries)``. The timestamp is the
        earliest change-history entry, which for gov.uk is the original
        publication even when the page has since been rewritten. Falls back to
        ``first_published_at`` when no change history exists, and that fallback
        is flagged in the note because it is occasionally the content-migration
        date rather than the original announcement.
    """
    payload = _get(f"{CONTENT_ENDPOINT}{path}")
    history: list[dict[str, Any]] = payload.get("details", {}).get("change_history", [])
    if history:
        earliest = min(
            history, key=lambda entry: str(entry.get("public_timestamp", ""))
        )
        return (
            str(earliest.get("public_timestamp")),
            str(earliest.get("note", "")).strip(),
            len(history),
        )
    fallback = payload.get("first_published_at")
    return (
        str(fallback) if fallback else None,
        "no change_history; first_published_at used and may be a migration date",
        0,
    )


def sweep(
    queries: Iterable[tuple[str, str]] = SWEEP_QUERIES,
    *,
    count: int = 40,
    organisations: Sequence[str] = (),
    pause_seconds: float = 0.3,
    resolve_dates: bool = True,
) -> list[Candidate]:
    """Run the Step 1 sweep and resolve Step 2's first-publication timestamps.

    Deliberately polite: a short pause between content-API calls, since this
    issues one request per candidate.
    """
    seen: set[str] = set()
    candidates: list[Candidate] = []

    for key, query in queries:
        for result in search(query, count=count, organisations=organisations):
            link = str(result.get("link", ""))
            if not link or link in seen:
                continue
            seen.add(link)

            stamp, note, entries = (None, None, 0)
            if resolve_dates:
                try:
                    stamp, note, entries = first_publication(link)
                    time.sleep(pause_seconds)
                except (urllib.error.URLError, OSError, ValueError, KeyError):
                    note = "content API lookup failed; date unresolved"

            orgs = result.get("organisations") or []
            candidates.append(
                Candidate(
                    query_key=key,
                    title=str(result.get("title", "")).strip(),
                    url=f"https://www.gov.uk{link}",
                    document_type=str(result.get("content_store_document_type", "")),
                    organisations=tuple(
                        str(org.get("acronym") or org.get("title", "")) for org in orgs
                    ),
                    search_timestamp=str(result.get("public_timestamp", "")),
                    first_published_at=stamp,
                    first_published_note=note,
                    change_history_entries=entries,
                )
            )
    return candidates


def to_frame(candidates: Sequence[Candidate]) -> pd.DataFrame:
    """Candidates as a frame, newest first publication last."""
    frame = pd.DataFrame(
        [
            {
                "query_key": candidate.query_key,
                "first_published_at": candidate.first_published_at,
                "time_known": candidate.time_known,
                "document_type": candidate.document_type,
                "organisations": ";".join(candidate.organisations),
                "title": candidate.title,
                "url": candidate.url,
                "search_timestamp": candidate.search_timestamp,
                "redating_gap_days": candidate.redating_gap_days,
                "change_history_entries": candidate.change_history_entries,
                "note": candidate.first_published_note,
            }
            for candidate in candidates
        ]
    )
    if frame.empty:
        return frame
    return frame.sort_values("first_published_at", na_position="first").reset_index(
        drop=True
    )
