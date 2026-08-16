"""Promote the a-priori inventory into the event dictionary. Freeze step.

Converts `inventory_apriori_*.yaml` plus `date_resolutions_*.yaml` into
`data/events/uk_energy_policy_events.csv`, applying every admissibility rule
the project has accumulated. Deliberately conservative: a row that cannot
satisfy the validator does not enter, and the reason it did not is printed.

Promotion rules, each of which drops rows
------------------------------------------
* `date_grade` C -- a month is not a trading session.
* No resolved day.
* **No source URL.** `source_url` is required precisely so an unauditable row
  cannot reach an estimate; the inventory's section 6 maps sources to 29 of its 49
  rows, so the rest are held back rather than promoted with a blank.
* Dropped by the leak protocol.
* Scheduled commencements that merely enact an earlier decision -- kept in the
  inventory per Rule 0, but not independent observations of news.

Vocabulary bridge
-----------------
The inventory speaks in **exposure channels**; the event dictionary's
`affected_sectors` speaks in **universe treated-group keys**, and the
validator checks the latter against `config/universe.yaml`. The mapping
between them is one-to-one and is declared here rather than inferred.
"""

from __future__ import annotations

import re
import sys

import pandas as pd
import yaml

from policy_event_study.events.grouping import DEFAULT_MIN_SPACING_DAYS as SPACING_DAYS
from policy_event_study.events.inventory import load_inventory, usable_events
from policy_event_study.events.schema import OPTIONAL_COLUMNS, REQUIRED_COLUMNS
from policy_event_study.paths import EVENTS_CSV, EVENTS_DIR

#: Exposure channel -> universe treated-group key. One-to-one, declared rather
#: than inferred: the two vocabularies exist for different reasons and a
#: silent mismatch would produce an empty treated set at estimation time.
CHANNEL_TO_SECTOR = {
    "residential_stock": "residential_landlords",
    "delivered_stock": "housebuilders",
    "product_revenue": "insulation_and_materials",
    "domestic_supply": "utilities_and_suppliers",
}

#: Anticipation risk mapped from the inventory's leak-risk grading. A
#: confirmed leak is `high` by construction: the information was public before
#: the formal announcement, which is exactly what high anticipation means.
LEAK_TO_ANTICIPATION = {
    "confirmed": "high",
    "high": "high",
    "medium": "medium",
    "low": "low",
    "": "medium",
}


def section_six_sources(markdown: str) -> dict[int, str]:
    """Map inventory row numbers to the source URL recorded in section 6."""
    sources: dict[int, str] = {}
    for line in markdown.splitlines():
        if not line.startswith("- "):
            continue
        rows = re.search(r"\(rows? ([\d,\s\-]+)\)", line)
        urls = re.findall(r"\((https?://[^)\s]+)\)", line)
        if not rows or not urls:
            continue
        for token in re.split(r"[,\s]+", rows.group(1)):
            cleaned = token.strip("-")
            if cleaned.isdigit():
                sources.setdefault(int(cleaned), urls[0])
    return sources


