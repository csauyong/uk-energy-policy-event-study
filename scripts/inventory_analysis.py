"""Score the sweep against the a-priori inventory, then size the design on it.

Two questions, in order.

1. **How good was the automated discovery?** The inventory was written before
   the shortlist was consulted, so it can measure the sweep rather than merely
   disagree with it. Recall and date accuracy are reported separately because
   they fail differently: a missed event costs one observation, an event dated
   to its effect month puts the whole reaction outside the window.

2. **Does the design work on the real event list?** Grouping and the p-value
   floor computed on 41 usable instruments rather than on simulated counts.
   This is the first time the power arithmetic meets actual events.
"""

from __future__ import annotations

import itertools
import sys
from collections import Counter

import pandas as pd

from policy_event_study.estimators.dose_response import (
    WeightScheme,
    bootstrap_p_floor,
)
from policy_event_study.events.grouping import DEFAULT_MIN_SPACING_DAYS
from policy_event_study.events.inventory import (
    DateGrade,
    load_inventory,
    score_discovery,
    usable_events,
)
from policy_event_study.paths import EVENTS_DIR


def shortlist_rows() -> list[tuple[str, str]]:
    """Read (month, family) pairs from the generated final shortlist."""
    finals = sorted(EVENTS_DIR.glob("shortlist_final_*.md"))
    if not finals:
        return []
    rows: list[tuple[str, str]] = []
    for line in finals[-1].read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.split("|")]
        if len(cells) < 9 or not cells[1].isdigit():
            continue
        rows.append((cells[2], cells[3].strip("`")))
    return rows


def group_by_spacing(dates: list[pd.Timestamp], spacing_days: int) -> list[list[int]]:
    """Transitive-closure grouping over a spacing threshold, on bare dates."""
    if not dates:
        return []
    order = sorted(range(len(dates)), key=lambda i: dates[i])
    chains: list[list[int]] = [[order[0]]]
    for previous, current in itertools.pairwise(order):
        if (dates[current] - dates[previous]).days < spacing_days:
            chains[-1].append(current)
        else:
            chains.append([current])
    return chains


def main() -> int:
    """Run the scoring and the design sizing."""
    inventory = load_inventory()
    independent = usable_events(inventory, include_scheduled=False)
    rows = shortlist_rows()

    score = score_discovery(inventory, rows)
    print("=== 1. Discovery scoring ===")
    print(f"  inventory        : {score.inventory_total} instruments")
    print(f"  usable (A/B)     : {score.inventory_usable}")
    print(f"  found by sweep   : {len(score.found)}")
    print(f"  missed by sweep  : {len(score.missed)}")
    print(f"  mis-dated        : {len(score.misdated)}")
    print(f"  COVERAGE         : {score.coverage:.0%}  (sweep had something)")
    print(f"  DATE ACCURACY    : {score.date_accuracy:.0%}  (of those, dated right)")
    print(f"  miss rate        : {score.miss_rate:.0%}")
    partition = len(score.found) + len(score.misdated) + len(score.missed)
    print(f"  partition check  : {partition} == {score.inventory_usable}")

    print()
    print("=== 2. Why the sweep missed what it missed ===")
    missed = [i for i in inventory if i.id in set(score.missed)]
    fiscal = [i for i in missed if "fiscal" in " ".join(i.families)]
    print(
        f"  fiscal-event instruments among the misses: {len(fiscal)} of {len(missed)}"
    )
    for instrument in missed:
        tag = "FISCAL" if instrument in fiscal else "      "
        print(f"    {tag} {instrument.date:12} {instrument.title[:62]}")

    print()
    print("=== 3. Grouping on the real list (protocol Step 6) ===")
    dated = [i for i in independent if i.resolved_day is not None]
    dates = [i.resolved_day for i in dated if i.resolved_day is not None]
    chains = group_by_spacing(dates, DEFAULT_MIN_SPACING_DAYS)
    collapsed = [c for c in chains if len(c) > 1]
    print(f"  independent, day-resolved : {len(dated)}")
    print(f"  groups at {DEFAULT_MIN_SPACING_DAYS}-day spacing  : {len(chains)}")
    print(f"  collapsed groups          : {len(collapsed)}")
    for chain in collapsed:
        members = [dated[i] for i in chain]
        span = (
            max(m.resolved_day for m in members) - min(m.resolved_day for m in members)
        ).days  # type: ignore[operator]
        print(f"    {span:3d}d  " + " + ".join(m.id[:26] for m in members))

    print()
    print("=== 4. Power on the real list ===")
    n_groups = len(chains)
    for scheme in WeightScheme:
        floor = bootstrap_p_floor(scheme, n_groups, 2000)
        verdict = "OK" if floor <= 0.05 else "5% UNREACHABLE"
        print(f"  {scheme!s:11} floor at {n_groups} groups = {floor:.5f}  {verdict}")

    directions = Counter(i.direction or "unset" for i in independent)
    print()
    print(f"  direction balance (independent): {dict(directions)}")
    # Group each side properly. An earlier version estimated `count // 2`,
    # which reported the loosen side at ~4 groups when it is actually 8: the
    # loosen instruments are spread across 2013-2026 and almost none of them
    # fall within the spacing threshold of each other. The shortcut made the
    # side look far more fragile than it is, and the fragility was the premise
    # for sequencing the whole curation step.
    for label, subset in (
        ("tighten", [i for i in dated if i.direction == "tighten"]),
        ("loosen/mixed", [i for i in dated if i.direction in {"loosen", "mixed"}]),
    ):
        side_dates = [i.resolved_day for i in subset if i.resolved_day is not None]
        side_groups = len(group_by_spacing(side_dates, DEFAULT_MIN_SPACING_DAYS))
        floor = bootstrap_p_floor(WeightScheme.WEBB, side_groups, 2000)
        print(
            f"    sign-consistency {label:13} n={len(subset):2d} "
            f"-> {side_groups} groups, Webb floor {floor:.5f}"
        )

    print()
    print("=== 5. Still blocking ===")
    unresolved = [i for i in inventory if i.date_grade is DateGrade.C]
    print(f"  C-grade dates unresolved: {len(unresolved)}")
    high_leak = [i for i in independent if i.leak_risk in {"high", "confirmed"}]
    print(f"  high/confirmed leak risk: {len(high_leak)}")
    for instrument in high_leak:
        print(
            f"    {instrument.leak_risk:10} {instrument.date:12} {instrument.title[:56]}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
