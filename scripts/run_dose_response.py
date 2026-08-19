"""Run the dose-response estimate end to end and write the results tables.

Run with ``make estimate``.

This is the script the whole repository was built to make possible. It reads
the frozen event dictionary, the curated exposure, and the cached price
history; builds the stacked firm x event CAR panel; and fits the exposure
gradient with all three inference procedures.

WHAT IT PRINTS AND WHY IT PRINTS IT IN THIS ORDER
-------------------------------------------------
MDE first, then the estimate. `reports/dose_response.md` puts the minimum
detectable effect ahead of any point estimate on purpose: a beta read without
knowing what the design could have detected is a number without a scale, and
reading them in the other order invites treating a null as evidence of absence
when it is evidence of an underpowered test.

THE PRE-REGISTERED SENSITIVITY
------------------------------
`CLAUDE.md` section 5 step 4 requires the Budget-2025 sensitivity: estimate
with and without `budget-2025-eco-abolished`, and report both. That event
abolished ECO, is the largest single loosening in the sample, and was
pre-registered as the one whose inclusion is arguable. Both numbers are
printed. Neither is described as the headline.
"""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING

import pandas as pd

from policy_event_study.data.prices import (
    Adjustment,
    build_panel,
    load_cached_prices,
)
from policy_event_study.data.universe import load_universe
from policy_event_study.estimators.base import EventSpec
from policy_event_study.estimators.car_panel import CARPanelError, build_car_panel
from policy_event_study.estimators.dose_response import (
    WeightScheme,
    bootstrap_p_floor,
    dose_response_mde,
    estimate_dose_response,
)
from policy_event_study.events.grouping import assign_event_groups
from policy_event_study.events.loader import load_events
from policy_event_study.events.schema import resolve_event_timing
from policy_event_study.exposure.build import (
    build_exposure_panel,
    load_exposure_config,
    parse_exposure_inputs,
    read_exposure_inputs,
)
from policy_event_study.paths import REPORTS_DIR

if TYPE_CHECKING:  # pragma: no cover
    from policy_event_study.events.schema import PolicyEvent

VINTAGE = "2026-08-17"
START = pd.Timestamp("2012-01-01", tz="UTC")
END = pd.Timestamp("2026-08-17", tz="UTC")
WINDOW = (0, 1)
EXPOSURE_COLUMN = "exposure_continuous"

#: Pre-registered in CLAUDE.md section 5. Estimated in and out; both reported.
SENSITIVITY_EVENT = "budget-2025-eco-abolished"


def _spec_for(
    event: PolicyEvent, donors: tuple[str, ...], trading_days: pd.DatetimeIndex
) -> EventSpec:
    """Build the estimation spec for one event.

    Timing is resolved against the **panel's own calendar**, not an assumed
    one, so a UK holiday-adjacent announcement lands on a day the data has.
    """
    timing = resolve_event_timing(
        event.announcement_ts_utc, trading_days, time_known=event.time_known
    )
    return EventSpec(
        event_id=event.event_id,
        timing=timing,
        donors=donors,
        anticipation_risk=event.anticipation_risk,
        expected_direction=event.expected_direction,
    )


