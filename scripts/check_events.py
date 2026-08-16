"""Validate the hand-curated event dictionary. Invoked by `make events-check`.

Exits 0 when nothing fatal was found, 1 otherwise. Warnings are printed and do
not fail the check -- they are caveats the report must carry, not errors.
"""

from __future__ import annotations

import sys

from policy_event_study.data.universe import UniverseConfigError, load_universe
from policy_event_study.events.loader import validate_events_file


def main() -> int:
    """Run the validator and report."""
    # Cross-check `affected_sectors` against the universe's treated groups
    # when the universe loads; skip that check rather than fail when it does
    # not, so an incomplete universe cannot block event curation.
    try:
        known_sectors: tuple[str, ...] | None = load_universe().sector_keys
    except (UniverseConfigError, FileNotFoundError) as exc:
        known_sectors = None
        print(f"note: sector cross-check skipped ({exc.__class__.__name__}: {exc})\n")

    report = validate_events_file(known_sectors=known_sectors)
    print(report.render())
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
