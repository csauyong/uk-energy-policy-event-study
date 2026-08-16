"""Sweep gov.uk for candidate announcements. Invoked by `make sweep`.

Protocol Steps 1-3. Writes `data/events/govuk_sweep_<vintage>.csv` and prints a
summary. Discovers nothing about which events belong in the study -- that is
Steps 4-6 and is the curator's judgement.
"""

from __future__ import annotations

import sys

import pandas as pd

from policy_event_study.events.govuk import sweep, to_frame
from policy_event_study.paths import EVENTS_DIR


def main() -> int:
    """Run the sweep and write the candidate table."""
    vintage = pd.Timestamp.now(tz="UTC").date().isoformat()
    print(f"sweeping gov.uk (vintage {vintage}) ...")
    candidates = sweep()
    frame = to_frame(candidates)
    if frame.empty:
        print("no candidates returned")
        return 1

    target = EVENTS_DIR / f"govuk_sweep_{vintage}.csv"
    frame.to_csv(target, index=False)
    print(f"{len(frame)} candidate(s) -> {target}")
    print()

    dated = frame[frame["first_published_at"].notna()]
    print(f"  dated from change history : {len(dated)}")
    print(f"  time of day recoverable   : {int(frame['time_known'].sum())}")
    if not dated.empty:
        gaps = dated["redating_gap_days"].dropna()
        print(
            f"  search-API redating error : median {gaps.median():.0f} days, "
            f"max {gaps.max():.0f} days"
        )
    print()
    print("  by document type:")
    for kind, count in frame["document_type"].value_counts().items():
        print(f"    {kind:24} {count}")
    print()
    print("  earliest 12 by first publication:")
    for _, row in dated.head(12).iterrows():
        stamp = str(row["first_published_at"])[:16]
        print(f"    {stamp}  {row['document_type'][:18]:18}  {row['title'][:52]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
