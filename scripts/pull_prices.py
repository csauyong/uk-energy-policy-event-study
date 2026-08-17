"""Pull daily price history for every named unit in the universe.

Acquisition only. This script fetches and caches; it computes no returns and
prints no price, because of the Rule 0 firewall below.

Run with ``make prices``.

RULE 0 FIREWALL
---------------
``docs/event_curation_protocol.md`` Rule 0 forbids looking at any price series
while curating, and ``docs/exposure_construction.md`` R0 extends that to
exposure curation. Exposure curation is NOT finished
(``data/exposure/firm_attributes.csv`` holds three firms at one vintage), so
prices must not be inspected yet.

Pulling is not looking — but only if that is structural rather than
intentional. So this script:

* writes to ``data/raw/yfinance/`` and nowhere else;
* prints per-ticker METADATA only (row count, first and last date, currency)
  and never a price, a return, or anything derived from one;
* refuses to print anything at all for a treated unit near an event date.

The complementary half of the firewall belongs in the estimator: it must
refuse to run until ``data/exposure/firm_attributes.csv`` is tagged. A rule you
can test beats a rule you remember.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pandas as pd

from policy_event_study.data.prices import (
    PriceSourceUnreachableError,
    fetch_prices,
)
from policy_event_study.data.universe import Universe, load_universe

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Sequence

# Sample floor from CLAUDE.md; the pre-window needs history before the first
# event, so start earlier than the first event date rather than at it.
START = pd.Timestamp("2012-01-01", tz="UTC")
END = pd.Timestamp.now(tz="UTC").normalize()
VINTAGE = END.date().isoformat()


def _named_units(universe: Universe) -> Sequence[str]:
    """Every source ticker in the universe, treated and donor alike.

    `unit_id` is how a firm enters the panel; `source_ticker` is what gets
    fetched, and they differ wherever a corporate action means one price
    series carries two economically distinct firms. BARRATT_PRE is the live
    instance: Yahoo serves Barratt's entire pre-merger history under the
    post-merger symbol, so fetching `unit_id` blindly is the forbidden splice.

    `Universe.source_tickers` already collapses aliased units onto one fetch,
    which is what this needs: BARRATT_PRE and BTRW.L share a symbol and must
    not be requested twice.
    """
    return sorted(set(universe.source_tickers))


def main() -> int:
    """Pull and cache daily history for every named unit."""
    universe = load_universe()
    tickers = _named_units(universe)

    print(f"vintage {VINTAGE}   {START.date()} -> {END.date()}")
    print(f"{len(tickers)} source tickers\n")

    try:
        frames = fetch_prices(tickers, START, END, vintage=VINTAGE)
    except PriceSourceUnreachableError as exc:
        print(f"UNREACHABLE: {exc}", file=sys.stderr)
        print(
            "\nThis is a transport failure. It is NOT evidence that any symbol "
            "has delisted, and the delisted names in config/universe.yaml "
            "(PRSR.L, CSH.L) remain unresolved either way.",
            file=sys.stderr,
        )
        return 2
    except ValueError as exc:
        print(f"SYMBOL PROBLEM: {exc}", file=sys.stderr)
        return 1

    # METADATA ONLY. No price, no return, nothing derived from one.
    print(f"{'ticker':12s} {'rows':>6s}  {'first':10s} {'last':10s}")
    for ticker in sorted(frames):
        frame = frames[ticker]
        print(
            f"{ticker:12s} {len(frame):6d}  "
            f"{frame.index[0].date()} {frame.index[-1].date()}"
        )

    print(f"\ncached to data/raw/yfinance/ at vintage {VINTAGE}")
    print(
        "Rule 0: these series must not be inspected until "
        "data/exposure/firm_attributes.csv is frozen and tagged."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
