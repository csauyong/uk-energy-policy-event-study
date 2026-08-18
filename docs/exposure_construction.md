# Exposure construction

The exposure score is the project's core contribution and the part a reader
cannot reproduce from public method descriptions. This document records every
judgement call, every mapping from disclosure to firm, and the sensitivity of
the result to each.

Machine-readable counterparts: [`config/exposure.yaml`](../config/exposure.yaml)
(pre-registered scoring configuration),
[`src/policy_event_study/exposure/`](../src/policy_event_study/exposure/).
Where this document and the code disagree, the code wins and this file is the bug.

**Status: schema and channels complete, curation outstanding.**
`data/exposure/firm_attributes.csv` and `data/exposure/policy_targets.csv`
ship header-only.

---

## 1. What the score is

For firm *i* and event *e*:

```
magnitude_ie  ∈ [0,1]   the fraction of the firm's business the policy touches
signed_ie     = magnitude_ie × channel_sign_i × event_direction_e
exposure_continuous = signed, winsorised then standardised WITHIN event
exposure_rank       = decile rank of signed, WITHIN event
```

### 1.1 Why it is signed

This is the single most consequential choice in the construction, so it is
stated first.

The regression is `CAR_ie = α_e + β·Exposure_ie + …`. Under one insulation
mandate, a fabric manufacturer gains and a residential landlord loses. If
exposure were an unsigned magnitude both would score high, β would average
their opposite responses toward zero, and a null would be uninterpretable —
indistinguishable from "the policy did nothing".

So exposure carries the sign of the firm's *payoff*. The unsigned magnitude is
retained as `exposure_magnitude` and an unsigned specification is available as
a robustness run, but it is not the headline.

**The sign convention is anchored to the policy direction, not the event.**
`channel_sign` is the sign of the payoff under a **tightening**; a loosening
event multiplies by −1. One field then serves every event, and it produces a
falsification test worth more than any single estimate: *the same exposure
measure must produce opposite-signed betas on a mandate and on its repeal*. If
it does not, the measure is picking up something other than policy exposure.

### 1.2 Why dose is a share, not a size

A landlord with 100,000 dwellings all at band B has no capex obligation under a
mandate at C. A landlord with 5,000 dwellings all at band F has a large one.
Dose is therefore the share of the portfolio **requiring work**.

Scaling by portfolio size would mostly recover market capitalisation, and the
regression already controls for size — the exposure coefficient would become a
size effect wearing a policy label. This is the most likely way for the design
to produce a spurious positive, and the share-not-size construction is the
defence.

---

## 2. The four channels

| Channel | Applies to | Magnitude | Sign | Ambiguous? |
|---|---|---|---|---|
| `residential_stock` | Landlords, resi REITs | share of held dwellings below the mandated band | −1 | no |
| `delivered_stock` | Housebuilders | share of delivered units below the mandated band, capped at 0 if the firm's build standard already meets the mandate | −1 | **yes** |
| `product_revenue` | Insulation, heating, glazing, building products | revenue share in affected categories × UK revenue share | +1 | no |
| `domestic_supply` | Utilities, energy retail | domestic supply share | **0** | **yes** |
| *(none)* | everything else | 0 | 0 | n/a |

### 2.1 Judgement calls, one by one

**Housebuilders: the build-standard cap.** A builder already delivering at the
mandated standard faces no compliance cost however large its historic delivered
profile. The cap encodes that. It is a strong assumption — it says compliance
cost is the entire channel and ignores any demand-side effect on new-build
appetite — and it makes the housebuilder dose sparse, since most volume
builders will either clear the standard or not.

**Housebuilders: the sign is genuinely unresolved.** Tightening raises build
cost per unit (−1), but incumbent volume builders absorb compliance cost better
than small builders and have historically passed it through (+1). The default
is −1. `config/universe.yaml` independently records this group as `ambiguous`.
**The report must run the sign-flip sensitivity in §4 rather than assert the
default**, and a result that only survives one sign is not a result.

