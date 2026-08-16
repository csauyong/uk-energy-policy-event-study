# Donor pool justification

`config/universe.yaml` requires that "before committing, check each firm's
geographic and segment revenue split and record it in
`docs/donor_pool_justification.md`". This is that record.

**Status: not yet completed.** The table below is the schema and the questions
each row must answer, with the candidate pool as uploaded. No revenue splits
have been verified. Until they are, the donor pool is a set of plausible
candidates, not a screened pool, and the report must say so.

---

## Why this document is load-bearing

The no-interference condition is the assumption synthetic control cannot test
and cannot recover from. A donor with a UK energy-efficiency revenue channel is
not a noisy control — it is a **second treated unit**, and if it moves the same
way as the treated unit it drags the synthetic counterfactual toward the
treatment and biases the estimate toward zero. If it moves the *opposite* way
(as `config/universe.yaml` warns for ITM Power and Ceres Power) it biases the
estimate away from zero.

Neither shows up in a pre-treatment fit diagnostic, because both are
post-treatment phenomena. Nothing in `src/policy_event_study/diagnostics/`
detects them. Only this document does.

---

## Screening questions, per donor

Each row must answer all five. "Probably not" is not an answer to Q1.

1. **UK revenue share.** What fraction of revenue is UK? A firm with material
   UK construction or heating revenue is not a donor.
2. **Segment exposure.** Does any segment sell insulation, glazing, heating,
   ventilation, heat pumps, retrofit services, or EPC-related compliance?
3. **Indirect channel.** Does the firm's UK demand move with domestic
   construction volumes even without a policy-specific product? Staffing,
   distribution and building-products retail all qualify.
4. **Read-through risk.** Would a UK policy announcement plausibly be read by
   the market as a signal about *this* firm's own regulatory environment?
   Relevant for European names ahead of EPBD or EU ETS news — the reason
   `config/universe.yaml` conditionally excludes Nexity and Vonovia.
5. **Listing continuity.** Was the firm listed and trading for the full
   estimation window of every event it is used in? Note any merger, ticker
   change or suspension.

---

## Candidate pool

Tickers as uploaded in `config/universe.yaml`. `verify: true` in that file
marks the names its author already flagged as needing checking.

### Tier 1 — international homebuilders

| Ticker | Firm | UK rev % | Segment exposure | Indirect | Read-through | Continuity | Verdict |
|---|---|---|---|---|---|---|---|
| DHI | D.R. Horton (US) | | | | | | pending |
| LEN | Lennar (US) | | | | | | pending |
| PHM | PulteGroup (US) | | | | | | pending |
| NVR | NVR (US) | | | | | | pending |
| NXI.PA | Nexity (FR) | | | | **flagged: EPBD** | | pending |
| VNA.DE | Vonovia (DE) | | | | **flagged: EU efficiency mandate** | | pending |

Nexity and Vonovia are conditionally excluded for any event tagged
`eu_efficiency_mandate`, `epbd` or `eu_ets`. That exclusion is enforced by
`Universe.donors_for_event` and tested. Vonovia in particular is a German
residential landlord — structurally the same exposure as Grainger, which sits
in the *treated* set.

### Tier 1 — international building materials

| Ticker | Firm | UK rev % | Segment exposure | Indirect | Read-through | Continuity | Verdict |
|---|---|---|---|---|---|---|---|
| OC | Owens Corning (US) | | **insulation maker — check UK share** | | | | pending |
| HOLN.SW | Holcim | | | | | | pending |
| HEI.DE | Heidelberg Materials | | | | | | pending |
| CX | Cemex | | | | | | pending |
| VCT.PA | Vicat | | | | | | pending |

Owens Corning is the highest-risk name in the pool: it is an insulation
manufacturer, which is precisely the treated exposure. The uploaded config
flags it. If its UK share is non-trivial it belongs in `excluded:` alongside
Kingspan and Rockwool.

### Tier 2 — UK domestic cyclicals

| Ticker | Firm | UK rev % | Segment exposure | Indirect | Read-through | Continuity | Verdict |
|---|---|---|---|---|---|---|---|
| NXT.L | Next | | | | | | pending |
| GRG.L | Greggs | | | | | | pending |
| WTB.L | Whitbread | | | | | | pending |
| JD.L | JD Sports | | | | | | pending |
| RTO.L | Rentokil Initial | | | | | | pending |
| BNZL.L | Bunzl | | | | | | pending |
| HAS.L | Hays | | | **construction staffing — flagged** | | | pending |
| PAGE.L | PageGroup | | | | | | pending |

Hays fails Q3 on its face: construction-and-property staffing revenue moves
with UK construction volumes, which is the channel a housebuilding policy
shock travels down. Expect to exclude.

### Tier 3 — UK financials

| Ticker | Firm | UK rev % | Segment exposure | Indirect | Read-through | Continuity | Verdict |
|---|---|---|---|---|---|---|---|
| AV.L | Aviva | | | | | | pending |
| PRU.L | Prudential | | | | | | pending |
| SDR.L | Schroders | | | | | | pending |
| STJ.L | St James's Place | | | | | | pending |

These carry UK rate exposure without a policy channel, which is what the
housebuilders need spanned. Legal & General is deliberately absent from the
uploaded pool because of its modular-housing and retrofit-adjacent ventures —
a good call, and the kind of judgement this document exists to record.

---

## Open questions

**Segro.** `docs/data_inventory.md` §7 lists it "as a control", which makes it
a donor, but it is absent from both `donors:` and `excluded:` in the uploaded
config. It sits in `control_candidates:` with `ticker: null` pending a
decision. The interference screen is not obvious either way: logistics assets
face MEES for commercial property, a related but distinct policy channel.

**Delisted names.** `notes.survivorship` requires recording which UK mid-caps
were acquired or delisted during the sample and are therefore absent from a
yfinance-built pool. Not yet compiled. This list is needed for the report's
limitations section and cannot be produced from yfinance itself.

**Liquidity screen.** `meta.min_avg_daily_volume_gbp` is 1,000,000. The screen
compares turnover across listings using the coarse static rates in
`meta.fx_screen_rates_to_gbp`. Those rates never touch a return series — see
`notes.fx` — and a coarse rate is adequate because the screen selects the pool
and the pool is fixed before estimation. Which names it actually drops is
recorded in each panel's provenance, and belongs here once prices are pulled.
