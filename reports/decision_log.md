# Decision log

Every specification tried, in order. This is the multiple-comparisons audit
trail required by `CLAUDE.md` §5 — deflated Sharpe ratios and multiple-testing
corrections are computed against the count of rows in this table.

Append; never edit or delete a row.

**Read the "Kept?" column carefully.** Rows marked `pre-registered` are design
decisions fixed before any estimation and are not specification searches. Rows
marked `trial` consume a degree of freedom and count toward the correction.

| # | Date | Phase | What was tried | Result | Kept? | Note |
|---|------|-------|----------------|--------|-------|------|
| 1 | 2026-08-15 | B0 | Event dictionary schema: 7 required columns, 7 optional; source URL and announcement timestamp are hard rejections | Validator + 26 tests | pre-registered | `data/events/uk_energy_policy_events.csv` ships header-only; curation outstanding |
| 2 | 2026-08-15 | B0 | Event-day resolution using LSE **open and close**, not close alone | Pre-market announcements correctly treated as clean rather than straddling | pre-registered | First implementation used the close only and misclassified a 07:30 release. Fixed; 5 tests pin the three timing cases |
| 3 | 2026-08-15 | B0 | Default event-day convention `FIRST_CLEAN_CLOSE` | — | pre-registered | `INCLUDE_STRADDLE` available and recorded per event; forced to conservative when the time is unknown |
| 4 | 2026-08-15 | B0 | Universe loader enforcing the six `notes:` constraints in `config/universe.yaml` | 17 tests | pre-registered | Loader raises on the 9 `ticker: null` treated names by design |
| 5 | 2026-08-15 | B0 | Clock alignment computed per exchange under GMT and BST | Only the 6 US donors are late (+4h30m); Euronext/Xetra/Dublin are simultaneous with London; Copenhagen is 30m early and uncorrectable | pre-registered | The naive "lag all overseas donors" assumption would have put a spurious 1-day lag on 5 of 23 donors |
| 6 | 2026-08-15 | B0 | Adjustment mode `POINT_IN_TIME` as the estimation default; `AUTO_ADJUST` retained as a labelled comparison | — | pre-registered | `UNADJUSTED` refused for estimation unless explicitly forced |
| 7 | 2026-08-15 | B0 | Reconstructing yfinance `auto_adjust` offline from raw closes + actions | **Abandoned — circular.** A pure back-adjustment cancels in consecutive returns, so the mode reduced to `POINT_IN_TIME` and compared a series with itself | no | Replaced by fetching Yahoo's own adjusted close. The algebra is now a documented finding: retroactive adjustment moves levels, not returns — which is what makes the price-level ban load-bearing |
| 8 | 2026-08-15 | B1 | Market model: OLS + CLM prediction-error SE, 4 event windows, BMP + Brown-Warner crude dependence, block bootstrap | Implemented first, per `CLAUDE.md` §4 | pre-registered | 4 windows = 4 looks; counted here |
| 9 | 2026-08-15 | B1 | Market model routed through the **same permutation inference** as SC/SDiD | — | pre-registered | Prevents confounding estimator with inference method in the headline comparison |
| 10 | 2026-08-15 | B3 | Abadie SC, simplex, ridge `1e-6` variance-scaled | Recovers generating weights to ±0.08 on synthetic panels | pre-registered | Ridge selects the minimum-norm optimum among near-collinear ties; LOO is the check |
| 11 | 2026-08-15 | B3 | SDiD (Arkhangelsky et al. 2021) Algorithm 1, closed-form step 4 | Closed form verified equal to explicit weighted TWFE to 1e-8 | pre-registered | `HORIZON` estimand is the default so τ is comparable with SC and the market model; native `AVERAGE` also exposed |
| 12 | 2026-08-15 | B2 | Embargo of 30 trading days between estimation window and t0 | — | pre-registered | Doubles as the design's only out-of-sample pre-event holdout for the pre-trend test |
| 13 | 2026-08-15 | B2 | Effect measured from the eve of the event, not the end of the estimation window | Embargo-period drift no longer folded into τ | pre-registered | First implementation never evaluated the gap over the embargo at all, which silently broke both `car_by_window(-1,+1)` and the pre-trend holdout. Fixed; tests pin it |
| 14 | 2026-08-15 | B3 | In-space placebo exclusion ladder reported at none/20x/5x/2x rather than one cutoff | — | pre-registered | The cutoff is a researcher degree of freedom; reporting the ladder removes it |
| 15 | 2026-08-15 | B3 | MDE from the placebo distribution | **First version inverted the answer** — took both the critical value and the power quantile from the absolute distribution, making a two-sided test look more powerful than a one-sided one | fixed | Critical value from the thresholded statistic; power quantile from the signed distribution. Regression test asserts the ordering |
| 16 | 2026-08-15 | B3 | Design-level power analysis on calibrated simulations | **1% significance is arithmetically impossible (needs 99 donors); MDE at 20d is 12-24% cumulative abnormal return** | kept — headline | See `reports/event_study.md` §3. This bounds what any subsequent null can mean and was computable before any data || 17 | 2026-08-15 | B0 | **ESTIMAND CHANGE.** Primary design moves from synthetic control on treated units to dose-response on exposure across the whole listed universe | Driven by row 16's power finding, not by an unwelcome estimate | kept | SC/SDiD retained as the robustness section, not deleted |
| 18 | 2026-08-15 | B0 | Treated tickers supplied and verified against yfinance | 9 of 10 resolve; **PRSR.L returns HTTP 404 (PRS REIT taken private)** | kept | Recorded under `unresolved:`, not substituted or silently dropped |
| 19 | 2026-08-15 | B0 | Barratt merger handling | **BTRW.L returns 9,776 rows back to 1988** — Yahoo renamed the pre-merger history to the post-merger symbol; BDEV.L and RDW.L both empty. The naive pull *is* the forbidden splice | kept | Two units, one source, non-overlapping availability bounds + exclusion window. Completion dated 2024-08-20 from an 82.3m-share volume spike (vs ~6m median) and 1.39bn shares outstanding |
| 20 | 2026-08-15 | B0 | Universe schema: per-event status overrides on a global default | Segro flips donor→treated on commercial-MEES events; conflicting overrides are a hard error, not last-one-wins | pre-registered | Exhaustiveness asserted: every unit resolves to exactly one status or one drop reason |
| 21 | 2026-08-15 | B0 | Panel calendar changed from strict intersection to LSE spine with NaNs | Availability-bounded units never overlap, so an intersection would return an empty panel | pre-registered | Completeness resolved per event window instead |
| 22 | 2026-08-15 | B1 | Exposure measure: 4 channels, signed, share-not-size | Sign convention anchored to policy direction so a mandate and its repeal must produce opposite betas | pre-registered | `docs/exposure_construction.md`. Utilities score zero: sign not determinable ex ante |
| 23 | 2026-08-15 | B1 | Housebuilder channel sign set to -1 with `sign_ambiguous: true` | Genuinely unresolved ex ante | pre-registered | Sensitivity S2 is mandatory; a result surviving only one sign is not a result |
| 24 | 2026-08-15 | B2 | Dose-response estimator: event FE, 4 controls, 3 inference procedures | Wild cluster bootstrap is the headline; clustered SE reported for comparison only | pre-registered | Cluster-robust asymptotics over-reject at single-digit event counts |
| 25 | 2026-08-15 | B2 | MDE via design-effect haircut on an assumed intraclass correlation | **Abandoned — 5.6x too optimistic, silently.** Event FE force residual event-means to ~0, so the ICC collapses; once demeaned the average pairwise residual correlation is ~-1/(n-1), not positive | no | Replaced with an MDE on the cluster-robust SE, effective N derived from it. Regression test added |
| 26 | 2026-08-15 | B2 | Analytic (normal-approximation) MDE as headline | **Optimistic**: realised wild-bootstrap power at the analytic MDE is 54% (6 events), not 80% | no | Report the bootstrap-calibrated figure, ~1.5x the analytic one, via `se_inflation` |
| 27 | 2026-08-15 | B2 | **Dose-response MDE = ~0.3% CAR per SD of exposure** ([0,1], 6 events, calibrated) | vs 12-24% for the SC design: a 40-80x improvement. A fully-exposed firm at ~5 SD implies ~1.5%, inside the plausible range | kept — headline | The design is adequately powered for the hypothesis it now tests. Gates Part 3 |
| 28 | 2026-08-15 | B2 | Power scaling check | **Universe size barely moves the MDE; event count does** (100→600 firms: <5%; 4→15 events: roughly halves) | kept | Inverts the curation guidance: effort belongs on finding clean events, not extending the cross-section || 29 | 2026-08-15 | B2 | Rademacher wild bootstrap as the default weight scheme | **Abandoned — carries its own p-value floor.** 2^G sign vectors floor the two-sided p at 2/2^G: 0.031 at 6 clusters, 0.125 at 4. The same defect as the 1/(J+1) permutation floor, through a different mechanism | no | Escaping one floor and walking into another |
| 30 | 2026-08-15 | B2 | Webb six-point weights as the default; scheme a required argument; floor a field on the result | 6^G vectors -> floor 0.000043 at 6 clusters | kept | `bootstrap_p_floor`, `detectable_at`, `at_the_floor`. Regression tests pin the 2/S^G arithmetic and the G=5 textbook figure of 6.25% |
| 31 | 2026-08-15 | B2 | Webb-vs-Rademacher effect on conclusions | **No conclusion changes at 6 events** (realised power identical, 71%/92%/96%). At 4 events Rademacher makes 5% unreachable and Webb does not | kept | Webb buys robustness against a thin event count, not a better headline |
| 32 | 2026-08-15 | B2 | Influence diagnostics: leverage, Cook's D, top-k drop path, winsorised variant, form comparison, effective firm count | Exposure is right-skewed, so a large-N regression can be identified off a handful of names and nothing else in the pipeline surfaces it | pre-registered | `MissingInfluenceError` makes a missing influence section a hard failure, as `MissingPlaceboError` does for placebos |
| 33 | 2026-08-15 | B2 | Nominal firm count reported alone | **Abandoned.** Misleading when leverage is concentrated | no | Effective firm count (leverage participation ratio) is emitted in the same table so the two cannot be separated |
| 34 | 2026-08-15 | B0 | `direction` (tighten/loosen) added to the event schema as a required column with no default | Makes the mandate-versus-repeal falsification test executable rather than a prose design property | pre-registered | A missing value would remove the test rather than fail it |
| 35 | 2026-08-15 | B2 | `sign_consistency`: beta estimated separately on tightening and loosening subsamples | Pre-registered falsification, not a subgroup finding. Reports UNDERPOWERED rather than a verdict when either side cannot reach 5% | pre-registered | Runs on the direction-neutral `exposure_channel_signed`, where the prediction is opposite signs |
| 36 | 2026-08-15 | B0 | Event spacing rule: events closer than 14 days rejected without `overlap_ack` | Overlapping windows are not independent clusters, and the bootstrap floor is set by the nominal cluster count | pre-registered | Configurable threshold; the ack records that dependence is known rather than unnoticed |
| 37 | 2026-08-15 | B0 | `make event-report` and `data/events/candidates.md` | Curation view: timing resolution, status resolution, MDE-vs-event-count curve over the current file | kept | Candidates file carries the primary-source rule; not populated -- curation is the owner's || 38 | 2026-08-16 | B0 | A-priori hand inventory loaded and used to score the sweep | **Coverage 76%, date accuracy 35%, miss rate 24%** (found/mis-dated/missed = 11/20/10 of 41 usable) | kept | The binding failure is dating, not recall. Mis-dating is the more damaging error: ECO abolition carried at March 2026 rather than 2025-11-26 puts the whole reaction outside the window while still looking like a valid row |
| 39 | 2026-08-16 | B0 | Discovery scored as `1 - misdated/found` | **Returned -82%.** `found` and `misdated` are disjoint partitions, not nested sets | no | Corrected to `found/(found+misdated)`; partition check asserts 41 == 41. A metric bug that reads as catastrophe rather than as arithmetic |
| 40 | 2026-08-16 | B0 | Grouping and p-value floor computed on the real event list | **31 independent day-resolved instruments -> 26 groups**; Webb floor 0.0005, Rademacher clears 5% | kept | First time in the project the p-value floor is NOT the binding constraint. The binding constraint is now the `loosen` side: 22 tighten vs 9 loosen/mixed, ~4 groups when split |
| 41 | 2026-08-16 | B0 | Extending the sweep to HMT documents to close the fiscal source gap | **Refused, deliberately.** The hand list already recovered all five fiscal instruments; a sweep extension pays off only on a rerun that will not happen | no | Tooling spiral wearing a methodological hat. The gap is written up as a limitation with the hand-list diff as evidence -- a stronger artefact, because it documents a source-coverage failure the completeness audit was structurally incapable of detecting (it audits the corpus against the extractor, and both share the gap) |
| 42 | 2026-08-16 | B0 | **Leak-search protocol, pre-committed before any article was read** | see the block below | pre-registered | Ordered before C-grade resolution because leak searches can only *remove* rows and C-grade resolution can only add them -- and three of the four leak rows sit on the `loosen` side that already binds |


