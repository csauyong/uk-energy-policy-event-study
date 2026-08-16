# Event dictionary — curation guide

`uk_energy_policy_events.csv` is **hand-curated source, not data**. It is the
one file under `data/` that is version controlled (see the note at the top of
`.gitignore`), because no loader can regenerate it and because "which events
were in the study, and when did that change" must be answerable from git
history rather than from memory.

CSV has no comment syntax, so the schema is documented here. The machine-
readable version of this document is
[`src/policy_event_study/events/schema.py`](../../src/policy_event_study/events/schema.py);
where the two disagree, the code wins and this file is the bug.

Validate a work in progress at any time:

```bash
make events-check
```

---

## Required columns

A row missing any of these is **rejected**. Nothing downstream ever sees it.

| Column | Type | Notes |
|---|---|---|
| `date` | `YYYY-MM-DD` | The announcement's **London** date. Redundant with the timestamp on purpose: the validator cross-checks the two and rejects the row if they disagree, because there is no way to tell which one is wrong. |
| `announcement_timestamp_utc` | ISO-8601 **with offset** | When it became public. `2023-09-20T15:30:00+00:00` or `...Z`. A timezone-naive value is rejected — read as UTC when it was really London, it silently shifts the event day under BST. |
| `policy` | free text | One line. Used to generate `event_id` when that is blank. |
| `source_url` | http(s) URL | Must point at the announcement, not at the publisher's home page (a bare domain is a warning). Without it the row cannot be audited. |
| `anticipation_risk` | `low` / `medium` / `high` | See below — this is an identification property, not a nuisance flag. |
| `expected_direction` | `positive` / `negative` / `ambiguous` | Recorded **before** looking at returns. This is what makes a one-sided reading legitimate. `ambiguous` is an honest and common answer. |
| `affected_sectors` | `;`-separated keys | Must match `treated:` group keys in `config/universe.yaml`. Validated against the config when it is loaded, so a typo fails loudly instead of silently selecting an empty treated set. |

## Optional columns

Every one of these sharpens the identification argument. None is required,
because a schema demanding more than a curator can honestly supply gets filled
in with guesses.

| Column | Type | Notes |
|---|---|---|
| `event_id` | slug | Auto-generated from date + policy when blank. Supply one if you want a stable handle in the report. Must be unique. |
| `time_known` | bool | Set `false` where the publication time could not be recovered. When omitted, a `00:00:00Z` timestamp is *inferred* to mean "time unknown" and a warning is recorded. |
| `scheduled` | bool | Scheduled (Budget, planned consultation response) vs unscheduled. Scheduled events have a partly-anticipated component almost by construction. |
| `confounders` | `;`-separated | What else happened that day. **Any non-empty value routes the event out of the headline pool.** Budget day, MPC day, CPI print, general election period. |
| `event_tags` | `;`-separated | Free tags consumed by the universe config's conditional exclusions — e.g. tagging an event `eu_efficiency_mandate` drops `VNA.DE` and `NXI.PA` from its donor pool, as `config/universe.yaml` requires. |
| `leak_note` | free text | If the announcement was trailed or leaked beforehand, say where and when. **The effective event date is the leak, not the podium** (`CLAUDE.md` §2.5). |
| `notes` | free text | Anything else the report should carry. |

---

## `anticipation_risk` — how to set it, and what it costs you

This is the field most likely to be set carelessly, and it changes what the
result *means*, not just how it is labelled.

- **`low`** — genuinely unscheduled, no press trailing found, no consultation
  or leak in the preceding weeks. The announcement-date return is a clean read
  on the news.
- **`medium`** — scheduled but with uncertain content (a consultation response
  whose direction was not pre-briefed), or unscheduled but widely speculated.
- **`high`** — the market already knew. Pre-briefed to the press, trailed in a
  prior speech, or the near-certain conclusion of a consultation.

**A `high` row cannot produce an informative null.** If the news was already
priced, there is no announcement-date effect to find, and a zero estimate is
consistent both with "the policy did not matter" and with "the policy mattered
and was priced a fortnight earlier". The two are not distinguishable from the
event-date return, and no amount of estimator sophistication separates them.

The pipeline therefore treats `high` rows as a separate stratum: they are
estimated, reported with their placebo distributions like everything else, and
excluded from any pooled headline. The report carries a standing section on
what their identification failure implies. Setting this field to `low` because
a `high` is inconvenient is the single easiest way to make this project
dishonest.

The validator warns when `anticipation_risk` is `high` and both `leak_note`
and `notes` are blank — the report is required to discuss identification for
these events and cannot do so from the flag alone.

---

## Worked example rows

Not committed to the CSV (which ships header-only, for you to curate). These
illustrate the three timing cases the resolver distinguishes.

```
2023-09-20,2023-09-20T19:00:00+00:00,"PM speech rowing back 2035 boiler phase-out and landlord EPC mandate",https://www.gov.uk/government/speeches/pm-speech-on-net-zero-20-september-2023,high,negative,insulation_and_heating;residential_landlords,,true,false,,uk_domestic_policy,"Trailed by BBC on 19 Sep; the effective event date is arguably the leak","20:00 London — after the LSE close, so the 20 Sep close-to-close return is fully pre-announcement and t0 is 21 Sep"
2021-10-19,2021-10-19T07:30:00+00:00,"Heat and Buildings Strategy published, Boiler Upgrade Scheme confirmed",https://www.gov.uk/government/publications/heat-and-buildings-strategy,medium,positive,insulation_and_heating,,true,true,,,"","07:30 London — before the open, so the 19 Oct return is fully post-announcement and t0 is 19 Oct"
2020-07-08,2020-07-08T00:00:00+00:00,"Green Homes Grant announced at Summer Economic Update",https://www.gov.uk/government/speeches/summer-economic-update-speech,high,positive,insulation_and_heating;housebuilders,,false,true,summer_economic_update;fiscal_statement,,"Pre-briefed over the preceding weekend","Time not recovered — midnight placeholder, time_known=false. Confounded by the fiscal statement: NOT poolable"
```

Read the third row carefully. It is a *good* event on paper — large,
directional, clearly exposed names — and it is unusable for a headline
estimate: the time is unknown, it was pre-briefed, and it landed inside a
fiscal statement that moved every UK domestic cyclical for unrelated reasons.
`docs/research_plan.md` Phase B0 warns that this is the normal case for UK
energy policy, and the kill criterion exists because of it.
