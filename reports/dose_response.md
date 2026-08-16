# Dose-response: do firms move in proportion to policy exposure?

**Status: pipeline complete, MDE in, no estimates yet.** Curation of the event
dictionary, the exposure attributes and the screening universe is outstanding.
Everything below is either a pre-registered decision or a design-level result
that does not depend on the data.

Structure follows the Phase 1 report: design change and why, **MDE first**,
then estimates, then diagnostics, then limitations.

---

## 1. The design change, and why

Phase 1b's power diagnostic settled the question before any data was pulled.
The synthetic-control design asked *"did the announcement move the treated
firms?"* and identified from a handful of treated units against 23 donors. That
gave:

- a permutation p-value floored at **1/24 = 0.042**, making 1% significance
  arithmetically impossible for any effect size;
- a 20-day **MDE of 12–24% cumulative abnormal return**, larger than any
  plausible UK policy announcement effect.

The study as specified could not detect what it was looking for. So the
estimand changes.

**New question: did the announcement move firms *in proportion to their policy
exposure*?** Identification now comes from cross-sectional variation in
exposure across the whole listed universe — abundant — rather than from a
handful of treated units — not. Three consequences:

- **Zero-exposure firms become informative observations.** They pin down the
  event fixed effect `α_e`, which absorbs the common market move on the
  announcement date. Previously they were donors at best and discarded at worst.
- **Common shocks are absorbed by construction.** A macro release on the
  announcement day hits high- and low-exposure firms alike and lands entirely
  in `α_e`. It biases β only if it is *correlated with exposure* — a far weaker
  requirement than the SC design's.
- **Power scales with the cross-section and the event count**, not with the
  number of treated units.

Synthetic control and SDiD are **not deleted**. They become the robustness
section (§9), to be run on the three or four highest-surprise events once
curation is complete.

### What the change does not buy

It does not rescue a confounded event. A construction-sector shock landing on a
housing-policy day is correlated with exposure and biases β directly; event
fixed effects absorb the common component, not the exposure-correlated one.
Confounded events remain confounded and are still reported separately.

---

## 2. Minimum detectable effect

Reported before the estimates, per the Phase 1b precedent, and computed on this
design rather than carried over.

### 2.1 The bootstrap has its own p-value floor

Escaping the permutation design's 1/(J+1) floor walked straight into another
one. With Rademacher weights and `G` clusters the bootstrap admits only `2^G`
distinct sign vectors; because the two-sided statistic is symmetric under a
global sign flip, attainable p-values come in steps of **2/S^G**, not 1/S^G.
That factor of two is confirmed by the textbook result that Rademacher at
G = 5 cannot go below 6.25% = 2/2^5.

| Events | Rademacher floor | Webb floor |
|---|---|---|
| 4 | **0.125** | 0.0015 |
| 5 | 0.0625 | 0.00026 |
| 6 | **0.031** | 0.000043 |
| 8 | 0.0078 | 0.0000012 |
| 10 | 0.0020 | ~0 |

**The default is now Webb six-point weights** (±√1.5, ±1, ±√0.5, each with
probability 1/6 — mean zero and unit variance like Rademacher, but 6^G
vectors). Rademacher remains available. The scheme is a **required argument
with no default**, and the floor is a **field on the result object**, not
prose, so a design that cannot reach the level being claimed is visible at the
call site.

**Does this change any conclusion in the previous report? At six events, no.**
Realised power is identical under the two schemes (71% / 92% / 96% at 1.0× /
1.5× / 2.0× the analytic MDE), because Rademacher's 0.031 floor still sits
below 0.05 and the test can reject. What Webb buys is robustness against a
*thin* event count: **at four events Rademacher's floor is 0.125 and 5% is
unreachable for any effect size**, while Webb's is 0.0015. Given that Phase B0
may well yield four clean events rather than six, that is not a hypothetical.

The narrower point stands regardless: at six events Rademacher offered a single
usable rung below 0.05, and a p-value sitting on the floor is a statement about
resolution, not about evidence. `DoseResponseResult.at_the_floor` flags exactly
that case.