---

## Pre-committed leak-search protocol (2026-08-16)

**Written and committed before a single article was read.** Recorded here
rather than in the report because the point of a pre-commitment is that it is
timestamped in the audit trail, not that it is well presented.

### Why leak searches run before C-grade resolution

The two remaining curation steps are asymmetric in what they can do to the
event list:

* **C-grade resolution can only add rows.** Eight instruments carry a month
  but no day. Resolving them against legislation.gov.uk and the gov.uk content
  API either produces a usable date or does not.
* **Leak searches can only remove rows.** The protocol's Step 2 rule is that
  gradual disclosure makes an event unusable. Each of the four high/confirmed
  rows is therefore a coin-flip on deletion.

Three of the four leak rows are `loosen` -- September 2023, Budget 2025, green
levies 2013 -- and the `loosen` side is already the binding constraint at ~4
groups. Seven of the eight C-grade rows are `tighten`, so resolving them all
would move the balance from 22/9 to 29/10 and make the imbalance *worse*.
Doing the additive work first would be spending a day worsening the constraint
while still not knowing whether the constraint survives.

### Search bounds -- fixed, no extensions

| Parameter | Value |
|---|---|
| Window | 10 calendar days before the formal date |
| Sources | National broadcast, and FT / Times / Telegraph / Guardian |
| Excluded | **Trade press.** Anticipating policy is what trade press does; including it would drop every row in the list |
| Budget | 30 minutes per row |