**Utilities: sign set to zero, so they contribute nothing.** Electrification of
heat is a volume gain for power networks and a volume loss for gas supply, and
Centrica and SSE sit on both sides; National Grid's exposure is regulated capex
responding to mandated investment rather than to retail demand. A channel whose
sign cannot be determined ex ante contributes no information to a *signed*
test, and guessing would contribute noise dressed as signal. These firms enter
with exposure zero and are analysed separately. This is a real loss of four
otherwise well-exposed names, taken deliberately.

**Products: the UK share multiplier, and why it is not defaulted.** A firm with
a large insulation business and no UK revenue has no *UK* policy exposure.
Where `uk_revenue_share` is absent the channel returns "does not apply" rather
than defaulting to 1.0 — defaulting would hand every foreign manufacturer full
UK exposure and would put Owens Corning, D.R. Horton's supplier base and the
European materials names at the top of the exposure ranking for a UK policy.

**Products: revenue outside the affected categories is a measured zero, not an
inapplicable channel.** A firm disclosing 90% flooring revenue and no
insulation has been *measured* as unexposed to an insulation mandate. That
distinction matters for the identification — see §3.

**Bands are read strictly.** An unrecognised band letter raises rather than
being treated as the worst band, which would hand the firm maximal exposure on
a typo.

---

## 3. Zero is data, absent is not

Most of the several-hundred-name screening universe scores exactly zero. **Those
firms are the identification.** They pin down the event fixed effect `α_e`,
which absorbs the common market move on the announcement date, so β is
estimated from the cross-sectional gradient rather than from a before-after
comparison. In the abandoned SC design they were donors at best and discarded
at worst.

So a zero is recorded explicitly and never dropped as missing.

A firm whose exposure is genuinely **unknown** is a different thing and is
excluded with a reason. A false zero is a measurement error that attenuates β
toward zero, and the two must not be conflated. The channels return `None` for
"does not apply" and `0.0` for "measured and unexposed", and `build.py` treats
them differently.

---

## 4. Sensitivities the report must run

Not optional. Each is a pre-registered specification and gets a decision-log row.

| # | Sensitivity | What it tests |
|---|---|---|
| S1 | `exposure_rank` instead of `exposure_continuous` | Whether the scoring function's functional form is doing the work. The rank is monotone-invariant, so agreement means the shape does not matter |
| S2 | `delivered_stock.channel_sign` flipped to +1 | The housebuilder sign ambiguity. A result surviving only one sign is not a result |
| S3 | `domestic_supply.channel_sign` set to +1 and to −1 | Whether excluding utilities cost the design a real signal |
| S4 | Unsigned `exposure_magnitude` | Whether the sign convention is doing the work rather than the exposure |
| S5 | Drop the build-standard cap | Whether the housebuilder dose is an artefact of one strong assumption |
| S6 | Winsorisation off | Whether one leverage point drives β |
| S7 | Exposure computed one vintage earlier | Whether the result depends on the freshest disclosure |

**S1 and S2 are the ones most likely to overturn a positive result.** If S1
disagrees, the mapping from band profile to economic dose is doing the work
rather than exposure itself, and the honest conclusion is that the measure is
not robust. If S2 flips the sign of β, the housebuilder block dominates and the
result rests on an ambiguity the config already flags.

---

## 5. Point-in-time discipline

Every attribute carries `knowable_from`, the date the value became **public** —
usually the report publication date, not the balance-sheet date it describes,
and the gap is routinely four months. `CLAUDE.md` §2.3: the timestamp at which a
feature became knowable determines which prediction it may enter.

`filter_knowable` drops every attribute whose `knowable_from` is at or after the
announcement timestamp, and the builder cannot bypass it.

**The specific leak this prevents is sharp.** A firm's post-announcement
portfolio disclosure — published *because* the policy changed, often quoting
the very exposure the policy created — would otherwise flow into that firm's
pre-announcement exposure score. The regression would then recover the market's
reaction to information it was handed after the fact, and it would look like a
strong result.

Withheld attributes are **counted and reported**, not silently dropped:
`n_withheld_not_knowable` appears on every panel row. A silent drop is
indistinguishable from an absent attribute, and the two have different
consequences for the score.

