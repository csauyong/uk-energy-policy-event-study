# UK energy-policy event study

**Do UK energy-efficiency and heating policy announcements move the share
prices of the companies they affect — and can we measure it honestly?**

That is the whole question. This repository is the machinery for answering it
without fooling ourselves, which turns out to be most of the work.

## The answer, as of 2026-08-18

**Not yet — and the interesting part is why not.**

The regression runs end to end. It returns β = −0.0092% per standard deviation
of exposure, p = 0.94, across 682 firm-event observations and 17 clusters,
against a minimum detectable effect of 0.31%. That reads like a clean,
well-powered null.

**It isn't one.** Of those 682 rows, **seven** carry a non-zero exposure score,
and two firms account for all seven. A Frisch-Waugh decomposition puts 97% of
the weight on β on ten rows, and the effective count of identifying
observations at **6.5**. Drop one firm and β moves by a factor of 22; drop two
and it ceases to exist at all.

So the honest finding is not *"policy announcements don't move exposed
prices"*. It is:

> The dose-response estimand is not identified on the exposure data curated so
> far. The binding constraint is exposure curation — specifically, missing
> back-vintages for firms already curated — and it is neither statistical
> power nor the event dictionary.

The full audit is in **[`reports/results.md`](reports/results.md)**, including
what would fix it and in what order. The project's own diagnostics are what
caught this. Without them the number would have been published as a null, and
the null would have been wrong.

---

## The idea in one page

When the government announces something like "landlords must bring rented
homes up to EPC band C", some listed companies are affected and most are not.
Insulation manufacturers might gain. Residential landlords face a bill. A
supermarket chain is unaffected.

So the test is: **on the day of an announcement, did share prices move in
proportion to how exposed each company was?**

That framing matters, and it is the second design this project used. The first
one asked "did the affected companies move?" and compared them to a synthetic
control built from unaffected firms. We measured how large an effect that
design could detect before running it, and the answer was **12–24% share price
movement** — far larger than any real policy announcement produces. The design
could not have found what it was looking for, so we changed it rather than
running it and reporting a null.

The current design compares *hundreds* of companies on the same day, using
each one's exposure as the explanatory variable. Companies with zero exposure
are not discarded — they are what tells us how the market moved that day for
reasons unrelated to the policy. That change brought the detectable effect
down to roughly **0.3%**, which is inside the range a real announcement plausibly
produces.

---

## Why so much of this repo is about dates

An event study lives or dies on knowing exactly when information became
public. A day's error can put the entire market reaction *outside* the
window you are measuring, which makes a real effect look like nothing.

Three concrete examples from this project:

- **The gov.uk search API reports the wrong date.** It returns when a page was
  last *updated*, not when it was first published. For one guidance page that
  is a difference of **8.5 years**. We read publication dates from a different
  endpoint that records the original.
- **A policy was announced in a Budget on 26 November 2025 but takes effect in
  March 2026.** Automated tools kept dating it to March, because that is the
  date the sentence mentions. Five months wrong.
- **The September 2023 net-zero rollback leaked to the BBC the evening
  before.** The formal speech was the 20th; the information was public on the
  19th, and the speech was brought forward *because* of the leak. Using the
  20th would place the whole reaction in the "before" window.

---

## The pipeline

Each step has a `make` target. Everything is reproducible from source plus a
date — no data is committed except hand-curated work that no program could
regenerate.

```
  1. DISCOVER      make chronology            find candidate announcements
  2. AUDIT         make audit                 check nothing obvious is missing
  3. SHORTLIST     make shortlist             filter by rule to a short list
  4. FINALISE      make finalise              hand curation, verify dates
  5. PROMOTE       make promote               write the frozen event dictionary
  6. INSPECT       make event-report          timing, grouping, statistical power
  7. PRICES        make prices                download share price history
  8. UNIVERSE      make screening-universe    build the zero-exposure cross-section
  9. ESTIMATE      make estimate              stack CARs, fit the dose-response
 10. DIAGNOSE      make diagnostics           leverage, drop path, identification
```