### Decision rule

| Finding | Action |
|---|---|
| Substance in >=1 credible outlet, one identifiable date, with specifics | Move `t0` to that date; **keep** |
| Substance across >=3 dates with escalating specificity | Gradual disclosure; **drop** and say why |
| Nothing | **Keep** the formal date |

### Contingency, pre-stated before results are seen

If the `loosen` side falls below 4 groups, **report sign-consistency as
underpowered with the Webb floor stated plainly.**

The alternative considered and rejected was folding the Future Homes Standard
2026 `delivered_stock` leg into the `loosen` side. It was rejected on a
substantive ground rather than a preference: that event is `mixed`, so its
`product_revenue` leg is already on the `tighten` side, and counting its other
leg as a `loosen` observation would put **the same announcement on both sides
of a test that assumes the two subsamples are independent**. The
sign-consistency test compares betas estimated on disjoint event sets; sharing
an event across the split violates that directly, and would inflate apparent
agreement between the sides for a mechanical reason.

Reporting the test as underpowered costs a finding. Sharing an event across
the split would produce a finding that is not one.| 43 | 2026-08-16 | B0 | Leak searches executed under the pre-committed protocol | 1 drop (green levies 2013), 1 `t0` move (net zero rollback to 09-19), 2 keeps | kept | **The pre-commitment worked**: the rule was written before any article was read and it deleted a row that would otherwise have been argued on its merits |
| 44 | 2026-08-16 | B0 | Loosen side estimated as `count // 2` groups | **Wrong.** Grouped properly the loosen side is 8 groups, not ~4 | no | The estimate made the design look one deletion from losing its falsification test, and that false fragility was the premise for sequencing the curation. Now pinned in `tests/test_inventory.py` |
| 45 | 2026-08-16 | B0 | Scenario drops matched instruments by id without validation | **Silent no-op**: `green-levies-2013` for `green-levies-rollback-2013` made a dropped event look harmless | no | `drop_instruments` now raises on an unknown id. A mistyped drop reads as a robustness finding, which is the dangerous failure |
| 46 | 2026-08-16 | B0 | Corrected leak scenario table | baseline 9->8 groups; drop either 8->7; **drop both 7->6**. Webb floor 0.0005 throughout | kept | Pre-stated contingency (below 4 groups) does not fire in any scenario. Sign-consistency survives every leak outcome |
| 47 | 2026-08-16 | B2 | **Budget 2025 pre-registered as a sensitivity** rather than defended | Estimate with and without the event; report both | pre-registered | Converts an evidence problem that cannot be resolved through blocked outlets into a stated robustness result |
| 48 | 2026-08-16 | B0 | C-grade resolution, timeboxed | `mees-2015-regs-made` -> **2015-03-26** (SI 2015/962, made). `mees-3500-cap-laid` unresolved: the 2018 draft became SI 2019/595 made 2019-03-15, and the laying date is not on legislation.gov.uk | partial | Six remaining C grades are `tighten` on the non-binding channel; excluded by the stated rule "month-only, day not establishable from primary source" |