Restatements: where two vintages are both knowable, the later one is used —
selected on `knowable_from`, not `as_of_date`, since a recently-published older
figure is still the freshest *public* information.

---

## 6. Interpreting β

**β is per standard deviation of a within-event standardised score.** With ~8%
of the universe exposed, the standard deviation is dominated by the zero mass,
so a fully-exposed firm sits several SD out. Concretely, in calibration:

| Share of universe exposed | A fully-exposed firm sits at |
|---|---|
| 2% | ~12 SD |
| 5% | ~7 SD |
| 10% | ~5 SD |
| 25% | ~3.5 SD |

So β must be multiplied by that factor to read as a fully-exposed firm's
abnormal return. **The report must state both** — β per SD, and the implied
effect for a fully-exposed firm — because the per-SD number looks
implausibly small on its own and the firm-level number is the economically
meaningful one.

This also means the exposed share is a reporting parameter, not just a data
property: the same underlying effect produces a smaller β when more of the
universe is exposed.

---

## 7. Curation rules — pre-registered 2026-08-16, before any firm data was read

These were written and committed **before** the first attribute was curated, for
the same reason the leak rule was written before the first search: a rule
authored after seeing the numbers is not a rule, it is a rationalisation.

### R0 — curate blind, and this extends Rule 0 to exposure

`docs/event_curation_protocol.md` Rule 0 forbids looking at price series while
curating events. **It binds equally on exposure curation, and more tightly.** A
date is one number you either find or do not; an exposure weight is continuous
and defensible across a range, so it has far more researcher degrees of freedom.
Curating exposure after seeing which names moved on 20 September 2023 is
selection on the dependent variable through a different door — and it is the
door a sceptical reader checks first, because *"how did you pick the weights?"*
is the standard objection to every dose-response design.

No price series, no return series, no "did this firm move" check, until
`firm_attributes.csv` is frozen and tagged.

### R1 — categories are defined at the coarsest granularity every firm discloses

**A segment is never split into categories the firm does not split.** Genuit
reports Climate Management Solutions as one line covering low-carbon heating,
cooling and ventilation; it does not disclose heating separately from
ventilation. Assigning, say, 60/40 would be a fabricated number entering the
regression as data.

So affected categories are defined at disclosed granularity, and where a firm's
segment spans several, the whole segment is recorded against a combined
category. This over-states exposure for an event targeting only part of the
segment. That is the correct direction to err: over-stated magnitude attenuates
β toward zero, whereas an invented split biases it in an unknown direction.

`policy_targets.csv` therefore names categories the *firms* disclose, not
categories the *policy* distinguishes.

### R1a — a category inside a segment, not spanning it, is ABSENT

Added 2026-08-16 during Tier 3 curation, because R1 met a case it did not
anticipate and stretching it would have been wrong.

R1 handles a segment that spans *several affected categories* — Genuit's
Climate Management Solutions is entirely heating and ventilation, so recording
the whole segment against a combined category over-states nothing that is not
genuinely exposed.

Marshalls is the opposite shape. Roofing Products "comprises Marley Roofing and
Viridian Solar" — an affected business (roof-integrated solar) sitting *inside*
a segment that is mostly unaffected (clay and concrete roof tiles). Recording
the segment total would not over-state a real exposure; it would attribute
revenue that is **not exposed at all** to an affected category, and it would
also drag every other roof-tile maker into a solar mandate. Ibstock makes
concrete roof tiles and would inherit solar exposure it does not have.

**So: where an affected category is a proper subset of a disclosed segment and
the firm does not split it, the attribute is ABSENT, not the segment total and
not zero.** The firm re-enters the moment a split is disclosed. The segment
total is recorded in the row's `note` as context for a later curator, never as
the value.

Consequence, stated plainly: Marshalls currently has no usable
`revenue_share_roof_integrated_solar`, so it drops out of solar-mandate events
— including 2026-03-24, which is the event its own results describe Viridian as
being driven by. That is a real loss and it is recoverable: Marley acquired
Viridian Solar in 2021 and acquisition-year disclosures often state standalone
revenue. **Checking the FY2021 and FY2022 reports for a Viridian revenue level
is the highest-value single outstanding item in product_revenue curation.**

