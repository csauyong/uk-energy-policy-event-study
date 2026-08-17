# CLAUDE.md — uk-energy-policy-event-study

Project-level status and handover. The **governing standards** are in
[`../CLAUDE.md`](../CLAUDE.md) and win wherever this file conflicts with them:
point-in-time discipline, named baselines, time-ordered splits, negative
results kept, no P&L without a cost model.

Read [`README.md`](README.md) first for what the project is. This file is
what a new session needs to pick the work up.

**Status as of 2026-08-17:** event dictionary frozen and tagged, prices
pulled, exposure curation in progress. Estimation is blocked on one channel's
worth of curation. 301 tests, `ruff` and `mypy --strict` clean.

---

## 1. Where the project actually is

| Stage | State |
|---|---|
| Universe (treated / donor / excluded) | **Working.** Per-event status overrides, 57 source tickers |
| Event discovery | **Working.** Deductive, from published chronologies |
| Event dictionary | **Frozen and tagged** — `events-frozen-2026-08-16`, 24 events → 18 groups |
| Leak searches | **Done**, with a stated deviation (§4) |
| Price acquisition | **Working.** 55 of 57 tickers; two genuine delistings |
| Exposure curation | **In progress.** This is the blocker |
| Dose-response estimation | **Blocked** on exposure |
| Synthetic control / SDiD | **Parked deliberately** — retained as robustness, not deleted |

### The design changed once, on purpose

The original design was synthetic control on treated firms. A power
calculation run *before* any data was pulled put the minimum detectable effect
at **12–24% cumulative abnormal return** — larger than any plausible policy
effect. The estimand changed to dose-response across the whole listed
universe, which brought the detectable effect to roughly **0.3%**.

SC and SDiD code is intact and tested. It is the robustness section, and
`reports/dose_response.md` §9 is where it belongs. **Do not run it before the
dose-response result exists** — that ordering was an explicit instruction and
the reason is that it would invite reporting whichever design gave the nicer
answer.

---

## 2. What is working

**Everything with a `make` target.** `make check` runs lint, types, tests and
data hygiene, and is green.

- `make chronology` — deductive discovery over 17 Commons Library briefings
- `make audit` — completeness audit and deferral hunt
- `make shortlist` / `make finalise` — rule-based filtering, hand overlay
- `make promote` — writes the frozen event dictionary
- `make event-report` — timing, grouping, power curve keyed on **groups**
- `make prices` — price acquisition with a Rule 0 firewall
- `make events-check` / `make universe-check` — validators

**Load-bearing safeguards that have each caught a real bug.** These are not
decoration; every one fired at least once:

| Guard | What it caught |
|---|---|
| `MissingPlaceboError` | A point estimate reaching a report without its placebo distribution |
| `MissingInfluenceError` | A β reported without leverage diagnostics |
| `bootstrap_p_floor` | Rademacher weights flooring p at 0.031 with 6 clusters |
| `drop_instruments` id check | A mistyped id making a deleted event look harmless |
| Availability windows | The Barratt pre/post-merger splice |
| `PriceSourceUnreachableError` | Blocked egress being misread as mass delisting |
| Event spacing validator | Announcements 1, 7 and 13 days apart treated as independent |

---

## 3. What is NOT working — the blocker

**Exposure curation is incomplete, and estimation cannot start without it.**

`estimate_dose_response` raises when exposure has no within-event variation.
That guard is correct — with every firm at zero, β is collinear with the event
fixed effects and any number it returned would be an artefact.

### The single highest-value cell

**`KRX.IR` (Kingspan) `uk_revenue_share` is `TODO`.**

Kingspan's `revenue_share_insulation` is filled (0.2120, FY2024). But
`product_revenue_magnitude` returns *"channel does not apply"* when
`uk_revenue_share` is missing — deliberately, because defaulting it to 1.0
would hand every foreign manufacturer full UK exposure. So the largest firm in
the cleanest channel currently contributes **nothing**.