### Leak protocol: executed with deviation (2026-08-16)

**The pre-committed source list was not reachable.** BBC, FT, Times,
Telegraph, Guardian and Sky all refuse this user agent. The searches were run
against search-engine summaries of those outlets and against Carbon Brief,
which the a-priori inventory already cites for establishing leak timing. Trade
press was **not** substituted -- the row 20 search returned almost entirely
trade sources and they were discarded under the committed rule.

**The resulting bias has a known direction, and it is the conservative one.**
Under-powered leak detection means formal dates are kept where an earlier date
should have been adopted. That pushes `t0` later, which places genuine
reaction inside the pre-window, which attenuates measured effects toward zero.

> Leak detection was under-powered; the resulting bias is toward late event
> dates and attenuated estimates; **measured effects are therefore lower
> bounds.**

A caveat with a known conservative direction is a bound. A caveat with unknown
direction is a hole. This one is a bound.

### Outcomes

| Row | Outcome |
|---|---|
| Net zero rollback | **Keep, `t0` -> 2023-09-19.** Leaked to the BBC the evening before; the speech was brought forward because of it |
| Green levies 2013 | **DROP.** Four dates, escalating specificity; formal date also ambiguous between 2 and 5 December |
| Budget 2025 | **Keep at 2025-11-26, with a pre-registered sensitivity.** Pre-Budget reporting was on a different figure, not the ECO mechanism |
| Heat and Buildings Strategy | **Keep.** 18-vs-19 October resolved to 2021-10-19 12:05 UTC; 13:05 London is mid-session, so 19 Oct straddles and `t0` is 20 Oct |

