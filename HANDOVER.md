# Handover — 2026-08-18

> **SUPERSEDED IN PART, 2026-08-19.** The work list below ("What was NOT done")
> put back-vintage curation for Genuit, Marshalls and Ibstock first. That was
> tested and is wrong for Marshalls and Ibstock — curating a measured zero is a
> numerical no-op — and bounded for Genuit, whose affected category does not
> exist as a disclosed quantity before the FY2023 results. **Read
> `reports/results.md` §4.5 and `CLAUDE.md` §5 for the current list.** The rest
> of this file stands as the record of that session.

What changed in this session, what is left, and the two commands that need a
machine with network access.

## The one-line summary

The estimate now runs end to end, and the identification audit says the number
it produces is not yet a result. **`reports/results.md` is the deliverable.**

## Run these two, in this order, on a networked machine

```bash
make screening-universe   # needs Yahoo Finance; ~220 tickers, a few minutes
make estimate && make diagnostics
```

Everything else in `make check` runs offline and is green: 361 tests, `ruff`,
`ruff format --check`, `mypy --strict`, and the three data-hygiene targets.

**Why they were not run here.** The environment this work was done in reaches
package registries but not Yahoo Finance — the proxy returns 403 on
`query1.finance.yahoo.com`. `PriceSourceUnreachableError` caught it correctly
and refused to interpret it as a mass delisting, which is that guard doing its
job. The estimate below therefore uses the 55 series already cached at vintage
`2026-08-17`, not the wider screened cross-section.

## What was added

| Path | What it is |
|---|---|
| `src/policy_event_study/data/screening.py` | Screening-universe assembly: EPIC→Yahoo symbology, investment-vehicle filter, history and liquidity screens, survivorship measured rather than assumed |
| `src/policy_event_study/estimators/controls.py` | `size`, `momentum`, `pre_event_vol` from the return panel alone |
| `src/policy_event_study/estimators/car_panel.py` | The missing join: stacks per-unit CARs into the firm × event panel, with every dropped pair carrying a reason |
| `data/prices.load_cached_prices` | Vintage-pinned, network-free price loading, so estimation reproduces from a fixed vintage |
| `data/universe.Universe.without_units` | Explicit removal of the two permanent delistings, keeping `build_panel`'s guard strict |
| `scripts/build_screening_universe.py` | `make screening-universe` |
| `scripts/run_dose_response.py` | `make estimate` |
| `scripts/run_diagnostics.py` | `make diagnostics` — the identification audit |
| `data/universe/index_membership.csv` | FTSE 100 + FTSE 250 constituents with source URLs; hand-transcribed, so version controlled |
| `tests/test_screening.py`, `tests/test_car_panel.py` | 50 new tests |
| `reports/results.md` | **The result and the audit** |

## What was changed

- **`book_to_market` dropped from `DEFAULT_CONTROLS`.** Direction stated: β is
  now an upper bound on the policy channel. `estimators/controls.py` has the
  full reasoning; decision log row 41.
- **`residential_stock` retired** in `config/exposure.yaml`, the way
  `delivered_stock` was — code and tests kept, reason recorded. The study is
  now explicitly one-sided. Decision log row 43.
- **Rockwool `revenue_share_insulation` = 0.7865 (FY2024)** added to
  `firm_attributes.csv`, verified against the annual report. Its UK revenue
  share is **ABSENT** — Rockwool discloses geography by region, not country —
  so it still cannot score on `product_revenue`, which is
  affected-share × UK-share.
- **Grouping corrected from 18 to 21.** The 18 in `README.md` and `CLAUDE.md`
  was stale; recomputing from the frozen dictionary at the 14-day default
  gives 21. Decision log row 50. This matters because the group count drives
  the bootstrap p-value floor.
- README now opens with the answer instead of the blocker.

## What was NOT done, and why

- **Back-vintage curation for Genuit, Marshalls and Ibstock.** This is the
  highest-value remaining work and it is hand curation from annual reports —
  see `CLAUDE.md` §5 step 1. Attempting it from plausible-looking figures
  rather than primary sources would have been worse than leaving it undone.
- **Saint-Gobain and Travis Perkins.** Travis Perkins does not disclose segment
  revenue in its results announcement, so ABSENT is the likely outcome; that
  still needs recording with the reason rather than being left blank.
- **Placebo-in-time and placebo-in-space.** Deliberately skipped. A placebo
  distribution around a β supported by 6.5 effective observations produces a
  number with no interpretation, and quoting it as reassurance is exactly the
  failure mode. `results.md` §7.
- **SC and SDiD.** Still parked, per the standing instruction. The condition
  for running them — an identified dose-response result — has not been met.

## If you pick this up with Claude Code locally

Read in this order: `reports/results.md` §4, then `CLAUDE.md` §5. Section 4 is
why the number is not a result; section 5 is the reordered work list. The
single most important habit to carry forward:

> Read `effective_identifying_rows` in `reports/tables/identification.json`
> before reading β. If it is single digits, the p-value means nothing.