### 2.2 How the MDE is computed, and one trap avoided

MDE = (z₀.₉₇₅ + z₀.₈₀) × se(β), with se(β) the **cluster-robust** standard
error from the fitted model. `CLAUDE.md` §3's effective-observation count is
then *derived* from that standard error, not assumed.

> **The obvious route is wrong here and fails silently.** The natural approach
> is a design-effect haircut, `N_eff = N / (1 + (m−1)ρ)`, with ρ the
> within-event residual correlation. But **event fixed effects demean the
> residuals within each date**, so an intraclass correlation read off the
> event-level variance share collapses to ≈0 — and, once demeaned, the average
> *pairwise* residual correlation across firms is mechanically ≈ −1/(n−1)
> rather than positive. Either way the design effect comes out at 1.0 and the
> MDE is **5.6× too optimistic**, with an entirely plausible-looking number.
>
> The dependence that genuinely inflates se(β) is the component correlated
> *with exposure*, which is exactly what the cluster-robust sandwich measures.
> This was caught in construction, is recorded in the decision log, and carries
> a regression test.

### 2.3 The numbers

Calibrated on simulated panels with a sector factor hitting the exposed block —
the realistic case, since exposure concentrates in sectors whose members
co-move. Daily residual volatility 2.0%, sector factor 0.6%/day, 300-firm
universe, 8% exposed. **Placeholders to be replaced with empirical values once
prices are pulled**; the ordering and the ratios are the durable part.

| Events | Window | se(β) | Analytic MDE | Effective N | Design effect |
|---|---|---|---|---|---|
| 4 | [0,0] | 0.00060 | 0.17% | 1,986 | 1.3 |
| 4 | [0,1] | 0.00085 | 0.24% | 1,986 | 1.3 |
| 6 | [0,0] | 0.00053 | 0.15% | 2,123 | 1.4 |
| **6** | **[0,1]** | **0.00074** | **0.21%** | **2,123** | **1.4** |
| 6 | [0,2] | 0.00091 | 0.26% | 2,123 | 1.4 |
| 10 | [0,1] | 0.00057 | 0.16% | 2,785 | 1.3 |
| 15 | [0,1] | 0.00046 | 0.13% | 4,089 | 1.2 |

### 2.4 The analytic MDE is optimistic — use the calibrated one

The analytic figure uses a normal approximation. The headline test is the wild
cluster bootstrap, which with single-digit event counts is materially more
conservative. Simulating realised rejection rates:

| Events | Analytic MDE | Realised power at it | **Calibrated MDE (80% power)** |
|---|---|---|---|
| 6 | 0.19% | **55–71%** | ~1.4× → **0.27%** |
| 10 | 0.15% | ~75% | ~1.3× → **0.20%** |

Realised power varies across calibration runs by more than the third
significant figure, so the multiplier is quoted as approximate rather than
implying precision the simulation does not carry.

**Report the calibrated figure.** `dose_response_mde(se_inflation=1.5)`
reproduces it and the inflation is disclosed rather than applied silently.

### 2.5 What this means

> **Headline: the bootstrap-calibrated MDE is ≈0.3% cumulative abnormal return
> per standard deviation of exposure, at the [0,1] window with 6 events.**
> Against the SC design's 12–24%, that is a 40–80× improvement in detectable
> effect size.

Converting to something economically readable: with ~8% of the universe
exposed, a fully-exposed firm sits ~5 SD out, so β = 0.003 corresponds to a
fully-exposed firm moving ≈1.5%. **That is squarely inside the range a real
policy announcement plausibly produces.** The design is adequately powered for
the hypothesis it now tests — which the previous one was not.

Two further points the table makes:

- **Universe size barely moves the MDE; event count does.** Going from 100 to
  600 firms changed the MDE by under 5%, while 4→15 events roughly halved it.
  With large clusters, effective N is governed by the number of independent
  dates. **Curation effort belongs on finding more clean events, not on
  extending the cross-section**, which inverts the guidance the SC design would
  have given.
