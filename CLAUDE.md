# CLAUDE.md — uk-energy-policy-event-study

Project-level status and handover. The **governing standards** are in
[`../CLAUDE.md`](../CLAUDE.md) and win wherever this file conflicts with them:
point-in-time discipline, named baselines, time-ordered splits, negative
results kept, no P&L without a cost model.

Read [`README.md`](README.md) first for what the project is. This file is
what a new session needs to pick the work up.

**Status as of 2026-08-19: THE ESTIMATE RUNS, AND THE BINDING CONSTRAINT HAS
BEEN IDENTIFIED AS A DISCLOSURE GAP, NOT A CURATION BACKLOG.**

`make estimate` and `make diagnostics` work end to end. The result and the
audit behind it are in **`reports/results.md`**, which is the first thing to
read after `README.md`.

**The headline is not the coefficient.** β = −0.057% with p = 0.52 across 682
rows looks like a well-powered null against a 0.26% MDE. It is not one. **Nine**
rows carry non-zero exposure, **two** firms account for all nine, and the
effective count of identifying observations is **8.6**. Drop Genuit and β flips
sign; drop Genuit and Kingspan and β does not exist.

**What changed on 2026-08-19, and it reorders everything.** The previous
handover named back-vintage curation for Genuit, Marshalls and Ibstock as "the
whole game", worth 6 → 15+ identifying events. Tested:

- **Marshalls and Ibstock: a numerical no-op.** Both are measured zeros on every
  affected category, and a curated zero and an uncurated default zero give the
  *same* `exposure_magnitude` and `exposure_signed`. Verified by construction.
- **Genuit: bounded, and delivered.** Its affected category did not exist as a
  disclosed quantity before the FY2023 results — two end-market segments until
  then. Curating that one vintage moved identifying events **6 → 8**, effective
  rows **6.5 → 8.6**, and β six-fold.
- **The real constraint: `product_revenue` is affected-share × UK-share, and
  every multinational in the sample sits below its own IFRS 8 country-
  materiality threshold in the UK.** Kingspan bounded below 15% from FY2022;
  Rockwool below 10% in every year; neither publishes a figure. The firms that
  do publish one are UK-domiciled with a share near 1.0, where the multiplier
  does nothing. **The measure's discriminating variable is unobservable exactly
  where it discriminates** — `results.md` §4.5.

So: **the dose-response is not identified, and no quantity of curation hours
fixes it.** The next decision is a design choice, not a data-entry task.

361 tests, `ruff` and `mypy --strict` clean.

---

## 1. Where the project actually is

| Stage | State |
|---|---|
| Universe (treated / donor / excluded) | **Working.** Per-event status overrides, 57 source tickers |
| Event discovery | **Working.** Deductive, from published chronologies |
| Event dictionary | **Frozen and tagged** — `events-frozen-2026-08-16`, 24 events → **21 groups** (the 18 previously stated here was stale; decision log row 50) |
| Leak searches | **Done**, with a stated deviation (§4) |
| Price acquisition | **Working.** 55 of 57 tickers; two genuine delistings |
| Exposure curation | **Largely exhausted, not incomplete.** 2 firms carry every non-zero score and §5 explains why a third is not available |
| CAR panel + controls | **Working.** `estimators/car_panel.py`, `estimators/controls.py` |
| Screening universe | **Builder written and tested; not yet run.** Needs one command on a networked machine |
| Dose-response estimation | **Runs.** Result in `reports/results.md`; not identified — see §3 |
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
| `Scope` enum raising on an unknown value | The exposure pipeline had never been run against its own curated targets file |
| `band_index` raising on a blank band | 8 unmeasurable targets that would have scored a fabricated zero on every firm |
| `latest_by_attribute` tie-break test | CSV row order silently deciding which vintage entered every score |

---

## 3. What is NOT working — the blocker

**Exposure curation is incomplete, and estimation cannot start without it.**

`estimate_dose_response` raises when exposure has no within-event variation.
That guard is correct — with every firm at zero, β is collinear with the event
fixed effects and any number it returned would be an artefact.

### 3.1 The single highest-value cell — RESOLVED 2026-08-17

**`KRX.IR` (Kingspan) `uk_revenue_share`: disclosed FY2014–FY2021, absent
FY2022–FY2025.** Full working in `docs/exposure_construction.md` §7.5.

