# Results

**Run date:** 2026-08-19 · **Price vintage:** 2026-08-17 · **Event window:** (0, +1)
· **Event dictionary:** `events-frozen-2026-08-16`, unchanged

> **Revised 2026-08-19** after curating Genuit's FY2023 back-vintage. Identifying
> events 6 → 8, effective identifying rows 6.5 → 8.6. The conclusion is
> unchanged and §4.5 explains why it is unlikely to change: the missing
> variable is not missing through lack of effort, it is not published.

---

## The answer, stated plainly

**The design does not identify an effect, and the reason is not that policy
announcements move nothing. It is that the exposure curation supports 8.6
effective observations.**

The regression runs. It reports β = −0.057% per standard deviation of
exposure, a cluster-robust standard error of 0.091%, p = 0.52, and n = 682
rows across 17 clusters. Read at face value that is a clean, well-powered
null against a minimum detectable effect of 0.26%.

**Read at face value it would be wrong.** Of those 682 rows, nine carry a
non-zero exposure score. Two firms account for all of them. The Frisch-Waugh
decomposition below puts 97% of the weight on β on ten rows, and the effective
count of identifying observations at **8.6**.

**And the point estimate moved six-fold on one back-vintage.** Curating a
single additional Genuit disclosure — not a new firm, not a new event, one
firm-year that had been dated a year late — moved β from −0.0092% to −0.057%.
An estimate that responds like that to one curation row is not measuring a
policy effect.

So this report does not claim that UK energy-efficiency announcements fail to
move exposed share prices. It claims something narrower and better supported:

> On the exposure data curated to date, the dose-response estimand is not
> identified. The point estimate is indistinguishable from zero, it varies by
> 160% of itself on the removal of any single event, it flips sign when Genuit
> alone is dropped, and it ceases to exist entirely when Genuit and Kingspan
> are both dropped. The binding constraint is **the disclosure record**, not
> curation effort, not statistical power, and not the event dictionary — §4.5.

---

## 1. What the pipeline produced

| Stage | Result |
|---|---|
| Events in the frozen dictionary | 24 |
| Event groups (clusters) | 21 |
| Price panel | 55 units × 3,672 trading days |
| Units dropped as permanent delistings | `PRSR.L`, `SIG.L` |
| Exposure panel | 1,210 unit × event rows |
| — of which non-zero magnitude | **17** |
| — distinct exposed firms | **2** (`GEN.L`, `KRX.IR`) |
| Stacked CAR panel | 692 rows, 18 events, 17 clusters, 41 firms |

Attrition from the full 24 × 55 grid, every drop with a reason:

| Reason | Pairs |
|---|---|
| No exposure row for the unit × event pair | 324 |
| Abnormal-return series has gaps inside the event window | 280 |
| Unit not available on the event date (listing bounds) | 24 |

The 280 gap-drops are mostly early events against firms that listed later,
which is correct behaviour rather than loss. The 24 availability drops are the
Barratt pre/post-merger boundary doing its job.

---

## 2. Minimum detectable effect, stated before the estimate

| Quantity | Value |
|---|---|
| Residual SD | 0.0510 |
| Exposure SD | 0.794 |
| se(β) | 0.000913 |
| **MDE at 80% power, 5% level** | **0.256%** |

That lands close to the 0.3% the pre-registered power analysis in
`dose_response.md` §2.5 predicted, which is a useful check that the pipeline is
doing what the design said it would.

**It is also, in this instance, close to meaningless.** The MDE is computed
from `se(β)`, and `se(β)` is computed from a design whose exposure column is
zero in 683 of 692 rows. The exposure SD of 0.794 is not the dispersion of a
populated cross-section; it is what you get when nine values of roughly ±7
standard units sit in a sea of zeros. The formula is correct. Its input is not
describing what the reader will assume it describes.

**This is the same class of error `dose_response.md` §2.4 caught once already**
— an MDE that was 5.6× too optimistic because of an intraclass-correlation
assumption. The lesson repeated: an MDE is only as meaningful as the design
matrix behind its standard error, and it should never be quoted without the
identifying structure beside it.

---

## 3. The estimate

| | Continuous | Decile rank |
|---|---|---|
| β | −0.000568 | −0.006199 |
| se (cluster) | 0.000913 | 0.012419 |
| t | −0.622 | −0.499 |
| p, cluster-robust | 0.543 | 0.624 |
| p, wild bootstrap | 0.522 | 0.617 |
| p, randomisation | 0.603 | 0.683 |
| Weight scheme | Rademacher | Rademacher |
| Bootstrap p floor | 0.0005 | 0.0005 |
| n rows / events / clusters | 682 / 18 / 17 | 682 / 18 / 17 |

All three inference procedures agree, which they should when β is this close
to zero.

