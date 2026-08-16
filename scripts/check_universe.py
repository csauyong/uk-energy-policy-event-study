"""Parse `config/universe.yaml` and print its clock-alignment table.

Invoked by `make universe-check`. Prints the configuration error and exits 1
rather than raising, since an unfinished universe is the expected state until
every treated ticker has been verified.
"""

from __future__ import annotations

import sys

from policy_event_study.data.universe import UniverseConfigError, load_universe


def main() -> int:
    """Load the universe and summarise it."""
    try:
        universe = load_universe()
    except UniverseConfigError as exc:
        print(f"universe config is not usable yet:\n\n  {exc}\n")
        return 1

    print(universe.alignment_table().to_string(index=False))
    print()
    print(f"donors: {len(universe.donors)}   treated: {len(universe.treated)}")
    print(f"lagged (close after LSE):      {list(universe.late_tickers)}")
    print(f"early (uncorrectable, see §7): {list(universe.early_tickers)}")
    print(f"sector keys for the event CSV: {list(universe.sector_keys)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