- Short windows dominate. [0,1] costs ~40% more MDE than [0,0]; [0,20] costs
  roughly 4×. Hence the default below.

### 2.6 MDE against event count

The curve `make event-report` prints while curating, so the marginal value of
one more event is visible before the file is finished rather than after.

| Events | Webb floor | Rademacher floor | Analytic MDE | MDE index (6 = 1.00) |
|---|---|---|---|---|
| 4 | 0.0015 | **0.125 — 5% unreachable** | 0.22% | 1.22 |
| 6 | 0.00050 | 0.031 | 0.19% | 1.00 |
| 10 | 0.00050 | 0.0020 | 0.15% | 0.77 |
| 15 | 0.00050 | 0.00049 | 0.13% | 0.63 |

Two readings, and the second is the operationally useful one:

- MDE scales roughly as 1/√events, so going from 6 to 15 clean events buys a
  ~37% reduction. Real, but not transformative.
- **The floor is a cliff, not a slope.** Below five events Rademacher cannot
  reach 5% at all; Webb removes that cliff entirely. Choosing the weight scheme
  correctly is worth more than several extra events, and costs nothing.

At Webb, the floor stops binding above ~5 events and the draw count (2,000)
becomes the limit at 1/2001 = 0.0005.

---

## 3. Pre-registered design

Fixed before estimation. Any change is a new specification with a decision-log row.

| Decision | Value | Why |
|---|---|---|
| Specification | `CAR_ie = α_e + β·Exposure_ie + γ'Controls_ie + ε_ie` | β is the estimand; H₀: β = 0 |
| Event windows | [0,0], [0,1], [0,2] | Resolved against the LSE open/close convention |
| **Headline window** | **[0,1]** | Short windows are far better powered — §2.5 |
| Longer horizons | sensitivity only | The power arithmetic is the reason and is stated, not implied |
| Controls | size, book-to-market, momentum, pre-event volatility | So β is not a known factor tilt. Pre-event vol matters most: exposure concentrates in small-cap building products, where it would otherwise proxy for riskiness |
| Exposure | `exposure_continuous` (standardised within event) | `exposure_rank` is the pre-registered robustness variant |
| **Headline inference** | **wild cluster bootstrap, Webb weights** | Null imposed. Cluster-robust asymptotics need many clusters and over-reject with single digits; Webb keeps the p-value floor off the threshold (§2.1) |
| Weight scheme | required argument, no default | The floor it sets is a design property the caller must choose deliberately |
| Also reported | clustered SE, within-event randomisation | See §5 |
| Significance | 5%, two-sided | |

### Event-day resolution

Unchanged from Phase 1 and already implemented: an announcement is located
using both the LSE **open and close**. A 07:30 release lands in the overnight
window, so that day's close-to-close return is entirely post-announcement; a
mid-session release makes the day straddling, and `t0` moves to the next day
with the straddling day reported separately.

---

## 4. Estimates

_Pending curation._

Every row will carry, and cannot be rendered without: β; all three p-values;
**the bootstrap p-value floor beside the bootstrap p-value** (§2.1); the
calibrated MDE above it; **the effective firm count beside the nominal one**
(§6); the influence verdict; the falsification verdict; and the sensitivity
battery from `docs/exposure_construction.md` §4.

Two of those are enforced in code rather than by convention:
`MissingInfluenceError` refuses a β without its influence diagnostics, and
`p_floor_bootstrap` is a required field on the result object rather than
something a writer must remember to quote.

---

## 5. Inference — three procedures, reported together

| Procedure | Null | Reads |
|---|---|---|
| `p_cluster` | asymptotic, clustered by event | **For comparison only.** Over-rejects with few clusters |
| `p_wild_bootstrap` | **Webb** wild cluster bootstrap, null imposed | **Headline.** Imposing the null is what makes it work with few clusters; Webb weights keep the floor off the 5% threshold. Reported *always* beside `p_floor_bootstrap` |
| `p_randomisation` | permute exposure within each event | **Sharpest.** Conditions entirely on realised returns |