### 1. Discovery — how we find announcements

The obvious approach is to search gov.uk for "energy efficiency" and see what
comes back. **We tried that and it failed in a way that would have been
invisible.** Search ranks results, and big cross-cutting announcements are
written in general language ("net zero") while small scheme tweaks are written
in technical language ("minimum energy efficiency standard"). So the search
found the small stuff and missed the biggest event in the study entirely.

Worse, you cannot audit a search: there is no way to list what it *didn't*
return.

So discovery was inverted. We start from a declared grid — **14 policy areas ×
10 stages of a policy's life** (consulted on, launched, amended, closed…) — and
answer each cell from published policy timelines: House of Commons Library
research briefings and gov.uk collection pages. An unanswered cell is a
visible gap that a reader can check. That is auditable in a way search recall
is not.

### 2–5. From candidates to a frozen list

Candidates are filtered by rules written *before* looking at results, then
hand-checked. Two hard rules:

- **Curate blind.** Nobody looks at a single share price until the event list
  is finished and tagged in git. Picking events after seeing which ones moved
  the market is the most damaging mistake available here.
- **Keep events you expect to find nothing for.** A list of only the ones that
  "should have moved something" is the same bias in a different coat.

The list was then scored against an independently hand-written inventory of 49
policy instruments. The automated pipeline had found something for 76% of them
but dated only **35%** correctly — which is how we learned that dating, not
finding, was the real weakness.

### 6. Grouping and power

Two announcements a fortnight apart are not two independent observations —
they share trading days. They are collapsed into one **group**, and all the
statistics are computed from the number of groups, not the number of events.
Currently **24 events → 21 groups** at the 14-day default spacing.

(An earlier draft of this README and of `CLAUDE.md` said 18 groups. That figure
was stale — recomputing it from the frozen dictionary gives 21. Corrected
2026-08-18 and recorded in `reports/decision_log.md`.)

### 7. Prices

Daily share prices from Yahoo Finance, with three protections:

- **Corporate actions applied forwards only.** A share split in 2025 must not
  change what a 2020 return looks like.
- **Merged companies are split into two units.** Yahoo serves Barratt
  Developments' entire pre-merger history under the post-merger symbol, so a
  naive download silently changes company halfway through.
- **Overseas exchanges are aligned to the London close.** US markets close 4½
  hours after London, so a US company's "same day" price contains information
  a UK company's does not.

---

## What is honest about this project

The interesting parts are the things that were *stopped*, not the things that
were built:

- The first design was abandoned on a power calculation before any data was
  pulled.
- One event was **deleted** by a rule written before the evidence was looked
  at — the disclosure had dribbled out over four separate dates, which makes
  it unusable.
- Several arithmetic bugs were caught in code that decides whether the design
  works, including one that reported a metric as −82% and one that made a
  deleted event look harmless.
- Where leak-checking could not be done properly (news sites blocked the
  tooling), the limitation is stated **with its direction**: it biases results
  toward *underestimating* effects, so any measured effect is a lower bound.

A caveat with a known direction is a bound. A caveat without one is a hole.

---

## Getting started

```bash
make setup          # create the environment
make check          # lint, type-check, tests, data hygiene
make event-report   # see the current event list and its statistical power
```

Read next:

| Document | What it covers |
|---|---|
| [`reports/results.md`](reports/results.md) | **The result, and the audit showing why it is not yet informative** |
| [`CLAUDE.md`](CLAUDE.md) | Current status, what works, what doesn't, next steps |
| [`docs/event_curation_protocol.md`](docs/event_curation_protocol.md) | How events are chosen, and the rules that stop us cheating |
| [`docs/exposure_construction.md`](docs/exposure_construction.md) | How company exposure is scored |
| [`reports/decision_log.md`](reports/decision_log.md) | Every decision, including the abandoned ones |
| [`reports/dose_response.md`](reports/dose_response.md) | The current design and its statistical power |

The governing standards for this work live in
[`../CLAUDE.md`](../CLAUDE.md) — point-in-time discipline, named baselines,
and the rule that negative results get written up rather than buried.
