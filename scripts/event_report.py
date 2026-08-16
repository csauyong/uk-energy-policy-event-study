"""Per-event curation report. Invoked by `make event-report`.

Prints, for the curated event dictionary as it currently stands:

* resolved trading day under the LSE open/close convention, and whether a
  close-to-close return straddles the announcement;
* universe status resolution, including any per-event overrides applied and
  any units dropped for availability or an exclusion window;
* **grouping** -- events within the spacing threshold collapse by transitive
  closure (`docs/event_curation_protocol.md` Step 6);
* the p-value floor and MDE as a function of **group** count, recomputed over
  the current file, so Step 7's stopping rule is visible while curating.

The curve is keyed on groups rather than events deliberately. Two
announcements a week apart add a row to the dictionary and nothing to the
inference: they share return days, so they are one cluster, and the bootstrap
floor must be computed from the number of clusters. Reporting the curve on
event count would tell a curator that a nearby event bought power it did not.

Exits non-zero when validation finds anything fatal.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from policy_event_study.data.universe import (
    EventResolutionError,
    UniverseConfigError,
    load_universe,
)
from policy_event_study.estimators.dose_response import (
    WeightScheme,
    bootstrap_p_floor,
)
from policy_event_study.events.grouping import assign_event_groups
from policy_event_study.events.loader import load_events
from policy_event_study.events.schema import resolve_event_timing

RULE = "-" * 72
BOOTSTRAP_DRAWS = 2000


def _trading_calendar(start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
    """Business-day stand-in for the panel calendar.

    Adequate for the curation view: it resolves the open/close convention and
    the straddle, which is what a curator needs to see. The real panel calendar
    is the intersection of every listing's, and the estimator uses that one.
    """
    return pd.DatetimeIndex(pd.bdate_range(start=start, end=end, tz="UTC"))


def main() -> int:
    """Print the per-event curation report."""
    try:
        universe = load_universe()
    except (UniverseConfigError, FileNotFoundError) as exc:
        print(f"universe not loadable: {exc}")
        return 1

    events, report = load_events(known_sectors=universe.sector_keys, strict=False)
    print(report.render())
    print()

    if not events:
        print("No curated events yet. Nothing further to report.")
        print("Candidates and required fields: data/events/candidates.md")
        return 0 if report.ok else 1

    calendar = _trading_calendar(
        min(event.announcement_ts_utc for event in events) - pd.Timedelta(days=400),
        max(event.announcement_ts_utc for event in events) + pd.Timedelta(days=60),
    )

    for event in events:
        print(RULE)
        print(f"{event.event_id}   [{event.direction}]  {event.policy}")
        print(RULE)

        timing = resolve_event_timing(
            event.announcement_ts_utc, calendar, time_known=event.time_known
        )
        straddle = (
            f"{timing.straddling_day.date()} (excluded from day 0)"
            if timing.straddle_is_excluded and timing.straddling_day is not None
            else "none"
        )
        print(f"  announced      {event.announcement_ts_utc.isoformat()}")
        print(f"  time known     {event.time_known}")
        print(f"  t0             {timing.t0.date()}  ({timing.convention})")
        print(f"  straddling day {straddle}")

        try:
            resolved = universe.resolve_for_event(
                event.event_id, event.event_tags, event.announcement_ts_utc
            )
        except EventResolutionError as exc:
            print(f"  STATUS CONFLICT: {exc}")
            continue

        print(
            f"  universe       treated={len(resolved.treated)} "
            f"donors={len(resolved.donors)} excluded={len(resolved.excluded)} "
            f"dropped={len(resolved.dropped)}"
        )
        if resolved.applied_overrides:
            print(f"  overrides      {list(resolved.applied_overrides)}")
        for unit, reason in resolved.dropped.items():
            print(f"    dropped {unit}: {reason[:80]}")

        print(f"  anticipation   {event.anticipation_risk}")
        if event.confounders:
            print(f"  confounders    {list(event.confounders)}")
        if event.channel_targets:
            print(f"  channels       {list(event.channel_targets)}")
        if event.surprise_note:
            print(f"  surprise       {event.surprise_note[:70]}")
        if event.requires_separate_reporting:
            print("  ** reported separately; excluded from every pooled figure **")

    print()
    print(RULE)
    print("GROUPING AND POWER")
    print(RULE)

    poolable = [event for event in events if not event.requires_separate_reporting]
    grouping = assign_event_groups(poolable)
    print(f"  {len(events)} curated, {len(poolable)} poolable")
    print(f"  {grouping.summary()}")

    if grouping.collapsed:
        print()
        print("  collapsed groups:")
        for group in grouping.collapsed:
            print(
                f"    {group.group_id}: {group.size} events over "
                f"{group.span_days} days -- {', '.join(group.event_ids)}"
            )

    print()
    current = max(grouping.n_groups, 1)
    print(f"  {'groups':>7} {'Webb floor':>12} {'Rademacher':>12} {'MDE index':>11}")
    for count in range(1, current + 6):
        webb = bootstrap_p_floor(WeightScheme.WEBB, count, BOOTSTRAP_DRAWS)
        rademacher = bootstrap_p_floor(WeightScheme.RADEMACHER, count, BOOTSTRAP_DRAWS)
        index = float(np.sqrt(current / count))
        marker = "  <- current" if count == current else ""
        blocked = "  5% UNREACHABLE on Rademacher" if rademacher > 0.05 else ""
        print(
            f"  {count:7d} {webb:12.5f} {rademacher:12.5f} "
            f"{index:11.2f}{marker}{blocked}"
        )

    print()
    print(
        f"  Rows are GROUPS, not events (protocol Step 6): events within\n"
        f"  {grouping.min_spacing_days} days share return days and collapse by "
        "transitive closure.\n"
        "  Adding an event inside an existing group moves neither the floor nor\n"
        "  the MDE. MDE index is relative to the current group count, on the\n"
        "  1/sqrt scaling measured in reports/dose_response.md §2.6.\n"
        "  Exposure dispersion needs curated exposure inputs and is not shown\n"
        "  until data/exposure/ is populated."
    )
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