The randomisation test deserves emphasis: it asks whether the observed
exposure-return gradient is unusual against the distribution of gradients
obtainable by reassigning the *same* exposure values among the *same* firms on
the *same* day. Returns are never resampled, so no distributional assumption
about them enters, and the common market move on each date is held fixed by
construction. Permutation is **within** event — permuting across events would
break the fixed effects and test a weaker null.

Where the three disagree, the clustered p-value is the one to distrust.

---

## 6. Influence: is β identified off the cross-section or off five names?

**A required section. A missing one is a hard failure, not an omission** —
`DoseResponseSection` raises `MissingInfluenceError` if a β would be rendered
without it, exactly as `MissingPlaceboError` guards the synthetic-control
effects.

### 6.1 Why this is the design's most likely failure mode

§2.5 notes that a fully exposed firm sits ~5 SD out. That is a direct
consequence of exposure being heavily right-skewed with most of the universe at
exactly zero — and it means the nominal sample size is not the identifying one.
**Several hundred observations with five influential ones is the small-N problem
wearing a large-N regression as a costume.**

Nothing else in the pipeline surfaces it. The clustered standard error, the wild
bootstrap and the randomisation test are all computed on the same design matrix
and are all equally content to let a handful of leverage points carry the
answer. The p-value would look fine.

### 6.2 The five checks

| Check | Question | Failure means |
|---|---|---|
| Hat values, Cook's distance, leverage share of the top 1% / 5% | How concentrated is leverage? | The design is not what the row count suggests |
| **Top-k drop path**, k = 1, 2, 3, 5 | Does β survive dropping the most exposed firms? | **A β that dies at k = 3 is a statement about three firms, not about exposure** |
| Winsorised exposure, 1st/99th within event | Is one extreme score levering the fit? | The gradient is an artefact of the tail |
| `exposure_continuous` vs `exposure_rank`, head to head | Does the result depend on the scoring function's shape? | The functional form is doing the work, not the ordering |
| **Effective firm count** (leverage participation ratio) | How many firms actually contribute? | The nominal N is misleading |

Whole *firms* are dropped in the drop path, not single rows: a firm appears once
per event, and removing one of its observations would leave the rest of its
influence in the fit.

The effective firm count is the inverse Herfindahl of each firm's share of total
leverage — the same construction as the donor-weight concentration measure in
the synthetic-control diagnostics. **The nominal firm count never appears in
this report without it beside it**, and `DoseResponseSection.headline_table`
emits the two columns together so they cannot be separated by accident.

### 6.3 Verdict, not a number

`InfluenceReport.verdict` returns one of:

- **FRAGILE** — β does not survive the drop path, or the continuous and rank
  variants disagree in sign. Names the firms responsible.
- **CAUTION** — β survives, but the top 5% of observations hold over half the
  leverage. Reports the effective cross-section against the nominal one.
- **ROBUST** — survives the drop path, forms agree, leverage not concentrated.

`DoseResponseSection.trustworthy` is deliberately conjunctive and deliberately
**not about the p-value**: a significant β that fails the drop path is not a
result, and an insignificant one that passes every structural check is an
informative null.

_Estimates pending curation._

---

## 7. Falsification: mandate versus repeal

Now executable, not a design property described in prose.

Exposure sign is anchored to policy **direction** rather than to the individual
event, so one `channel_sign` per firm serves every event. That buys a
falsification test for free: on the direction-neutral measure
(`exposure_channel_signed` = magnitude × channel_sign, without the tighten /
loosen multiplier),

> **a mandate and its repeal must produce opposite-signed betas.**

An insulation manufacturer gains when a standard is tightened and loses when it
is repealed. Equivalently on `exposure_signed`, where the direction multiplier
is already folded in, the two subsamples must give the *same* sign; both
framings are computed and agreement between them checks the panel construction
rather than the hypothesis.

