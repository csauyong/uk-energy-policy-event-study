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
| 49 | 2026-08-17 | B1 | **Kingspan `uk_revenue_share` sourced across every vintage** | Disclosed FY2014-FY2021 (0.3635 -> 0.1539, falling monotonically); **not disclosed FY2022-FY2025** | kept | The blocker was never the document format. Kingspan names a country only "where revenue exceeds 15% of total Group revenues"; Britain cleared that bar until FY2021 and stopped clearing it in FY2022, so the figure leaves the accounts mid-sample |
| 50 | 2026-08-17 | B1 | FY2022-FY2025 `uk_revenue_share` recorded ABSENT rather than carried or estimated | Kingspan drops out of `product_revenue` for 9 of the 15 product-touching events | kept | R5. The non-disclosure is itself informative and is recorded as a **bound with a direction**: UK revenue is below 15% of group, so the FY2024 magnitude is under 0.0318 against Genuit's 0.2561 |
| 51 | 2026-08-17 | B1 | R3 carry-forward of the FY2021 UK share into FY2022+ events | Scores 8 later events off a stale 0.1539 | kept, with the bias stated | R3 is right that the last *published* figure is what the market has. But Kingspan's later accounts positively imply a value **below** 0.15, so the carried figure **over-states** exposure. Over-statement is classical measurement error: **attenuates beta toward zero** |
| 52 | 2026-08-17 | B1 | `latest_by_attribute` tie-break on `knowable_from` | **Wrong.** Ties were resolved by CSV row order | no | R7 *guarantees* the tie: a comparative carries the later report's `knowable_from`. Sorting `firm_attributes.csv` would silently have swapped current-year figures for prior-year ones. Now breaks on `as_of_date` and is pinned in `tests/test_exposure.py` |
| 53 | 2026-08-17 | B1 | Loading the curated `policy_targets.csv` through `parse_exposure_inputs` | **Raised on row 1.** The `Scope` enum was `domestic/commercial/both`; the curated file uses `all_domestic/domestic_prs/social_rented/off_gas_grid/new_build` | fixed | The exposure pipeline had never been run against the real targets file. "Raise rather than no-op" found it on the first attempt |
| 54 | 2026-08-17 | B1 | **`PolicyTarget.scope` is parsed, validated and never read** | A private-rented landlord scores full exposure to a social-rented mandate, and vice versa | **open — needs a decision** | Gating the stock channels on scope changes the estimand, so it is not made silently. Affects 4 `domestic_prs` and 3 `social_rented` target rows |
| 55 | 2026-08-17 | B1 | 8 `new_build` target rows carry a blank band **and** blank categories | `validate_exposure_inputs` marks all 8 FATAL, so `strict=True` rejects the curated file | **open — needs a decision** | These are the deliberate record of the retired `delivered_stock` channel (row of 2026-08-16). Separately, a blank band makes `band_index("")` **raise** as soon as any landlord band profile exists — which is the next curation step |
| 56 | 2026-08-17 | B1 | **Unite Group resolved: near-zero dose, on two independent grounds** | Not scored by judgement; band profile to be curated and left to score its own measured value | kept | (i) Domestic MEES binds on assured/regulated tenancies only — Energy Act 2011 s.42(1)(a), read from primary source; PBSA is generally let outside that regime. (ii) Even granting full scope, Unite's disclosed portfolio is >99% EPC A-C, so the share below band C is under 1% |
| 57 | 2026-08-17 | B1 | Landlord channel membership at the three `domestic_prs` events | **Grainger alone.** Unite ~0 either way; Civitas delisted 2023-08-04, before all three | **open — needs a decision** | The signed measure's falsification pair (`net-zero-rollback-2023` vs `prs-mees-epc-c-reinstated`) would rest on one firm. This is the data-availability risk `CLAUDE.md` §3 names, now realised |
| 58 | 2026-08-17 | B0 | Civitas `listed_to` verified | 2023-08-04 **confirmed** (cancellation 08:00, 4 Aug 2023); `date_confidence` can move low -> high | kept | The pulled `CSH.L` series runs to **2026-07-16** — roughly three years of prices after the shares stopped trading. The availability window is the only thing keeping them out of the panel |
| 59 | 2026-08-18 | B1 | **Unscoreable targets skipped and counted**, not scored as zero | `strict=True` now loads the curated file; 8 targets skipped, recorded on `panel.attrs` | kept | Resolves row 55. Scoring them would put a fabricated zero on every firm at 8 events — rows carrying no information that drag beta toward zero — and would crash on `band_index("")` the moment a landlord profile exists. Validator downgraded to WARN so a curator is not forced to delete the record of the retired channel to make the loader work |
| 60 | 2026-08-18 | B1 | **`n` for the dose-response recounted: 18 of 24, not 19** | 6 events carry no scoreable target, not 5 | corrected | The 2026-08-16 count took only the seven blank `new_build` rows. It missed `epc-reform-consultation`, blank for a *different* and deliberate reason — it reforms the EPC metric rather than mandating a band — and carrying no affected category either. **Pinned in `tests/test_exposure.py`**: the last hand count of this number was wrong by one |
| 61 | 2026-08-18 | B1 | **Stock channels gated on `PolicyTarget.scope`** | `residential_stock` scores the tenure the instrument names; `delivered_stock` only `new_build` | kept | Resolves row 54. MEES binds by tenure, which is why the curation separated `domestic_prs` from `social_rented` in the first place. A PRS landlord now takes a **measured zero** on a social-rented mandate — data, not an artefact — rather than full exposure |
| 62 | 2026-08-18 | B1 | Tenure encoded in the attribute prefix, not inferred | `dwellings_prs_band_*` / `dwellings_social_band_*`; generic `dwellings_band_*` means tenure **not disclosed** | kept | The generic prefix scores only under `all_domestic`. A landlord curated without a tenure split therefore scores nothing at a tenure-specific event instead of being assumed fully private rented, which would be a fabricated value under R5. Costs nothing today: no landlord band profile is curated yet, so there is nothing to migrate |
| 63 | 2026-08-18 | B1 | `product_revenue` and `domestic_supply` deliberately **not** gated on scope | unchanged | kept | A manufacturer sells into whichever tenure the subsidy stimulates. Gating the demand channel would invent a distinction the firm's own revenue disclosure does not make |
| 64 | 2026-08-18 | B0 | `make universe-check` run | **Broken on HEAD**, and had been: it called `late_tickers` / `early_tickers`, which do not exist | fixed | `CLAUDE.md` §2 listed it under "what is working". It was not in `make check`, which is exactly why it rotted unnoticed. **Now in `make check`** |
| 65 | 2026-08-18 | B1 | RESI.L proposed, HOME.L exclusion re-affirmed, ESP.L dropped | **No membership change** — recorded in `config/universe.yaml` as a proposal pending approval | pending owner | ReSI is the only candidate reaching both tenure tracks (retirement rentals on assured tenancies; shared ownership via a Registered Provider). Its managed wind-down from 2024 is a caveat with a direction. HOME.L's 1,476 rows are stale prints from a suspended line and would inject false zero returns |
| 66 | 2026-08-18 | B1 | **Open: `score_firm` cannot distinguish "no channel applies" from "channel applies, input missing"** | Both land on `channel="none", magnitude=0` | **open — changes `n`** | Kingspan FY2022+ is the live instance: a genuinely unknown UK share is recorded as a measured zero exposure to UK insulation policy. §3 says a false zero attenuates beta while an absence merely shrinks `n`. Fixing it means the panel must emit "applicable but unknown", which changes the estimand and so is not done silently |
| 67 | 2026-08-19 | B1 | **Genuit back-vintage FY2023 curated** | 4 new attribute rows; identifying events **6 → 8**, effective identifying rows **6.48 → 8.59** | kept | The FY2024-comparative row's own note asked for exactly this: the FY2023 figures entered the market on 2024-03-11 with the FY2023 results, not on 2025-03-10 with the FY2024 results. Correcting `knowable_from` by one year buys `autumn-budget-2024` and `chmm-delayed` |
| 68 | 2026-08-19 | B1 | **Genuit cannot be curated before 2024-03-11, at any price** | `revenue_share_heating_ventilation` ABSENT for FY2013–FY2022 per R1a | kept | Until the FY2023 results Genuit/Polypipe reported two END-MARKET segments — Residential Systems and Commercial and Infrastructure Systems — and no product split. The affected category **did not exist as a disclosed quantity**. This is a disclosure fact, not a curation backlog |
| 69 | 2026-08-19 | B1 | **Marshalls and Ibstock back-vintages DEPRIORITISED — curating them is a numerical no-op** | Verified by construction: curated measured zero and default zero both give `magnitude=0.0`, `signed=0.0` | kept | A firm with no knowable attribute already falls through `score_firm` to an explicit zero. Only the `channel` label differs and no label enters the regression. **This falsifies the premise of `CLAUDE.md` §5 step 1**, which put these two alongside Genuit as "the whole game" |
| 70 | 2026-08-19 | B1 | **Rockwool `uk_revenue_share` ABSENT in every vintage, with a bound** | UK revenue is **below 10% of group**, so the magnitude is bounded above by 0.7865 × 0.10 = **0.0786** | kept | "In Germany, France, and the United States revenue amount to between 10-15 percent … In no other country does revenue exceed 10 percent." Identical wording FY2020, FY2021, FY2024. Rockwool would be the second-largest exposure in the sample if the figure existed. It does not, in any year |
| 71 | 2026-08-19 | B1 | **The channel's discriminating variable is unobservable exactly where it discriminates** | Structural, not effort-limited — see `results.md` §4.5 | recorded as a finding | `product_revenue = affected share × UK share`. Every multinational in the sample is below its own IFRS 8 country-materiality threshold in the UK, so none discloses a UK figure: Kingspan bounded < 15% from FY2022, Rockwool < 10% always. The firms that *do* disclose it are UK-domiciled with a share near 1.0, where the multiplier does no work |
| 72 | 2026-08-19 | B0 | Saint-Gobain fetch attempted | `saint-gobain.com` returns **HTTP 403** to the tooling | blocked, not absent | Same class as the blocked news outlets in the leak protocol. A transport failure must not be recorded as a disclosure failure — that is the distinction `PriceSourceUnreachableError` exists to protect elsewhere |
| 73 | 2026-08-19 | B2 | Re-ran `make estimate` and `make diagnostics` after the curation | β = −0.00057, p_wild = 0.52; Budget-2025 sensitivity β = −0.00044, p = 0.63 | **still not a result** | `effective_identifying_rows` 8.59 of 692, top-10 rows carry 97.0% of the weight, still **2** exposed firms. The handover's rule applies unchanged: single digits means the p-value means nothing. The curation moved the number in the right direction and nowhere near far enough |


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