## Kill criteria fired

| Date | Criterion | Verdict | Action taken |
|------|-----------|---------|--------------|
| — | B0 (fewer than ~8-10 clean events) | **not yet evaluable** | Event dictionary not curated |
| — | B2 (SC pre-fit not better than market model) | **not yet evaluable** | Universe does not load; no prices pulled |
| — | B3 (estimates indistinguishable from placebos) | **not yet evaluable** | — |
| 2026-08-15 | *Advisory, pre-data*: §3.1 arithmetic floor | **1% level unreachable with any donor pool this design admits** | Report states results at 5% only; 1% appears nowhere |
| 2026-08-15 | **Phase 1b power diagnostic** | **SC design cannot detect effects of the size at stake** (20-day MDE 12-24% CAR) | **Estimand changed to dose-response** (row 17). SC/SDiD retained as robustness, not deleted. This is the criterion doing its job |

---

## 2026-08-16 — `delivered_stock` retired; the study is products-and-landlords

**Specification tried.** Score the housebuilder channel as
`share_of_delivered_below_mandated_band`, per the pre-registered
`config/exposure.yaml`.

**Why it was examined.** Building `data/exposure/policy_targets.csv` produced a
blank `mandated_min_band` on 7 of 7 `new_build` target rows. The channel cannot
compute without one, so the blanks were either a curation gap to fill or a sign
that the construction does not fit the instruments. They were the latter.