### R2 — the segment-to-category mapping is fixed before the numbers are read

For each firm, write down which reported segments map to which affected
category **from the segment's stated description**, then read the revenue. Not
the other way round. The mapping is recorded in §7.1 below with the firm's own
words, so a reader can disagree with the mapping without re-deriving it.

### R3 — vintage selection

The attribute in force for event *e* is the one with the greatest
`knowable_from` strictly earlier than *e*'s announcement timestamp. Selection is
on `knowable_from`, never on `as_of_date`: a recently-published older figure is
still the freshest *public* information.

### R4 — `knowable_from` is the results-announcement date

Not the year-end, not the annual report PDF date, not the AGM. The RNS results
announcement is when the figures entered the market. For Genuit's FY2024 the
year-end is 2024-12-31 and `knowable_from` is 2025-03-10 — a ten-week gap, and
gaps of four months are routine.

### R5 — no interpolation, no carry-forward, no estimation

A firm-year with no disclosure is **absent**, and absent propagates to "does not
apply" for events that would have selected it. It is never filled by
interpolating neighbouring years, by carrying the prior year forward as if
newly published, or by inferring from a peer.

This is the rule that matters most. Every other error in this project is
visible in a diagnostic; a fabricated exposure value is not. It would produce a
β that looks fine and means nothing, and no sensitivity in §4 would catch it.
`confidence` is recorded per row and any row not read directly from a named
document is `confidence: low` and excluded from the headline specification.

### R6 — measured zero versus does not apply

Restating §3 as an operating instruction. Ibstock disclosing brick and concrete
revenue and no insulation line has been **measured** as unexposed to an
insulation mandate: `value: 0.0`, and it counts in the identification. Ibstock
with no readable disclosure for that year is **absent**: no row, and the firm
drops out for events selecting that vintage. The two must never be conflated,
because a false zero attenuates β while an absence merely shrinks n.

### R7 — restatements

Where a later report restates an earlier year, both are recorded, with their own
`knowable_from`. R3 then does the work automatically: an event before the
restatement sees the original, an event after sees the restated figure. This is
also what makes sensitivity S7 runnable.

### 7.1 Segment-to-category mapping

Fixed per R2 before reading revenue. Firm's own segment description in quotes.

| Firm | Segment | Firm's description | Category |
|---|---|---|---|
| GEN.L Genuit | Climate Management Solutions | "addressing the drivers for low carbon heating and cooling, and clean and healthy air ventilation" | `heating_ventilation` |
| GEN.L Genuit | Water Management Solutions | "climate adaptation and resilience through integrated surface and drainage solutions" | *none — measured zero* |
| GEN.L Genuit | Sustainable Building Solutions | "plumbing and water supply, drainage and other building accessories" | *none — measured zero* |
| MSLH.L Marshalls | Landscape Products | "Commercial and Domestic landscaping business and Landscape Protection" | *none — measured zero* |
| MSLH.L Marshalls | Building Products | "Water Management, Bricks and Masonry, Mortars and Screeds and Aggregate businesses" | *none — measured zero* |
| MSLH.L Marshalls | Roofing Products | "comprises Marley Roofing and Viridian Solar" | `roof_integrated_solar`, **ABSENT per R1a** — not split |
| IBST.L Ibstock | Clay | "leading manufacturer by volume of clay bricks sold in the UK"; Ibstock Kevington masonry and prefabricated components; Ibstock Futures reported within this segment | *none — measured zero* |
| IBST.L Ibstock | Concrete | "concrete roofing, walling, flooring and fencing products, along with lintels and rail & infrastructure products" | *none — measured zero.* Concrete roof tiles are roofing, **not** roof-integrated solar |

Remaining firms are mapped as they are curated; the mapping is written before
the revenue for that firm is read, and the row is dated in
`reports/decision_log.md`.

### 7.2 Rule interactions found during curation

Three, all found by curating rather than by reading the config. Each needs a
decision-log row before scoring.