---

## 2026-08-18 — Scope reduction to reach a first estimate, and what it found

Six decisions taken together, to move the project from a finished pipeline
with no result to a result with a stated limitation. The owner approved the
four marked **simplification** before any of it was run.

| # | Date | Phase | What was tried | Result | Kept? | Note |
|---|------|-------|----------------|--------|-------|------|
| 41 | 2026-08-18 | C1 | Drop `book_to_market` from `DEFAULT_CONTROLS` | Removes the entire point-in-time fundamentals workstream | **simplification** | Direction stated: exposure concentrates in value-tilted building-products names, so any unabsorbed value premium loads onto β, biasing it **away from zero**. β is an **upper bound**. `estimators/controls.py` |
| 42 | 2026-08-18 | C1 | `size` = log average daily GBP turnover, not market capitalisation | Point-in-time by construction | **simplification** | Share counts are only available at today's vintage; applying them to a 2015 price manufactures a market cap that never existed, with a look-ahead, since buybacks follow these events |
| 43 | 2026-08-18 | C1 | Retire the `residential_stock` channel | Study becomes one-sided | **simplification** | Grainger alone at all three `domestic_prs` events (Civitas delisted 2023-08-04; Unite ≈0 on two independent grounds; `RESI.L` not approved). A falsification test resting on one firm is not one. Code and tests kept, as `delivered_stock` was |
| 44 | 2026-08-18 | C1 | Screening universe at FTSE-350 scale (~150–250 names) rather than "several hundred" | Builder written and tested; **not yet run** — no network in the build environment | **simplification** | Justified by this project's own §2.5 finding: 100 → 600 firms moves the MDE by under 5%. `data/screening.py`, `scripts/build_screening_universe.py` |
| 45 | 2026-08-18 | C1 | `load_cached_prices`: vintage-pinned, network-free price loading | Estimation reproduces from a fixed vintage instead of from whatever the source serves today | pre-registered | `fetch_prices` silently falls back to the network on a cache miss, which made every estimation run quietly connectivity-dependent |
| 46 | 2026-08-18 | C1 | `Universe.without_units` | `PRSR.L` and `SIG.L` dropped explicitly by a named caller | pre-registered | Keeps `build_panel`'s strict guard intact rather than weakening it to tolerate two permanent delistings |
| 47 | 2026-08-18 | C2 | **First dose-response estimate**, window (0,+1), Rademacher weights | β = −0.000092, se 0.001116, p 0.94 (cluster), 0.94 (wild bootstrap), 0.94 (randomisation). MDE 0.313% | trial | Reported in `reports/results.md`. **Not the headline** — see row 49 |
| 48 | 2026-08-18 | C2 | Pre-registered Budget-2025 sensitivity, per `CLAUDE.md` §5 step 4 | β = +0.000183 excluding `budget-2025-eco-abolished`; a shift of ~3× the point estimate | pre-registered | Both reported; neither called the headline |
| 49 | 2026-08-18 | C2 | **Identification audit** — Frisch-Waugh leverage on β, drop path, leave-one-event-out | **The null is uninformative.** 7 non-zero exposure rows of 692; 6 identifying events of 18; 2 exposed firms; top 10 rows carry 97% of the weight on β; **6.5 effective identifying rows**. β not identified at all once both exposed firms are dropped; sign flips on removing any single event | **kept as the finding** | This is what the report says, in place of the null. New: `scripts/run_diagnostics.py` |

