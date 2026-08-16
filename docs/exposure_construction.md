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

## 7. What is not yet done

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