The blocker was never the document format. Kingspan's IFRS 8 note names a
country only *"where revenue exceeds 15% of total Group revenues"*. Britain
cleared that bar until FY2021 (€999.8m of €6,497.0m, **0.1539**) and stopped
clearing it in FY2022, so the figure leaves the accounts **mid-sample**.

Two consequences, both stated with direction:

- **The absence is a bound, not a hole.** UK revenue is below 15% of group from
  FY2022, so Kingspan's magnitude there is under **0.0318** against Genuit's
  **0.2561**. Kingspan is about an eighth of Genuit's dose at best — the cell
  was high-value because of the drop-out mechanics, not because Kingspan would
  have topped the ranking.
- **R3 carries FY2021 forward into 8 later events, and that over-states.**
  0.1539 remains the last *published* figure so R3 is right to use it, but
  Kingspan's own later accounts imply a value below 0.15. Over-statement is
  classical measurement error: it **attenuates β toward zero**.

Kingspan now scores on 9 events. `revenue_share_heating_ventilation` is ABSENT
at every vintage per R1a (ventilation sits inside an unsplit `Light & Air`).

### 3.2 Channel-by-channel state

| Channel | Live treated names | State |
|---|---|---|
| `product_revenue` | 7 (was 8) | Genuit (FY2021–FY2024) and Kingspan (FY2014–FY2024) curated. Marshalls/Ibstock measured zeros — further vintages **deprioritised, a no-op**. Rockwool UK share **ABSENT, bounded < 0.10**. SIG no price series. Saint-Gobain **BLOCKED (403)**. Travis Perkins R1a → ABSENT |
| `residential_stock` | **1 at the events that matter** | **Effectively Grainger alone** — see §3.3 |
| `delivered_stock` | 9 | Retired 2026-08-16; carried as unmeasurable |
| `domestic_supply` | 4 | Scores zero by design; sign undeterminable ex ante |

### 3.3 The landlord channel is down to one name, and three pipeline blockers

**Unite is resolved and it does not help.** Two independent grounds, neither a
judgement haircut: (i) domestic MEES binds only on assured and regulated
tenancies — Energy Act 2011 s.42(1)(a), read from primary source — and PBSA is
generally let outside that regime; (ii) even granting full scope, Unite's
disclosed portfolio is **>99% EPC A–C**, so the share below band C is under 1%.
Curate its band profile and let it score its own measured near-zero (R6). Do
not drop it.

**So at the three `domestic_prs` events — `net-zero-rollback-2023`,
`prs-mees-epc-c-reinstated`, `warm-homes-plan` — the landlord channel is
Grainger alone.** Unite ~0 either way; Civitas delisted 2023-08-04 (now
**verified**, not `date_confidence: low`), before all three. The falsification
pair the signed measure exists to test would rest on one firm.

Three blockers found by running the exposure pipeline against the curated files
for the first time. **All three are now closed:**

| # | Finding | Resolution |
|---|---|---|
| a | `Scope` enum had drifted (`domestic/commercial/both`) from the curated vocabulary. Every target row failed | Enum replaced with the curated tenure vocabulary |
| b | `PolicyTarget.scope` was parsed, validated and **never read** — a PRS landlord scored full exposure to a social-rented mandate | **Stock channels gate on scope.** Tenure lives in the attribute prefix (`dwellings_prs_band_*` / `dwellings_social_band_*`); the generic prefix means *tenure not disclosed* and scores only under `all_domestic`. `product_revenue` stays ungated — see `docs/exposure_construction.md` §7.7 |
| c | 8 rows carry blank band *and* blank categories, so `strict=True` rejected the file and `band_index("")` would **raise** once a landlord profile existed | **Skipped and counted**, not scored as zero. Recorded on `panel.attrs`; validator downgraded to WARN so the record of the retired channel need not be deleted to make the loader work |

**Curating Grainger's band profile is now unblocked** — use
`dwellings_prs_band_*`, not the generic prefix, or it will score nothing at the
three PRS events.

**`n` for the dose-response is 18 of 24, not 19** — corrected and pinned in a
test. The 2026-08-16 count missed `epc-reform-consultation`, which is blank for
a different and deliberate reason. §7.8 of the exposure doc.

