# Event curation protocol

Both the working procedure and the methods section for the write-up — a reader
needs to know the event list was built by a rule, not by taste.

**Machine-readable counterparts.** Step 6 grouping is implemented in
`src/policy_event_study/events/grouping.py` and enforced in the estimator.
Steps 1–3 are executed by `scripts/sweep_govuk.py` (`make sweep`), which takes
first-publication timestamps from the gov.uk **content** API, not the search
API. That distinction is not cosmetic: the search API's `public_timestamp` is
the *last updated* stamp. For the MEES landlord guidance it reads 2026-05-05
against a true first publication of 2017-10-01 — an 8.5-year error that would
silently redate the event.

---

## Rule 0 — curate blind

**Do not look at any price series while curating.** Not the treated names, not
the index, not "did anything happen that day". Selecting events after seeing
reactions is selection on the dependent variable, and it invalidates the whole
design no matter how clean the rest of the pipeline is.

Build the list. Freeze it. Commit it with a tag. *Then* run the estimator.

The corollary: **keep events you expect to find nothing for.** A list of only
the ones that "should have moved something" is the same bias wearing a
different hat. Events with genuine exposure and no expected reaction are what
make a positive β credible.

---

## Step 1 — sweep for candidates

Work from primary publishers, in this order. Never take a date from news
coverage.

| Source | What it gives |
|---|---|
| gov.uk publications and press releases (DESNZ, MHCLG, HMT) | The announcement itself, with a publication timestamp |
| Hansard | Oral and written ministerial statements, timestamped by sitting |
| Written Ministerial Statements index | Policy changes that never get a press release |
| legislation.gov.uk | The date instruments were laid |
| HMT Budget and Spending Review documents | Fiscal-event measures |
| UK ETS Authority announcements | Carbon-price-channel events |

Sweep categories, not headlines: minimum energy efficiency standards for
rented property; building regulations and the Future Homes Standard; EPC and
assessment methodology; retrofit and heating grant schemes; boiler and heat
pump policy; ETS scope and allocation.

Target 15–20 candidates before filtering.

## Step 2 — set the event date to first public disclosure

This is where most event studies quietly break.

The event date is **when the information first became public**, not when it was
formally announced. Major UK policy is routinely briefed to journalists the
evening before. If the substance appeared in a Friday-evening broadcast and the
statement came Monday, your event is Friday.

Procedure for each candidate:

1. Record the formal announcement timestamp from the primary source.
2. Search the preceding 10 calendar days for reporting of the *substance*.
3. If the substance appeared earlier, set `announcement_timestamp_utc` to the
   earliest credible public disclosure and record both timestamps.
4. If disclosure was gradual, the event is unusable. Drop it and say why.

## Step 3 — resolve the timestamp against trading hours

The existing LSE open/close logic handles this, but you must supply a real
time, not a date.

- Embargoed press releases commonly go out at 00:01 — overnight, so the whole
  of day 0 is clean.
- Fiscal statements begin around 12:30 — intraday, so day 0 straddles and the
  [0,1] window is the honest one.
- Documents laid before Parliament appear during the sitting day.

Record the time even when it is awkward. A missing timestamp is a rejected row.

## Step 4 — score the surprise, and be specific about what was surprising

For mature policy, the existence is almost always priced. **The surprise lives
in the parameters.**

Fill `surprise_note` with the specific unanticipated element, not a summary.
Good: *"Existence widely trailed; cost cap set at £10k against £15k proposed,
and the compliance date landed at 2030."* Bad: *"Government announced new
landlord rules."*

Set `anticipation_risk` by a rule, not a feeling:

- **low** — no pre-announced date, no substantive reporting in the prior 10
  days, outcome not derivable from an existing consultation.
- **medium** — date known or trailed, but a material parameter was open.
- **high** — date and substance both trailed; only confirmation occurred.

Keep the high ones in the file — they are your natural placebo group. A design
that finds β on low-anticipation events and nothing on high-anticipation ones
is far more convincing than one that finds β everywhere.

## Step 5 — fill the structured fields

- `direction` — `tighten` or `loosen`. Aim for a real mix: the sign-consistency
  falsification test needs both sides, and each side needs enough events to
  reach significance on its own. Three tightenings and one loosening gives you
  a test that reports `UNDERPOWERED` and tells you nothing.
- `channel_targets` — which exposure channels the policy touches. If a policy
  touches no channel in the exposure construction, either extend the
  construction or drop the event; do not fudge it.
- `overlap_ack` — see below.

## Step 6 — handle clustering by grouping, not acknowledgement

Events closer than the spacing threshold share return days. That is mechanical
dependence, not a soft correlation, so treat them as **one event group**: take
the transitive closure over the spacing threshold, cluster on the group, and
compute the bootstrap floor from the number of groups.

Practically:

- Prefer candidates 14+ days apart.
- A fiscal event and its accompanying policy documents are **one** event, not
  three.
- When you acknowledge an overlap, you are declaring a grouping, not waiving a
  check.

## Step 7 — watch the curve, and know when to stop

Run `make event-report` after each batch. Add events while the MDE keeps
falling materially. Stop when:

- the marginal event stops moving the MDE, **or**
- the next-best candidate is `anticipation_risk: high` or a forced grouping.

A smaller list of clean, well-spaced, well-timestamped events beats a longer
list padded with confirmations. Once you stop, tag the commit — that tag is
your pre-registration.

---

## Worked example

> **Candidate:** Future Homes Standard, published 24 March 2026.
>
> - **Primary source:** regulations laid before Parliament, gov.uk publication
>   page — take the publication time from the page, not from coverage.
> - **Leak check:** the existence and broad content had been trailed for years;
>   search the prior 10 days for reporting of the *lead time* specifically.
> - **Surprise:** not the standard itself. The implementation lead time — 12
>   months, against a rumoured 6 — is the unanticipated parameter, and it is
>   what a housebuilder's cash flow actually turns on.
> - `anticipation_risk`: **high** on existence, and that is how it should be
>   coded. It earns its place as a confirmation-type event against which the
>   low-anticipation ones are contrasted.
> - `direction`: `tighten`.
> - `channel_targets`: housebuilder build standard; insulation and materials;
>   heating systems; solar.
> - **Grouping:** check whether any related instrument or announcement fell
>   within 14 days. If so, group.