**If the signs agree on the direction-neutral measure, the exposure construction
is measuring something other than policy exposure**, and the report must say so
plainly rather than reporting the pooled β as though the check had passed. The
likely culprits, in order: exposure proxying for a persistent firm
characteristic (small-cap building-products names are riskier in every state of
the world and earn a premium on any date); a mis-coded `direction`; or events
that are not mirror images.

This is a **pre-registered falsification check, not a subgroup finding.** Both
subsamples are reported whatever they show, and a pass is not evidence for the
pooled result — only the absence of one specific disconfirmation.

`direction` is now a **required column of the event dictionary with no
default**, precisely so the test cannot be removed by omission.

### Power of the check

Splitting the sample halves the events on each side. Since the MDE scales with
event count rather than cross-section, each side's MDE rises by roughly √2 and
its p-value floor rises steeply — which is a further argument for Webb weights,
because a 6-event study splits into two 3-event subsamples where Rademacher's
floor is 0.25. `SignConsistencyResult` carries each side's own floor and reports
`UNDERPOWERED` rather than a verdict when either side cannot reach 5%.

_Pending curation. If the curated events contain no loosening announcement the
test cannot run, and `verdict()` returns `NOT RUN` — which is reported as a
standing limitation, not passed over._

---

## 8. Other diagnostics

| Diagnostic | Question |
|---|---|
| Exposure dispersion per event | With no cross-sectional variation there is nothing to identify from, however many firms |
| Non-zero exposure count per event | A gradient resting on three firms is not a cross-sectional design |
| Placebo dates | β on non-event dates matched on day of week and volatility regime |
| Sensitivities S1–S7 | `docs/exposure_construction.md` §4 |
| Withheld-attribute count | How much curated data the point-in-time filter refused |
| Event spacing | Events closer than 14 days are rejected without an explicit `overlap_ack`: overlapping windows are not independent clusters, and the bootstrap floor is set by the nominal cluster count rather than the effective one |

**Placebo dates are the primary falsification.** Matched on day of week and
volatility regime, they answer whether the exposure-return gradient is special
to announcement days or a standing feature of the cross-section. A firm
characteristic correlated with a persistent risk premium would produce a
non-zero β on *any* date, and only the placebo distribution catches it.

**The strongest falsification is free.** Because the sign convention is
anchored to policy direction, the same exposure measure must produce
opposite-signed betas on a mandate and on its repeal. If a tightening and a
rollback both produce positive β, the measure is picking up something other
than policy exposure.

---

## 9. Retained: synthetic control and SDiD as robustness

**Not started — gated on this report, per instruction.** To be run unchanged on
the three or four events with the lowest `anticipation_risk`, reported beside
the dose-response result with their MDE stated. They will be underpowered; §1
gives the numbers, and the write-up must say so plainly rather than present an
uninformative null as a finding.

Planned addition: **conformal inference for synthetic control**
(Chernozhukov, Wüthrich & Zhu, 2021), which is not bounded below by 1/(N+1) and
so escapes the arithmetic floor that made 1% unreachable. Both will be
reported, with the difference explained: the permutation p-value tests
exchangeability across units, the conformal p-value tests exchangeability of
residuals across *time* within the treated unit. They are different nulls, and
a divergence is informative rather than a contradiction.

---

## 10. Limitations

**Confounding is not solved.** Event fixed effects absorb the common component
of a same-day shock, not the exposure-correlated component. This is the
design's main residual vulnerability and it is why confounded events remain
separately reported.

**Exposure is measured with error, and the direction is known.** Classical
measurement error in a regressor attenuates β toward zero, so a null is
*conservative* — but a null could also mean the exposure measure is poor. The
S1 rank variant and the mandate/repeal sign test are what separate the two.

**Survivorship, and it now bites the treated set directly.** `PRSR.L` (PRS
REIT) returns HTTP 404 from yfinance — taken private, no continuing series. It
is recorded in `config/universe.yaml` under `unresolved:` rather than
substituted or silently dropped. The screening universe will contain more.