**(a) An absent `uk_revenue_share` must not drop a firm whose affected shares
are all measured zeros.** `config/exposure.yaml` returns "does not apply" when
`uk_revenue_share` is missing, to stop a foreign manufacturer inheriting full UK
exposure by default. That guard only bites when the affected share is non-zero:
if every affected category is a measured zero, magnitude is zero whatever the UK
share is, and dropping the firm loses a legitimate zero from the identification.
Ibstock is the live instance — its FY2024 RNS carries no geographic note, so its
UK share is absent, yet every affected share is a clean measured zero.
**Builder change required:** absent `uk_revenue_share` → "does not apply" *only
if* some affected-category share is non-zero.

**(b) `policy_targets.csv` has no solar category and needs one.** The
2026-03-24 Future Homes Standard mandates solar generation equivalent to ≥40%
of floor area on most new homes. No affected category covers it. This was
invisible until a firm with solar revenue was curated.

**(c) The `product_revenue` channel captures product-category exposure but not
construction-volume exposure — a documented limitation, not a fix.** Ibstock's
bricks and Marshalls' landscaping go into new homes; a standard that raises
build cost and suppresses starts hits them through volume, not through an
affected product line. Under the pre-registered definition both are measured
zeros for new-build events, which understates them.

This is left unmodelled, for the same reason `domestic_supply` was set to zero:
the sign is ambiguous ex ante — higher standards raise cost per unit but also
value per unit, and the volume effect partly duplicates the `delivered_stock`
housebuilder channel. Adding it now, after seeing which firms it would move,
would be a new specification chosen post-hoc. It is recorded as a limitation and
a candidate for a pre-registered extension in any future work.

---

### 7.3 Open items raised by `policy_targets.csv` (2026-08-16)

24 events, 30 target rows — an event carries one row per (channel, scope) it
touches, which is what lets a single announcement hold opposite signs.

**(a) New-build standards cannot be expressed as an EPC band, and this currently
darkens the entire housebuilder channel. 7 of 7 `new_build` target rows carry a
blank `mandated_min_band`, so `delivered_stock` scores nothing for any event.**

Part L 2021 mandates a 31% CO2 reduction against a 2013 baseline; the Future
Homes Standard mandates 75%. Neither is a band. Writing "FHS = band A" would be
a fabricated value under R5 — a mapping study, not a disclosure — and it would
enter the regression as data.

**RESOLVED 2026-08-16 — option 3. The housebuilder channel is retired and the
study is a products-and-landlords result.** The reasoning is below because a
reader must be able to check it; the summary is that a band-gap dose cannot be
constructed from disclosed quantities, and the two alternatives fail for
independent reasons.

**Why a band mapping (option 1) is not available.** Building regulations do not
mandate a band. Part L 2021 requires that a new dwelling meet a Target Emission
Rate and a Target Primary Energy Rate — `DER ≤ TER` and `DPER ≤ TPER` — both
derived from a *notional dwelling* with reference fabric, services and an on-site
renewables uplift. No SAP score and no band is specified anywhere in the
instrument. Bands are an **outcome** of compliance, not a requirement of it, so
there is no mandated band to cite. Outcome statistics do circulate — the share of
new dwellings achieving band B, the claim that FHS homes will "typically" be A —
but only in trade commentary, and adopting one would be the exact analogue of
taking an event date from news coverage.

**Why bands are not comparable across the sample even as outcomes.** The
calculation methodology changes three times inside the event window: SAP 2012
under Part L 2013, SAP 10.2 under Part L 2021, and the Home Energy Model under
the Future Homes Standard. RdSAP 10 changed the domestic assessment again in
2025, and the EPC metric itself was reformed in the partial response of
2026-01-21. A band in 2015 and a band in 2026 are different quantities computed
by different procedures.

The sharpest way to put this: **`epc-reform-consultation` is in the event
dictionary.** The event list contains the event that breaks band comparability.
Using a band-gap dose across this sample would mean holding the measuring
instrument constant across the announcement that changed the measuring
instrument.