`data/exposure/curation_worksheet_product_revenue.csv` has the cell, the
source (Kingspan FY prelims, late Feb/early Mar) and the segment structure
already noted. It needs the revenue-by-destination figure.

### Channel-by-channel state

| Channel | Live treated names | State |
|---|---|---|
| `product_revenue` | 7 (was 8) | Partially curated. Genuit complete; Kingspan blocked on UK share |
| `residential_stock` | **3** | **Thin and fragile** — see below |
| `delivered_stock` | 9 | Not started |
| `domestic_supply` | 4 | Scores zero by design; sign undeterminable ex ante |

### The landlord channel is fragile

`residential_stock` carries the entire landlord side of the dose-response and
is down to **Grainger, Unite and one other**. `PRSR.L` (PRS REIT) is confirmed
delisted — Yahoo returns HTTP 404 — and it is recorded under `unresolved:` in
`config/universe.yaml` rather than substituted.

Unite Group is student accommodation, so its exposure to *domestic* MEES is
questionable and should be checked before it is relied on. If it fails that
check the channel is effectively one name, and the landlord half of the
falsification test stops being credible. **This is the risk most likely to end
the project's headline claim, and it is a data-availability problem rather
than a methods problem.**

---

## 4. Known limitations, each with its direction

A caveat with a known direction is a bound. A caveat without one is a hole.

**Leak detection was under-powered.** The pre-committed news sources (BBC, FT,
Times, Telegraph, Guardian) all block the tooling's user agent. Searches ran
against summaries and Carbon Brief instead. Missing a leak means keeping a
formal date when an earlier one was correct, which pushes `t0` late, which
puts genuine reaction in the pre-window. **Measured effects are lower bounds.**

**The sweep does not reach HMT documents.** Every energy-efficiency measure
announced through a Budget or Spending Review was missed by automated
discovery — found only by hand-list diff. The completeness audit could not
have caught this: it audits the corpus against the extractor, and both share
the gap. **Deliberately not fixed** — the hand list already recovered the five
instruments, and building an HMT sweep would pay off only on a rerun that will
not happen. Written up as a limitation instead.

**Survivorship.** The universe is built from firms a scraper still serves.
`PRSR.L` and `SIG.L` are concrete instances inside the treated set, not
hypotheticals.

**Six inventory rows lack a source URL** and were held back at promotion
rather than promoted with a blank. Four are fiscal — the same gap biting
twice. Adding six URLs to the inventory's §6 recovers them.

---

## 5. Next steps, in order

1. **Fill Kingspan's `uk_revenue_share`.** Highest value per minute of any
   remaining task.
2. **Check Unite Group's exposure to domestic MEES.** Decides whether the
   landlord channel survives. Do this before curating more of it.
3. **Finish `product_revenue` curation**, then `residential_stock`, then
   `delivered_stock`.
4. **Run the dose-response estimate**, with the pre-registered Budget-2025
   sensitivity (estimate with and without that event; report both).
5. **Then** the robustness section: SC and SDiD on the lowest-anticipation
   events, plus conformal inference, which escapes the `1/(N+1)` floor.

**Do not** extend the sweep to HMT. **Do not** run SC/SDiD before step 4.
Both were explicit instructions and both have reasons recorded above.

---

## 6. Working agreements for this repo

Inherited from `../CLAUDE.md` §8, plus what this project learned:

- **Rule 0: curate blind.** No price series is looked at while the event list
  is being built. The list is frozen and tagged before estimation.
- **Pre-commit decision rules before looking at evidence.** The leak protocol
  was written before a single article was read, and it deleted an event that
  would otherwise have been argued about. That is the rule working.
- **State a caveat's direction or it is not a caveat.**
- **Arithmetic that decides whether the design lives gets pinned in a test.**
  Three defects in that class were found in one day — a nested-set assumption
  returning −82%, a `count // 2` group estimate off by half, and a mistyped id
  that made a deletion look harmless. All three produced *plausible* numbers.
- **A silent no-op is worse than a crash.** Prefer raising.
- **Report what did not work.** `reports/decision_log.md` is the audit trail
  and includes every abandoned specification.