**The Barratt series is a confirmed splice hazard, now structurally blocked.**
`BTRW.L` returns 9,776 rows back to 1988: Yahoo renamed Barratt Developments'
entire pre-merger history to the post-merger symbol, and serves neither
`BDEV.L` nor `RDW.L`. A naive pull *is* the forbidden splice. The config now
carries two distinct units (`BARRATT_PRE`, `BTRW.L`) sharing one source with
non-overlapping availability bounds, plus an exclusion window over the
2024-02-07 → 2024-11-20 bid-and-completion period. Merger completion is dated
2024-08-20 from an 82.3m-share volume spike against a ~6m trailing median,
corroborated by 1.39bn shares outstanding against Barratt's ~970m standalone.

**Redrow's standalone pre-merger returns are unavailable** from this source, so
Redrow is absent from the pre-merger treated set.

**Utilities contribute nothing by construction.** Four otherwise well-exposed
names enter with exposure zero because their sign cannot be determined ex ante.
Deliberate, and a real loss — see `docs/exposure_construction.md` §2.1 and
sensitivity S3.

**Cross-market clock alignment.** Computed, not assumed: only the US names
close after the LSE (+4h30m) and are lagged one trading day. Euronext, Xetra
and Dublin are *simultaneous* with London. Copenhagen closes 30 minutes early,
which is uncorrectable — the fix would need a lead — and is disclosed.

**Curation is the binding constraint, and the tooling now says so while you
work.** `make event-report` prints, per event: the resolved trading day under
the LSE open/close convention, the universe status resolution with any
overrides and drops, and the MDE-versus-event-count curve recomputed over the
current file. `data/events/candidates.md` carries the primary-source rule —
announcement timestamps from news coverage rather than GOV.UK or Hansard are
exactly the errors that quietly break this design, since a wire timestamp is
when the story was filed, not when the announcement was made.

**yfinance licence.** Unofficial scraper, no redistribution licence, personal
research use only; price data is gitignored. Institutional access would remove
this and the survivorship problem together.

---

## 11. What did not work

Required by `CLAUDE.md` §5. Three entries so far, all from construction rather
than estimation; all three would have produced plausible-looking wrong numbers.

**A wild bootstrap with its own undisclosed p-value floor.** Rademacher weights
with 6 clusters admit 2⁶ sign vectors, flooring the two-sided p-value at 0.031 —
having just escaped the permutation design's 1/(J+1) floor, the replacement
inference carried the same defect through a different mechanism. Switched to
Webb six-point weights, made the scheme a required argument, and put the floor
on the result object as a field. At six events no conclusion changes; at four
events Rademacher makes 5% unreachable entirely.

**A design-effect MDE that was 5.6× too optimistic.** The intraclass
correlation was read off the event-level residual variance share — which event
fixed effects force to ≈0 by construction. Replaced with an MDE built on the
cluster-robust standard error, with effective observations derived from it
rather than assumed. Regression test added. See §2.1.

**A reconstructed `auto_adjust` mode that tested nothing.** Rebuilding Yahoo's
back-adjusted series from raw closes is circular: a pure back-adjustment
cancels in consecutive returns, so the mode reduced to the point-in-time
construction and compared a series with itself. Replaced with Yahoo's own
fetched series. The algebra became a documented finding — retroactive
adjustment moves levels, not returns — which is what makes the price-level ban
load-bearing rather than stylistic.

**An MDE calculation that inverted one- and two-sided power.** The first
version took both the critical value and the power quantile from the absolute
placebo distribution, making a two-sided test appear *more* powerful than a
one-sided test on the same data. The critical value comes from the statistic
the test thresholds; the power quantile must come from the signed distribution.

Also logged, from Part 0: the event-day resolver initially used the LSE close
alone and misclassified pre-market announcements as straddling; and the
estimators initially never evaluated the counterfactual gap over the embargoed
days, which silently broke both the `(−1,+1)` window and the pre-trend holdout.