def main() -> int:
    """Build and write the event dictionary."""
    inventory = load_inventory()
    markdown = sorted(EVENTS_DIR.glob("inventory_apriori_*.md"))[-1].read_text(
        encoding="utf-8"
    )
    sources = section_six_sources(markdown)

    resolutions_path = sorted(EVENTS_DIR.glob("date_resolutions_*.yaml"))[-1]
    resolutions = yaml.safe_load(resolutions_path.read_text(encoding="utf-8"))
    dropped = {
        entry["id"]
        for entry in resolutions.get("leak_searches", [])
        if str(entry.get("outcome", "")).upper().startswith("DROP")
    }
    moved = {
        entry["id"]: str(entry["t0_date"])
        for entry in resolutions.get("leak_searches", [])
        if entry.get("t0_date")
    }
    stamped = {
        entry["id"]: str(entry["resolved_timestamp"])
        for entry in resolutions.get("leak_searches", [])
        if entry.get("resolved_timestamp")
    }

    rows: list[dict[str, str]] = []
    rejected: dict[str, list[str]] = {}

    usable_ids = {i.id for i in usable_events(inventory)}

    def reject(identifier: str, reason: str) -> None:
        rejected.setdefault(reason, []).append(identifier)

    for position, instrument in enumerate(inventory, start=1):
        if instrument.id in dropped:
            reject(instrument.id, "dropped by the leak protocol (gradual disclosure)")
            continue
        if instrument.id not in usable_ids:
            reject(instrument.id, "date_grade C: a month is not a trading session")
            continue
        if instrument.scheduled:
            reject(
                instrument.id,
                "scheduled commencement -- kept in the inventory, not an event",
            )
            continue
        day = instrument.resolved_day
        if day is None:
            reject(instrument.id, "no resolved day")
            continue
        url = sources.get(position, "")
        if not url:
            reject(instrument.id, "no source URL in inventory section 6")
            continue

        # Leak protocol may have moved the effective date earlier.
        effective = moved.get(instrument.id, str(day.date()))

        if instrument.id in stamped:
            timestamp = pd.Timestamp(stamped[instrument.id]).tz_convert("UTC")
            time_known = "true"
        else:
            timestamp = pd.Timestamp(f"{effective}T00:00:00Z")
            time_known = "false"

        sectors = sorted(
            {
                CHANNEL_TO_SECTOR[channel]
                for channel in instrument.channel_targets
                if channel in CHANNEL_TO_SECTOR
            }
        )
        if not sectors:
            reject(
                instrument.id,
                "no exposure channel maps to a universe treated group",
            )
            continue

        rows.append(
            {
                "date": str(timestamp.tz_convert("Europe/London").date()),
                "announcement_timestamp_utc": timestamp.isoformat(),
                "policy": instrument.title.replace(",", ";")[:180],
                "source_url": url,
                "anticipation_risk": LEAK_TO_ANTICIPATION.get(
                    instrument.leak_risk, "medium"
                ),
                "expected_direction": (
                    "ambiguous"
                    if instrument.direction == "mixed"
                    else (
                        "negative" if instrument.direction == "loosen" else "positive"
                    )
                ),
                "affected_sectors": ";".join(sectors),
                "direction": (
                    "loosen"
                    if instrument.direction in {"loosen", "mixed"}
                    else "tighten"
                ),
                "event_id": instrument.id,
                "time_known": time_known,
                "scheduled": "false",
                "confounders": "fiscal_statement"
                if "fiscal" in instrument.families
                else "",
                "event_tags": ";".join(instrument.families),
                "channel_targets": ";".join(instrument.channel_targets),
                "surprise_note": instrument.note[:200],
                "leak_note": (
                    f"leak protocol: t0 moved to {moved[instrument.id]}"
                    if instrument.id in moved
                    else ""
                ),
                "notes": f"inventory row {position}; date_grade {instrument.date_grade}",
                "overlap_ack": "",
            }
        )

    frame = pd.DataFrame(rows, columns=[*REQUIRED_COLUMNS, *OPTIONAL_COLUMNS])
    frame = frame.sort_values("announcement_timestamp_utc").reset_index(drop=True)

    # Declare groupings for events inside the spacing threshold. Protocol
    # Step 6: `overlap_ack` declares that two announcements share return days
    # and belong in one cluster -- it does not waive the check. The estimator
    # still clusters on the group and still computes the p-value floor from
    # the group count, so acknowledging costs power rather than granting it.
    stamps = pd.to_datetime(frame["announcement_timestamp_utc"], utc=True)
    declared = 0
    for index in range(1, len(frame)):
        gap = (stamps.iloc[index] - stamps.iloc[index - 1]).days
        if gap < SPACING_DAYS:
            frame.loc[index, "overlap_ack"] = "true"
            frame.loc[index, "notes"] = (
                f"{frame.loc[index, 'notes']}; groups with "
                f"{frame.loc[index - 1, 'event_id']} ({gap}d apart)"
            )
            declared += 1

    frame.to_csv(EVENTS_CSV, index=False)
    print(f"declared {declared} grouping(s) for events inside the spacing threshold")

    print(f"promoted {len(frame)} of {len(inventory)} inventory rows -> {EVENTS_CSV}")
    print()
    print("held back:")
    for reason, ids in sorted(rejected.items(), key=lambda kv: -len(kv[1])):
        print(f"  {len(ids):2d}  {reason}")
        if reason.startswith("no source URL"):
            print(f"      {', '.join(ids[:6])}{' ...' if len(ids) > 6 else ''}")
    print()
    print(f"direction: {dict(frame['direction'].value_counts())}")
    print(f"anticipation: {dict(frame['anticipation_risk'].value_counts())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