### Row 49 is the result of this session

The regression's own `n_observations = 682` and `n_events = 17` are honest
counts and are badly misleading, because a row whose exposure is exactly zero
contributes nothing to the exposure gradient beyond pinning its event fixed
effect. Nothing in the estimator's output surfaced the gap between 682 and 6.5.

That is the same class of defect as the design-effect MDE that was 5.6× too
optimistic (recorded earlier in this log): a plausible-looking number whose
input was not describing what a reader would assume. It was caught by building
the diagnostic, not by inspecting the estimate.

**Consequence for the remaining work.** The binding constraint is not power,
not the event dictionary, and not the screening universe. It is that every
Genuit, Marshalls and Ibstock attribute is `knowable_from` March 2025, so the
point-in-time filter correctly withholds them from the eighteen events that
pre-date it, leaving Kingspan as the only firm with pre-2025 vintages.

**The fix is more vintages of the firms already curated, not more firms.**

### Correction

| # | Date | Phase | What was tried | Result | Kept? | Note |
|---|------|-------|----------------|--------|-------|------|
| 50 | 2026-08-18 | C0 | Recount the event grouping from the frozen dictionary | **24 events → 21 groups** at the 14-day default, not 18 as `README.md` and `CLAUDE.md` both stated | correction | The 18 figure was stale. Both files corrected. Group count drives the bootstrap p-value floor and the MDE, so an over-stated collapse would have over-stated the clustering |