**Why the percentage-step amendment (option 2) also fails.** The steps are
stated — 31% for Part L 2021, 75% for the Future Homes Standard — but against
different baselines, and no step is stated at all for the 2015 cancellation or
the 2019 consultation, so at best 3 of 7 new-build events get a dose. The
firm-side analogue is worse: housebuilders disclose EPC band distributions of
completions, not a percentage compliance margin, so option 2 needs a
band-to-percentage mapping running in the opposite direction and lands back in
the same problem.

**And the firm-side data does not reach the early events regardless.**
Housebuilder EPC completion disclosures begin around 2019–2021. Of the seven
new-build events, three predate any such disclosure. Even a working construction
would cover 4 of 7.

**Consequences, stated rather than absorbed.** The housebuilder block — nine of
twenty-six treated names, the largest single group — contributes no exposure and
is not curated. Sensitivity **S2 is retired as moot**: there is no housebuilder
dose whose sign could be flipped, and §4 is amended accordingly. The seven
`new_build` target rows stay in `policy_targets.csv` with blank bands, as the
record of an exposure the design could not measure. Seven events therefore
contribute to the event list but not to the dose-response, and the report must
say so where it reports n.

This is a real narrowing and it is the honest one. The alternative was a
fabricated mandate value under R5, which no sensitivity in §4 would have caught.

**(b) `net-zero-rollback-2023` has internally offsetting product legs.** The same
announcement delayed the off-grid boiler phase-out (loosen) *and* raised the
Boiler Upgrade Scheme grant 50% to £7,500 (tighten). Net product exposure is
therefore ambiguous by construction, and the clean leg of this event is the
landlord one — which sharpens rather than weakens the case for resolving the
`residential_stock` channel, since it is the only unambiguous signal in the most
important event in the sample.

**(c) `redcar-hydrogen-cancelled` may carry no exposure variance.** It bites only
on hydrogen-ready boiler manufacturers, and no curated firm discloses hydrogen
boiler revenue. If every firm scores zero the estimator will raise. That is
correct behaviour, not a bug: keep the event, record the null, and report it as
an event the exposure measure cannot reach.

### 7.4 Curation mechanics, learned by doing it (2026-08-16)

Four firms curated. Three operational findings, and one of them changes how the
remaining work should be prioritised.

**Fetch the results announcement, not the annual report.** Results press
releases and RNS statements extract cleanly to text; full annual report PDFs are
multi-column and their segment tables are lost in extraction. Genuit, Marshalls
and Ibstock all yielded on the first attempt from a results release. Kingspan's
annual report financial statements yielded the accounting policy and no numbers
at all, and cost three fetches before switching sources.

**~~But results releases carry segments without geography.~~ CORRECTED
2026-08-17 — this was wrong, and it was wrong in the direction that stopped
the curation.** Kingspan's preliminary results statements carry the full
"Analysis of segmental data by geography" note in every year checked
(FY2014, FY2019, FY2020, FY2021, FY2024). The FY2024 prelim was read as
lacking geography because *Britain* is absent from it — but the note is there,
and so is the reason Britain is not in it. See §7.5. The operating lesson
survives in weaker form: fetch the results release first, but when a figure
appears to be missing, establish *why* before concluding the document is the
wrong one.

**Therefore: `uk_revenue_share` is the attribute that moves the exposure ranking
most, and it is least available exactly where it matters most.** For Genuit,
Marshalls and Ibstock the UK share is 0.89–1.00, so it barely moves the
magnitude. For Kingspan it is plausibly 0.10–0.15, which would cut its magnitude
by roughly 85% and could move it from the top of the exposure ranking to the
middle. *(Confirmed 2026-08-17: 0.1539 at the last disclosed vintage. The
prediction was right, and the consequence is §7.5 — Kingspan is not a
top-of-ranking name in this study and never was.)* The names where the
multiplier does real work are the names whose multiplier is hardest to source. Budget the remaining Tier 1 curation around
finding UK revenue shares, not around finding segment splits.

**(d) End market is an unmodelled dimension, and Kingspan makes it material.**
Insulated Panels is 55% of Kingspan's revenue and is genuinely an insulation
product, but it is composite building-envelope systems sold predominantly into
non-residential construction. UK *domestic* efficiency policy does not drive it.
It is recorded as excluded rather than as insulation revenue, on the same
reasoning as R1a: this is not over-statement of a real exposure but attribution
of revenue that is not exposed to the instruments in this study.

