"""Assemble the screening universe and cache its price history.

Run with ``make screening-universe``.

WHAT THIS PRODUCES
------------------
``data/universe/uk_listed_universe.csv``: the broad cross-section of
zero-exposure London listings that pins the event fixed effect in the
dose-response design. Until this file has rows, `estimate_dose_response` is
fitting `alpha_e` off the treated names themselves and beta means nothing.

RULE 0 FIREWALL
---------------
Same firewall as ``pull_prices.py``. This script fetches and screens; it
prints per-ticker metadata and rejection reasons only, and never a price, a
return, or anything derived from one.

The one place price data touches membership is the liquidity screen, and that
is measured over a window ending **before the first event in the dictionary**
-- see ``SCREEN_END``. Screening on activity after an announcement would let
the outcome decide the control group. The window is chosen here, in code,
rather than left to a caller who might reasonably pick the full sample.
"""

from __future__ import annotations

import sys

import pandas as pd

from policy_event_study.data.prices import (
    PriceSourceUnreachableError,
    fetch_prices,
)
from policy_event_study.data.screening import (
    filter_candidates,
    read_index_membership,
    screen_on_prices,
)
from policy_event_study.data.universe import load_universe
from policy_event_study.paths import DATA_DIR

MEMBERSHIP_CSV = DATA_DIR / "universe" / "index_membership.csv"
OUTPUT_CSV = DATA_DIR / "universe" / "uk_listed_universe.csv"

# Sample floor from CLAUDE.md. The market model needs an estimation window
# before the first event, so start well before it.
START = pd.Timestamp("2012-01-01", tz="UTC")
END = pd.Timestamp.now(tz="UTC").normalize()
VINTAGE = END.date().isoformat()

#: Liquidity is measured over the year ending here. This pre-dates the first
#: event in the frozen dictionary (`zero-carbon-homes-cancelled`, 2015-07-10),
#: so no post-announcement trading can influence membership.
SCREEN_END = pd.Timestamp("2015-06-30", tz="UTC")


def main() -> int:
    """Build the screening universe and write it to `OUTPUT_CSV`."""
    universe = load_universe()
    screening_config = universe.screening_universe
    if screening_config is None:
        print("config/universe.yaml has no screening_universe: block", file=sys.stderr)
        return 1

    candidates = read_index_membership(MEMBERSHIP_CSV)
    print(f"{len(candidates)} names in the published membership lists")

    survivors, pre_price_reasons = filter_candidates(
        candidates, exclude_tickers=universe.source_tickers
    )
    print(
        f"{len(survivors)} after dropping investment vehicles and "
        f"already-curated names ({len(pre_price_reasons)} dropped)\n"
    )

    tickers = sorted({candidate.ticker for candidate in survivors})
    try:
        frames = fetch_prices(tickers, START, END, vintage=VINTAGE)
    except PriceSourceUnreachableError as exc:
        print(f"UNREACHABLE: {exc}", file=sys.stderr)
        print(
            "\nThis is a transport failure, NOT evidence that these symbols "
            "have delisted. Re-run before drawing any survivorship conclusion.",
            file=sys.stderr,
        )
        return 2

    result = screen_on_prices(
        survivors,
        frames,
        min_history_days=screening_config.min_history_days,
        min_avg_daily_volume_gbp=screening_config.min_avg_daily_volume_gbp,
        screen_end=SCREEN_END,
    )

    # Fold the pre-price reasons in so the partition check covers every
    # candidate, not just the ones that reached the price source.
    all_rejected = {**pre_price_reasons, **result.rejected}
    merged = type(result)(
        frame=result.frame,
        rejected=all_rejected,
        attempted=result.attempted,
        no_data=result.no_data,
    )
    merged.check_partition(candidates)

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    merged.frame.to_csv(OUTPUT_CSV, index=False)

    print(f"admitted   {merged.admitted}")
    print(f"attempted  {merged.attempted}")
    print(
        f"no data    {len(merged.no_data)} "
        f"(survivorship rate {merged.survivorship_rate:.1%})"
    )
    print(f"\nwritten to {OUTPUT_CSV.relative_to(OUTPUT_CSV.parents[2])}")

    print("\nDropped, by reason:")
    tallies: dict[str, int] = {}
    for reason in all_rejected.values():
        key = reason.split(";")[0].split(" is below")[0]
        tallies[key] = tallies.get(key, 0) + 1
    for key, count in sorted(tallies.items(), key=lambda item: -item[1]):
        print(f"  {count:4d}  {key}")

    print(
        "\nRule 0: these series must not be inspected outside the estimator. "
        "The liquidity screen used a window ending "
        f"{SCREEN_END.date()}, before the first event."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