**The continuous and rank variants now agree in sign** (rank correlation
0.888), where before the FY2023 curation they disagreed.
`config/exposure.yaml` `notes.functional_form` pre-registered the reading: a
disagreement means the scoring function's shape is doing the work. That the
agreement arrived with one extra curation row rather than with a better
specification is not reassurance — it is the same fragility seen from the
other side.

### Pre-registered sensitivity: Budget 2025

`CLAUDE.md` required estimating with and without `budget-2025-eco-abolished`
and reporting both.

| | β | se | p, wild bootstrap | n |
|---|---|---|---|---|
| All events | −0.000568 | 0.000913 | 0.522 | 682 |
| Excluding Budget 2025 | −0.000438 | 0.000971 | 0.632 | 644 |

Excluding it moves β by 0.000130, about 23% of the point estimate, and leaves
the sign and the (non-)significance unchanged. **The pre-registered
sensitivity passes.** That is worth stating plainly — it is the one
robustness check in this report that the design comfortably survives — and it
is worth almost nothing, because §4 shows there is no identified estimate for
it to be robust about.

---

## 4. Why the null is uninformative — the identification audit

This is the section that matters.

### 4.1 Nine rows

| Count | Value | Was (2026-08-18) |
|---|---|---|
| Nominal rows | 692 | 692 |
| Rows with non-zero exposure | **9** | 7 |
| Events with any within-event exposure variation | **8 of 18** | 6 |
| Clusters with any within-event variation | **8 of 17** | 6 |
| Events where exactly one firm is exposed | 7 | 5 |
| Events where two or more firms are exposed | **1** | 1 |
| Distinct exposed firms | **2** | 2 |

At seven of the eight identifying events, a single firm carries the entire
cross-sectional gradient. A regression on one exposed firm and forty zeros is
a one-firm event study wearing a cross-sectional coat.

**The curation moved every count in the right direction and none of them past
the threshold that matters.** Two firms still carry the whole estimate.

### 4.2 Leverage on β, by Frisch-Waugh-Lovell

Ordinary hat values look reassuring — effective firms 30.69 of 40 nominal —
because every row loads on its own event dummy and the fixed effects dominate
the leverage. That number is not measuring what matters.

Partial the exposure column on the event dummies and the controls, and each
row's weight on β is proportional to the square of what is left:

| Unit | Event | Exposure | CAR | Weight |
|---|---|---|---|---|
| KRX.IR | shdf-wave21-awards | +7.28 | −1.33% | 51.83 |
| KRX.IR | energy-security-strategy | +7.28 | −0.76% | 51.72 |
| KRX.IR | heat-and-buildings-strategy | +7.28 | +0.07% | 51.66 |
| KRX.IR | eco4-consultation | +7.28 | +2.56% | 51.66 |
| GEN.L | chmm-delayed | −7.28 | +1.44% | 51.41 |
| GEN.L | budget-2025-eco-abolished | −7.22 | +2.59% | 51.05 |
| GEN.L | autumn-budget-2024 | +7.12 | −3.72% | 50.75 |
| GEN.L | spending-review-2025 | +7.08 | −2.05% | 49.56 |
| KRX.IR | spending-review-2025 | +1.58 | −0.60% | 2.18 |
| NG.L | spending-review-2025 | −0.16 | −0.62% | 0.10 |

**Top ten rows: 97.0% of the weight on β. Effective identifying rows: 8.6 of
692.** The gap between 692 and 8.6 is the whole story of this report.

### 4.3 The drop path

| Dropped | β | n |
|---|---|---|
| — (baseline) | −0.000568 | 682 |
| GEN.L | **+0.000873** | 664 |
| GEN.L, KRX.IR | **not identified** | 656 |
| GEN.L, KRX.IR, BNZL.L | **not identified** | 638 |
| + BKG.L, BWY.L | **not identified** | 602 |

**Removing Genuit alone flips the sign of β.** Removing Genuit **and**
Kingspan leaves no within-event exposure variation anywhere in the panel, so β
does not exist — the estimator's collinearity guard fires, correctly.

> **Correction, 2026-08-19.** An earlier draft of this table showed n *rising*
> from 664 to 666 between the first and second rows, which is impossible.
> `top_k_drop_path` was reporting the post-`dropna` count when the estimate
> succeeded and the pre-`dropna` count when it failed — two different
> quantities under one column heading. Neither branch was wrong alone. Fixed,
> and the monotonicity is now pinned in `tests/test_influence.py`. No
> conclusion in this report depended on it, which is exactly why it survived
> a reading.

Nine observations exceed the conventional Cook's distance threshold of 4/n,
with a maximum of 24,538.

### 4.4 Leave-one-event-out

β ranges from −0.00113 (dropping `eco4-consultation`) to −0.00021 (dropping
`autumn-budget-2024`), a range of 0.00092 — **more than one and a half times
the point estimate, and a third of the quoted MDE.**