The `product_revenue` channel has a category dimension and a geography
dimension but no end-market dimension, so a firm selling insulation into
warehouses scores identically to one selling it into homes. This is recorded as
a limitation, not fixed — adding an end-market split now, after seeing which
firms it would move, would be a post-hoc specification, and most firms do not
disclose a residential/non-residential revenue split in any case.

### 7.5 Kingspan: the disclosure regime changes inside the sample (2026-08-17)

Kingspan's `uk_revenue_share` was the single blocking cell. It is now resolved,
and the resolution is not a number — it is a **date at which the number stops
existing**.

**What Kingspan discloses.** The IFRS 8 geography note names an individual
country only "on the basis of materiality, where revenue exceeds 15% of total
Group revenues". Britain cleared that threshold every year to FY2021 and has
not cleared it since.

| Vintage | `knowable_from` | UK / Britain (€m) | Group (€m) | Share | How it is disclosed |
|---|---|---|---|---|---|
| FY2014 | 2015-02-23 | 687.4 | 1,891.2 | **0.3635** | `United Kingdom`, own column |
| FY2019 | 2020-02-21 | 891.8 | 4,659.1 | **0.1914** | `United Kingdom`, own column |
| FY2019 *restated* | 2021-02-19 | 848.4 | 4,659.1 | **0.1821** | re-cut to `Britain` |
| FY2020 | 2021-02-19 | 743.6 | 4,576.0 | **0.1625** | `Britain`, own column |
| FY2021 | 2022-02-18 | 999.8 | 6,497.0 | **0.1539** | narrative only; last year above 15% |
| FY2022–FY2025 | — | *not disclosed* | — | **ABSENT** | Britain folded into Western & Southern Europe |

Three things follow, and each is a caveat with a direction.

**(a) The FY2019 restatement is a live R7 pair, not a duplicate.** FY2019 was
published as `United Kingdom` €891.8m and restated a year later to `Britain`
€848.4m on the same group total. The €43.4m difference is Northern Ireland
leaving the line. Both rows are carried with their own `knowable_from`, so R3
selects by date. **`Britain` understates UK policy exposure**, so every vintage
from FY2020 on is measured slightly low, which attenuates.

**(b) Absence from FY2022 is evidence, and it bounds the value.** Kingspan did
not stop reporting geography; Britain stopped being material. That is positive
information: **UK revenue is below 15% of group in FY2022–FY2025.** So the
`product_revenue` magnitude is bounded above by `0.15 × affected share` — at
FY2024 that is **under 0.0318, against Genuit's 0.2561**. Kingspan is roughly
an eighth of Genuit's dose at best. *The highest-value cell in the curation was
high-value because of the drop-out mechanics, not because Kingspan would have
topped the ranking.*

**(c) R3 carries FY2021 forward, and the direction of that error is known.**
No later `uk_revenue_share` exists, so 0.1539 remains the freshest *published*
figure and R3 correctly uses it for every event from 2022 on. This is not the
carry-forward R5 forbids — R5 forbids inventing a firm-year, not using the last
published one. But Kingspan's own later accounts imply a value **below 0.15**,
so the carried figure **over-states** its exposure at 8 events. Over-statement
is classical measurement error and **attenuates β toward zero**.

**`revenue_share_heating_ventilation` is ABSENT for Kingspan at every vintage,
per R1a.** Ventilation sits inside `Light & Air` (later `Light, Air + Water`),
a segment that also carries architectural daylighting and water and that
Kingspan does not split. The FY2014 `Environmental` segment is the same shape
and carries no stated description in the source, so R2 cannot fix a mapping for
it either. This is the Marshalls/Viridian case again.

### 7.6 Two defects found by running the pipeline against the curated files

Both were found on the first end-to-end run, which had never happened before:
`config/exposure.yaml` and the code were written before
`data/exposure/policy_targets.csv` existed.

