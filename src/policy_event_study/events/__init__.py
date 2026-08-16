"""Event dictionary handling.

The hand-curated event list lives in `data/events/uk_energy_policy_events.csv`
-- the one deliberate exception to the `data/` gitignore, because it is source
that no loader can regenerate. Each entry records the announcement date, the
announcement timestamp, the source URL, the anticipation risk, the expected
direction and the affected sectors; a row missing a source URL or a timestamp
is rejected outright.

Unscheduled, pre-trailed and confounded events are analysed separately. See
`data/events/README.md` for the curation guide.
"""