The sign no longer flips, which it did before the FY2023 curation. Read that
carefully: the estimate did not become robust, it became *less unstable* while
still varying by 160% of itself on the removal of any single event. Full table
in `reports/tables/leave_one_event_out.csv`.

### 4.5 Why more curation will not fix this — the disclosure gap

This is the finding that reorders the remaining work, and it is a result about
the *measure*, not about this sample.

`product_revenue` is defined as **affected revenue share × UK revenue share**.
The UK multiplier exists for a good reason — without it every foreign
manufacturer inherits full UK exposure — but it requires a country-level
revenue split, and **the firms where it would do real work systematically do
not publish one.** Under IFRS 8 a country is named only when it clears a
materiality threshold, and for these firms the UK does not clear it:

| Firm | UK revenue disclosed? | Evidence |
|---|---|---|
| Kingspan | FY2014–FY2021 only | Names a country only "where revenue exceeds **15%** of total Group revenues". Britain cleared it to FY2021 and stopped in FY2022 |
| Rockwool | **Never** | "In no other country does revenue exceed **10%** of the Group's total revenue" — identical wording FY2020, FY2021, FY2024 |
| Genuit | Yes, ~0.89 | UK-domiciled; revenue by destination given directly |
| Marshalls | Yes, ~1.00 | UK-domiciled |
| Ibstock | Effectively 1.00 | UK-domiciled |

**The multiplier is unobservable exactly where it discriminates.** For the
UK-domiciled firms it sits between 0.89 and 1.00 and does almost nothing; for
the multinationals — which are the large insulation names, the ones a reader
would expect to carry the exposure — it is never published.

The non-disclosure is not a hole, because it comes with a direction. Both
firms' own thresholds **bound** the missing value:

| Firm | Affected share | UK share bound | Magnitude bound |
|---|---|---|---|
| Rockwool FY2024 | 0.7865 | < 0.10 | **< 0.0786** |
| Kingspan FY2024 | 0.2120 | < 0.15 | **< 0.0318** |
| Genuit FY2024 | 0.2879 | 0.8895 (measured) | 0.2561 |

So even a perfect resolution of the missing data would leave Genuit the
largest exposure in the sample by a factor of three, and would add **two**
firms, not twenty. **The cross-section this estimand needs does not exist in
the disclosure record**, and no quantity of curation hours changes that.

Two honest routes out, both changes to the design rather than to the effort:

1. **Drop the UK multiplier and restrict the universe to UK-domiciled firms.**
   The channel becomes affected-share alone, which *is* disclosed. This trades
   a defensible measure on a tiny cross-section for a cruder measure on a
   larger one, and it must be pre-registered before it is run.
2. **Report the study as what it is** — a measurement paper about why a
   theoretically clean exposure measure is not estimable from public
   disclosure, with the bounds above as the substantive contribution.

Route 2 is the honest default and `CLAUDE.md` §5 of the governing standards
anticipates it: a clean, well-diagnosed demonstration that the data cannot
support the estimand is a stronger portfolio piece than a marginal positive
reached by trying specifications.

---

## 5. Limitations, each with its direction

A caveat with a known direction is a bound. A caveat without one is a hole.

**Exposure curation is the binding constraint — direction: toward zero, and
toward no identification at all.** Two firms carry every non-zero score.
`product_revenue` is curated for Genuit and Kingspan; Marshalls and Ibstock
are curated as *measured zeros* on the affected categories; Rockwool has a
verified insulation share (0.7865 at FY2024) but discloses no UK revenue
figure, so it cannot be scored on a channel defined as affected-share × UK
share; SIG plc has no price series; Saint-Gobain and Travis Perkins are not
curated. This is not a bias with a sign so much as an absence of the data the
estimand needs.

**Back-vintages are missing, and that is why only six events identify.** Every
Genuit, Marshalls and Ibstock attribute is `knowable_from` March 2025, so the
point-in-time filter correctly withholds them from the eighteen events that
pre-date it. Only Kingspan carries pre-2025 vintages (FY2014, FY2019, FY2020,
FY2021). **The fix is not more firms; it is more vintages of the firms already
curated.** That single observation reorders the remaining work.

**`book_to_market` is dropped from the controls — direction: away from zero.**
It needs point-in-time book values the project has not acquired. Exposure here
concentrates in building-products names carrying a value tilt, and value earns
a positive average premium; whatever `size`, `momentum` and `pre_event_vol`
fail to absorb loads onto β. **The estimate is an upper bound on the policy
channel.** Full reasoning in `estimators/controls.py`.

**`size` is log average daily turnover, not market capitalisation.** Share
counts are only available at today's vintage, and applying them to a 2015
price manufactures a market cap that never existed — with a look-ahead, since
share counts move on the buybacks that follow these events.