**Finding.** Building regulations do not mandate a band. Part L 2021 requires
`DER ≤ TER` and `DPER ≤ TPER` against a *notional dwelling*; no SAP score and no
band appears in the instrument. Bands are an outcome of compliance, not a
requirement, so there is no mandated band to source. Band outcome statistics
exist only in trade commentary and adopting one would be the analogue of taking
an event date from news coverage.

Independently, bands are not comparable across the sample: SAP 2012 → SAP 10.2 →
Home Energy Model, plus RdSAP 10 in 2025 and the EPC metric reform of
2026-01-21. **`epc-reform-consultation` is itself an event in the dictionary** —
the sample contains the announcement that changed the measuring instrument.

The percentage-step alternative fails separately: baselines differ, only 3 of 7
events carry a stated step, and the firm-side analogue is not disclosed.
Housebuilder EPC completion data also begins around 2019–2021, so 3 of the 7
new-build events have no firm-side data under any construction.

**Kept or abandoned.** Abandoned. Not because it produced an unwelcome number —
it produced none — but because the dose cannot be built from disclosed
quantities without fabricating a mandate value, which R5 forbids and which no
sensitivity in `docs/exposure_construction.md` §4 would detect.

**Consequences.**

| | |
|---|---|
| Treated names losing exposure | 9 of 26 (the housebuilder block) |
| Curation cancelled | 9 firms × ~12 vintages of band profiles |
| Sensitivity S2 (housebuilder sign flip) | **retired as moot** — no dose to flip |
| `new_build` target rows | retained with blank bands, as the record of an unmeasurable exposure |
| Events dropping out of the dose-response entirely | 5 (`zero-carbon-homes-cancelled`, `fhs-2019-consultation`, `fhs-2019-response`, `part-l-2021-published`, `fhbs-2023-consultation`) |
| Events losing a leg but surviving on a product leg | 2 (`ten-point-plan`, `future-homes-standard-2026`) |
| Events still contributing to the dose-response | **19 of 24** |

The report must state `n` separately for the event list (24) and for the
dose-response (19), or the five will read as a silent drop.

**Note on `future-homes-standard-2026`.** It survives. Its delivered_stock leg
(the delay to 2028) is unmeasurable, but its two product legs — the solar
mandate and the heat-pump requirement — are `new_build` in *scope* while being
`product_revenue` in *channel*, and they score normally. The event keeps the
tighten side of its opposite-signed structure and loses the loosen side, which
must be stated wherever that event is discussed as a two-sided shock: after this
row, it is one-sided.

**Estimand after this row.** Products and landlords: `product_revenue` and
`residential_stock`. `domestic_supply` remains zero by design (§2.1);
`delivered_stock` now joins it as a channel carried in the config and reported
as unmeasurable rather than deleted.