**`Scope` had drifted out of the curated vocabulary.** The enum carried
`domestic / commercial / both`; the curated file uses `all_domestic`,
`domestic_prs`, `social_rented`, `off_gas_grid`, `new_build`. Every one of the
30 target rows failed. Fixed — and it raised rather than coercing, which is why
it was found in one run.

**`PolicyTarget.scope` was parsed, validated and then never read.** No channel
consulted it, so a listed private rented landlord scored full exposure to a
social-rented mandate and a social housing REIT scored full exposure to the PRS
track. **Resolved 2026-08-18 — the stock channels now gate on scope.** See
§7.7.

### 7.7 Scope gating, and what the tenure prefixes mean (2026-08-18)

MEES binds by **tenure**, not by building type. That is why the curation
separated `domestic_prs` from `social_rented` in the first place, and it is why
the two must not score each other's instruments.

**`residential_stock` now selects the band profile of the tenure the target
names.**

| Scope | Band profiles used |
|---|---|
| `all_domestic` | `dwellings_band_` + `dwellings_prs_band_` + `dwellings_social_band_`, summed |
| `domestic_prs` | `dwellings_prs_band_` only |
| `social_rented` | `dwellings_social_band_` only |
| anything else | channel does not apply |

`delivered_stock` applies only under `new_build`: a minimum-EPC mandate on let
property binds whoever *holds* the stock, not whoever built it.

**`product_revenue` and `domestic_supply` are deliberately not gated.** A
manufacturer sells fabric and heating products into whichever tenure the
subsidy or mandate stimulates, so its demand channel is reached by any domestic
scope. Gating it would invent a distinction the firm's revenue disclosure does
not make.

**The generic `dwellings_band_` prefix means "tenure not disclosed", and it has
teeth.** It scores only under `all_domestic`. A landlord curated without a
tenure split therefore scores **nothing** at a tenure-specific event, rather
than being assumed fully private rented — which would be a fabricated value
under R5. The curator is forced to state the tenure, which is a disclosure,
instead of the code assuming one. Nothing is lost today: no landlord band
profile is curated yet, so there is nothing to migrate.

**A PRS landlord's zero on a social-rented mandate is a measured zero**, not a
false one: the instrument genuinely does not reach it. That is the R6
distinction working, and it counts in the identification.

### 7.8 `n` for the dose-response is 18 of 24, not 19

Corrected 2026-08-18 and **pinned in a test**, because the last hand count of
it was wrong by one.

Targets naming neither a mandated band nor an affected category cannot be
scored by any channel. They are now **skipped and counted** rather than scored
as zero — a fabricated zero on every firm at those events would be rows
carrying no information dragging β toward zero, and a blank band reaches
`band_index`, which raises. `validate_exposure_inputs` downgrades them to a
warning so a curator is not forced to delete the record of the retired
`delivered_stock` channel just to make the loader work.

Six events carry no scoreable target at all:

| Event | Why blank |
|---|---|
| `zero-carbon-homes-cancelled` | new-build, no mandated band exists |
| `fhs-2019-consultation` | ditto |
| `fhs-2019-response` | ditto |
| `part-l-2021-published` | ditto |
| `fhbs-2023-consultation` | ditto |
| **`epc-reform-consultation`** | **different reason** — it reforms the EPC *metric* rather than mandating a band, and carries no affected category either |

The 2026-08-16 count of 19 took only the seven blank `new_build` rows and
missed `epc-reform-consultation`. `ten-point-plan` and
`future-homes-standard-2026` each lose an unscoreable leg but survive on a
product leg.

**The report must state 24 for the event dictionary and 18 for the
dose-response**, or the six will read as a silent drop.

---

## 8. What is not yet done

- **Curation.** Both input CSVs are header-only.
- **The screening universe.** `data/universe/uk_listed_universe.csv` is
  header-only; the design needs several hundred UK listings with
  point-in-time listing and delisting dates.
- **Delisted-name register.** `notes.survivorship` requires recording which
  UK mid-caps left the market during the sample. PRS REIT is a confirmed
  instance in the *treated* set — `PRSR.L` returns HTTP 404 — and there will
  be more in the screening universe.
- **Sensitivity S7** needs at least two vintages per attribute, so curation
  must capture superseded disclosures rather than only the latest.