**The `residential_stock` channel is retired — direction: the study is now
one-sided.** It existed to carry the falsification test: a tightening should
move insulation makers up *and* landlords down. At all three `domestic_prs`
events the channel was Grainger alone (Civitas delisted 2023-08-04; Unite is
approximately zero on two independent grounds; `RESI.L` was not approved). A
falsification test resting on one firm is not a falsification test. The study
therefore cannot distinguish "policy moves exposed firms" from "something else
moved building-products names on those dates".

**The screening universe is not built.** `data/universe/uk_listed_universe.csv`
is still header-only; the cross-section here is the 55-name curated universe.
The builder is written and tested (`data/screening.py`,
`scripts/build_screening_universe.py`) and needs one run with network access.
**Direction: this is the least important of the limitations.**
`dose_response.md` §2.5 measured that going from 100 to 600 firms moves the
MDE by under 5%. Widening the cross-section would not have rescued this
result.

**Leak detection was under-powered — direction: measured effects are lower
bounds.** Unchanged from `CLAUDE.md` §4; the news sources block the tooling.

**Survivorship.** The universe is built from firms the price source still
serves. In a *screening* universe this inflates se(α_e) and leaves β alone,
because the absent firms carry zero exposure either way. In the *treated* set
it is a genuine gap, and `PRSR.L` and `SIG.L` are concrete instances.

---

## 6. What would actually fix this, in order

**This list was rewritten on 2026-08-19.** The previous version's first
item — "curate back-vintages for Genuit, Marshalls and Ibstock … moves
identifying events from 6 to plausibly 15+" — was tested and is **wrong for
two of the three firms**, for reasons that are arithmetic rather than
effort-related. What replaced it:

1. **Decide between the two design routes in §4.5.** This is now the first
   question, not the last. More curation of the current channel definition
   cannot produce the cross-section the estimand needs, because the UK
   multiplier is not published by the firms where it matters. Route 1 (drop
   the multiplier, restrict to UK-domiciled firms) must be pre-registered
   before it is run; route 2 reports the measurement finding as the result.
2. **Curate Saint-Gobain**, the one remaining firm that might carry a UK
   figure. `saint-gobain.com` returns HTTP 403 to the tooling, so this needs a
   fetch from elsewhere. **Blocked ≠ absent**, and it is recorded as blocked.
3. **Run `make screening-universe`** on a networked machine. One command, and
   `dose_response.md` §2.5 already measured that 100 → 600 firms moves the MDE
   by under 5%. Do it for completeness, not for rescue.
4. **Re-run `make estimate` and `make diagnostics`**, reading
   `effective_identifying_rows` before β.

**What was removed from this list, with the evidence:**

| Removed | Why |
|---|---|
| Marshalls and Ibstock back-vintages | Both are measured zeros on every affected category. A curated zero and an uncurated default zero give the **same** `exposure_magnitude` and the **same** `exposure_signed`; only the `channel` label differs and no label enters the regression. Verified by construction |
| Genuit back-vintages before FY2023 | Genuit reported two **end-market** segments until the FY2023 results. The affected category did not exist as a disclosed quantity, so there is nothing to curate. R1a |
| Travis Perkins | A merchant reporting by end market. Insulation and heating are proper subsets of an unsplit segment, so R1a points to ABSENT, and its UK share of ~1.0 would do no work |

The one item that *was* delivered from the old list — Genuit's FY2023
vintage — moved identifying events 6 → 8 and effective rows 6.5 → 8.6, and
moved β six-fold. That is the measured return on the highest-value curation
row available, and it is the basis for expecting the rest to return less.

---

## 7. What was NOT run, and why

**Synthetic control and synthetic DiD.** Coded, tested, and deliberately not
run. `CLAUDE.md` §1 records the instruction and the reason: running them
before a dose-response result exists invites reporting whichever design gave
the nicer answer. A dose-response result does not yet exist in any meaningful
sense — §4 — so the condition for running them has not been met. They stay
parked.

**Conformal inference.** Dropped from scope. It escapes the 1/(N+1)
randomisation floor, which is not the constraint here; the constraint is 8.6
identifying observations, and no inference procedure fixes that.

**Placebo-in-time and placebo-in-space.** Not run against this panel. A
placebo distribution answers "could noise produce a β this large?" — a
question worth asking of an identified estimate. Running it on a β supported by
nine rows would produce a number with no interpretation, and the temptation to
quote it as reassurance is exactly why it is being skipped rather than run and
caveated.

---

## Reproducing this

```bash
make prices        # needs network; vintage 2026-08-17 used here
make estimate      # writes reports/tables/car_panel.csv and dose_response.json
make diagnostics   # writes identification.json and leave_one_event_out.csv
```

Tables behind every number above are in `reports/tables/`.