def main() -> int:
    """Build the panel, fit the model, write the tables."""
    universe = load_universe()
    events, _report = load_events(known_sectors=universe.sector_keys)
    grouping = assign_event_groups(events)

    print(f"{len(events)} events -> {len(grouping.groups)} groups\n")

    # Cache-only, on purpose: estimation must reproduce from a fixed vintage
    # rather than from whatever the source serves today. See load_cached_prices.
    frames, absent = load_cached_prices(
        sorted(set(universe.source_tickers)), vintage=VINTAGE
    )
    if absent:
        # Named, not swallowed. Both are recorded under `unresolved:` in
        # config/universe.yaml as permanent delistings, and dropping them is a
        # decision this script makes visibly rather than a loader making it
        # quietly. See Universe.without_units.
        dropped = [
            listing.unit_id
            for listing in universe.all_listings
            if listing.source_ticker in set(absent)
        ]
        print(
            f"not in the {VINTAGE} cache, dropped from the panel: "
            f"{', '.join(dropped)}  (permanent delistings, config/universe.yaml)"
        )
        universe = universe.without_units(dropped)
    panel = build_panel(
        frames,
        universe,
        adjustment=Adjustment.POINT_IN_TIME,
        vintage=VINTAGE,
    )
    print(f"panel: {len(panel.tickers)} units x {len(panel.trading_days)} days")

    config = load_exposure_config()
    attributes_frame, targets_frame = read_exposure_inputs()
    attributes, targets, exposure_report = parse_exposure_inputs(
        attributes_frame,
        targets_frame,
        known_units=universe.unit_ids,
        known_events=[event.event_id for event in events],
        strict=False,
    )
    if not exposure_report.ok:
        print(f"exposure validation: {exposure_report}")
    announcement_times = {event.event_id: event.announcement_ts_utc for event in events}
    exposure = build_exposure_panel(
        list(panel.tickers), attributes, targets, announcement_times, config
    )
    live = exposure.loc[exposure["exposure_magnitude"].abs() > 0]
    print(
        f"exposure: {len(exposure)} unit x event rows, "
        f"{len(live)} with non-zero magnitude, "
        f"{live['unit_id'].nunique()} distinct exposed firms\n"
    )

    donors = tuple(universe.source_tickers)
    specs = [_spec_for(event, donors, panel.trading_days) for event in events]
    availability = {listing.unit_id: listing for listing in universe.all_listings}
    closes = {ticker: frames[ticker]["close"] for ticker in frames}
    volumes = {ticker: frames[ticker]["volume"] for ticker in frames}

    car_panel = build_car_panel(
        panel,
        specs,
        exposure,
        window=WINDOW,
        cluster_ids=grouping.assignment,
        closes=closes,
        volumes=volumes,
        availability=availability,
    )

    print(f"CAR panel: {len(car_panel.frame)} rows")
    print(f"  events contributing  {car_panel.n_events} of {len(events)}")
    print(f"  clusters contributing {car_panel.n_clusters} of {len(grouping.groups)}")
    print("\nattrition:")
    print(car_panel.attrition_table().to_string(index=False))
    for note in car_panel.notes:
        print(f"  NOTE: {note}")

    try:
        car_panel.check_identified(EXPOSURE_COLUMN)
    except CARPanelError as exc:
        print(f"\nNOT IDENTIFIED: {exc}", file=sys.stderr)
        return 1

    frame = car_panel.frame
    n_clusters = car_panel.n_clusters
    scheme = WeightScheme.WEBB if n_clusters < 12 else WeightScheme.RADEMACHER
    floor = bootstrap_p_floor(scheme, n_clusters, 2000)
    print(f"\nweights {scheme.value}; bootstrap p floor {floor:.4f}")

    # MDE FIRST. See the module docstring.
    mde = dose_response_mde(frame, exposure_column=EXPOSURE_COLUMN)
    print("\n--- minimum detectable effect ---")
    print(mde)

    print("\n--- estimate ---")
    result = estimate_dose_response(
        frame, scheme=scheme, exposure_column=EXPOSURE_COLUMN
    )
    print(result)

    # Pre-registered sensitivity.
    without = frame.loc[frame["event_id"] != SENSITIVITY_EVENT]
    sensitivity = None
    if len(without) and without["event_id"].nunique() < frame["event_id"].nunique():
        print(f"\n--- sensitivity: excluding {SENSITIVITY_EVENT} ---")
        try:
            sensitivity = estimate_dose_response(
                without, scheme=scheme, exposure_column=EXPOSURE_COLUMN
            )
            print(sensitivity)
        except ValueError as exc:
            print(f"not identified without that event: {exc}")

    # Rank variant. Disagreement means the scoring function's shape is doing
    # the work -- config/exposure.yaml notes.functional_form.
    rank = None
    if "exposure_rank" in frame.columns:
        print("\n--- functional-form check: decile rank ---")
        try:
            rank = estimate_dose_response(
                frame, scheme=scheme, exposure_column="exposure_rank"
            )
            print(rank)
        except ValueError as exc:
            print(f"rank variant not identified: {exc}")

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    tables = REPORTS_DIR / "tables"
    tables.mkdir(parents=True, exist_ok=True)
    frame.to_csv(tables / "car_panel.csv", index=False)

    payload = {
        "window": list(WINDOW),
        "vintage": VINTAGE,
        "n_rows": len(frame),
        "n_events": car_panel.n_events,
        "n_clusters": car_panel.n_clusters,
        "n_exposed_firms": int(live["unit_id"].nunique()),
        "exposed_firms": sorted(live["unit_id"].unique().tolist()),
        "weight_scheme": scheme.value,
        "bootstrap_p_floor": floor,
        "estimate": _as_dict(result),
        "sensitivity_excluding_budget_2025": _as_dict(sensitivity),
        "rank_variant": _as_dict(rank),
    }
    (tables / "dose_response.json").write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    print(f"\nwritten to {tables}")
    return 0


def _as_dict(result: object) -> dict[str, object] | None:
    """Flatten a result dataclass for the JSON payload."""
    if result is None:
        return None
    return {
        key: value
        for key, value in vars(result).items()
        if isinstance(value, (int, float, str, bool))
    }


if __name__ == "__main__":
    raise SystemExit(main())