### 3.4 Estimation is blocked on more than exposure

`data/universe/uk_listed_universe.csv` is **header-only**. The dose-response
identification comes from several hundred zero-exposure listings pinning
`α_e`; with none of them, β would be estimated off two firms. There is also no
CAR panel builder (only per-unit `car_by_window`) and **no builder for any of
the four `DEFAULT_CONTROLS`** — `book_to_market` needs fundamentals the project
has not acquired at all.

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

**Rewritten 2026-08-19.** The previous first item — curate back-vintages for
Genuit, Marshalls and Ibstock, "this is the whole game", worth 6 → 15+
identifying events — was tested. It is **wrong for two of the three firms**,
and the reason is arithmetic, not effort. `reports/results.md` §4.5 and §6
carry the evidence; decision log rows 67–71.

What was actually delivered from that item: Genuit's FY2023 vintage, the one
row of it that could work. It moved identifying events **6 → 8**, effective
identifying rows **6.5 → 8.6**, and β **six-fold**. That is the measured
return on the best available curation row, and it is why the rest of the old
list has been retired rather than reordered.

1. **Decide between the two design routes in `results.md` §4.5.** This is now
   the first question rather than the last, because the binding constraint is
   a *disclosure* gap, not a curation backlog: `product_revenue` is
   affected-share × UK-share, and every multinational in the sample sits below
   its own IFRS 8 country-materiality threshold in the UK, so none publishes a
   UK figure. Kingspan is bounded below 15% from FY2022; Rockwool below 10% in
   every year. **The multiplier is unobservable exactly where it
   discriminates.** Route 1 — drop the multiplier, restrict to UK-domiciled
   firms — must be pre-registered before it is run. Route 2 reports the
   measurement finding as the deliverable, which `../CLAUDE.md` §5 explicitly
   sanctions.
2. **Curate Saint-Gobain**, the last firm that might carry a UK figure.
   `saint-gobain.com` returns **HTTP 403** to the tooling, so it needs a fetch
   from elsewhere. Recorded as **BLOCKED, not ABSENT** — a transport failure
   must never be written down as a disclosure failure.
3. **Run `make screening-universe`** on a networked machine, then re-run
   `make estimate && make diagnostics`. Read `effective_identifying_rows` in
   `reports/tables/identification.json` **before** reading β.
4. **Only then** the robustness section: SC and SDiD on the lowest-anticipation
   events.

**Retired from this list, each with its evidence:**

| Retired | Why |
|---|---|
| Marshalls and Ibstock back-vintages | Measured zeros on every affected category. A curated zero and an uncurated default zero produce the **same** `exposure_magnitude` and `exposure_signed`; only the `channel` label differs, and no label enters the regression. Verified by construction |
| Genuit vintages before FY2023 | Genuit/Polypipe reported two **end-market** segments until the FY2023 results (2024-03-11). The affected category did not exist as a disclosed quantity. R1a |
| Travis Perkins | Merchant reporting by end market; insulation and heating are proper subsets of an unsplit segment (R1a → ABSENT), and its UK share of ~1.0 would do no work |

**Do not** extend the sweep to HMT. **Do not** run SC/SDiD until something is
identified — the condition has not been met and 8.6 effective rows is not it.
**Do not** quote β, the MDE, or a placebo distribution without the identifying
row count beside it.

**5. After any re-run, read the documents against the output.** Added
2026-08-19 after a review found three stale figures that had been correct when
written: `README.md` still carried the pre-curation β and still named
back-vintage curation as the binding constraint — the one claim this project
had just refuted — and `results.md`'s summary contradicted its own §4.4. The
estimator has guards that fire. Prose does not. `make estimate && make
diagnostics`, then diff every number in `README.md`, `results.md` and this file
against `reports/tables/`. Decision log rows 74–76.

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
- **One column heading, one quantity.** `top_k_drop_path` reported the
  post-`dropna` count on success and the pre-`dropna` count on failure, so the
  drop path printed n *rising* as more firms were dropped. Neither branch was
  wrong alone. A number that is impossible but plausible-looking is this
  repository's most frequent defect, and every instance has been caught by
  running the thing rather than by reading it.
- **Report what did not work.** `reports/decision_log.md` is the audit trail
  and includes every abandoned specification.
