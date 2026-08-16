# A-priori policy inventory — vintage 2026-08-16

**Written by hand, from the policy record, before consulting the generated
shortlist.** That order matters: the point of this file is to be an independent
list the sweep can be scored *against*. If it were assembled by reading
`shortlist_final_2026-08-16.md` and filling gaps, it would inherit the sweep's
blind spots and could not measure them.

49 instruments, 2013-01 to 2026-08. Each row carries a **date grade**:

| Grade | Meaning |
|---|---|
| `A` | Exact day established from a primary or near-primary source (gov.uk publication, WMS, legislation.gov.uk, HMT fiscal document). Usable. |
| `B` | Day is near-certain but rests on secondary reporting of a primary act. Confirm through `events.govuk.first_publication` before use. |
| `C` | Month known, day not. Not usable until resolved. |

`sched` marks instruments whose date was announced long in advance — a
commencement, not news. **Keep them.** Per Rule 0 of the curation protocol, a
list containing only events that should have moved something is selection on
the dependent variable wearing a different hat; scheduled commencements with
genuine exposure and no expected reaction are what make a positive β credible.

---

## 1. The inventory

### 2013–2015

| # | Date | Grade | Instrument | Dir | Channels | Notes |
|---|---|---|---|---|---|---|
| 1 | 2013-01-28 | B | Green Deal opens to consumers; ECO1 live | tighten | product_revenue | Sample floor. `sched` |
| 2 | **2013-12-02** | B | Green levies package: ECO1 scaled back and extended to 2017, ~£50 off bills | **loosen** | product_revenue | Package announced 2 Dec, restated at Autumn Statement **5 Dec 2013**. Two candidate t0s; heavily trailed through Nov. See §4. |
| 3 | 2015-03-26 | C | Energy Efficiency (Private Rented Property) (E&W) Regs 2015 made | tighten | residential_stock | MEES band E from 2018. Needs the laying date off legislation.gov.uk. |
| 4 | **2015-07-10** | A | *Fixing the Foundations*: zero-carbon homes and allowable solutions dropped; 2016 on-site efficiency uplift abandoned | **loosen** | delivered_stock | HMT productivity plan, two days after the Summer Budget. **Resolves the shortlist's `zero-carbon-homes-cancelled`, which was flagged "2015 only".** |
| 5 | **2015-07-23** | A | Green Deal Finance Company funding ended; GDHIF closed to new applications | **loosen** | product_revenue | DECC, Amber Rudd. Announced same day it took effect. Absent from the sweep entirely. |

### 2016–2019

| # | Date | Grade | Instrument | Dir | Channels | Notes |
|---|---|---|---|---|---|---|
| 6 | 2017-10-01 | A | MEES landlord guidance first published | tighten | residential_stock | The known API trap: search API reports 2026-05-05. Weak as an event — guidance, not a decision. |
| 7 | 2018-04-01 | A | MEES band E in force, new tenancies | tighten | residential_stock | `sched`. Keep as a null-expectation row. |
| 8 | 2018-11-?? | C | Energy Efficiency (PRP) (Amendment) Regs 2018 laid — £3,500 landlord cap replaces "no cost to landlord" | tighten | residential_stock | In force 2019-04-01. The first time MEES imposed real landlord capex. Needs the laying date. |
| 9 | 2018-12-03 | C | ECO3 begins | tighten | product_revenue | `sched`. Order made Nov 2018 — the Order date is the event, not the start. |
| 10 | **2019-10-01 12:00** | A | Future Homes Standard 2019 consultation opens (Part L / Part F) | tighten | delivered_stock | **Time known: midday.** Intraday t0. |

### 2020–2021

| # | Date | Grade | Instrument | Dir | Channels | Notes |
|---|---|---|---|---|---|---|
| 11 | **2020-07-08 ~12:30** | A | Summer Economic Update: Green Homes Grant announced, £2bn | tighten | product_revenue | Fiscal statement — intraday, [0,1] is the honest window. |
| 12 | 2020-08-?? | C | GHG Local Authority Delivery, £500m, launched | tighten | product_revenue | Sweep has "August 2020". Day unresolved. |
| 13 | 2020-09-30 | B | GHG voucher scheme opens for applications | tighten | product_revenue | `sched`. |
| 14 | **2020-11-18** | A | Ten Point Plan for a Green Industrial Revolution | tighten | product_revenue, delivered_stock | Embargoed release — overnight, so day 0 is clean. Trailed for a week; see §4. |
| 15 | 2020-11-25 | B | Spending Review 2020: GHG extended to March 2022 | tighten | product_revenue | Fiscal, intraday. |
| 16 | **2021-01-19** | B | Government response to FHS 2019 consultation; Part L 2021 interim uplift confirmed | tighten | delivered_stock | Sweep has "January 2021". |
| 17 | **2021-03-27 17:00** | A | GHG voucher scheme closed to new applications | **loosen** | product_revenue | **Announced 17:00 on a Saturday.** t0 is Monday 2021-03-29 open — the whole reaction is in one clean session. One of the best-shaped events in the sample. **Absent from the sweep.** |
| 18 | **2021-07-20 10:00** | A | ECO4 consultation opens | tighten | product_revenue | **Time known: 10am.** |
| 19 | 2021-08-?? | C | Social Housing Decarbonisation Fund Wave 1, £179m | tighten | product_revenue | |
| 20 | **2021-10-19** | A | Heat and Buildings Strategy; Boiler Upgrade Scheme announced (£450m, £5,000 grants); 2035 gas boiler ambition | tighten | product_revenue | Trailed for weeks — high leak risk. |
| 21 | **2021-12-15** | A | Part L 2021 Approved Documents published — 31% uplift, in force 2022-06-15 | tighten | delivered_stock | The largest single regulatory cost step on housebuilders in the sample. |

### 2022–2023

| # | Date | Grade | Instrument | Dir | Channels | Notes |
|---|---|---|---|---|---|---|
| 22 | **2022-03-23 ~12:30** | A | Spring Statement: VAT zero-rated on energy saving materials for 5 years | tighten | product_revenue | Direct price cut on insulation and heat pumps. **Absent from the sweep.** |
| 23 | 2022-04-01 | A | ECO4 measures start | tighten | product_revenue | `sched`. |
| 24 | **2022-04-07** | A | British Energy Security Strategy: ECO4 confirmed, 600k heat pumps/yr by 2028 | tighten | product_revenue | |
| 25 | 2022-05-23 | A | Boiler Upgrade Scheme opens | tighten | product_revenue | `sched`. |
| 26 | 2022-06-15 | A | Part L 2021 in force | tighten | delivered_stock | `sched`. |
| 27 | **2022-11-17 ~12:30** | A | Autumn Statement 2022: ECO+ announced (£1bn); 2030 demand-reduction target | tighten | product_revenue | **Absent from the sweep** — the sweep picked up GBIS only from its April 2023 launch. |
| 28 | **2022-11-28** | A | ECO+ consultation opens (closes 2022-12-23) | tighten | product_revenue | |
| 29 | 2023-03-?? | C | ECO+ renamed Great British Insulation Scheme; design confirmed | tighten | product_revenue | Sweep has GBIS at "April 2023" — that is the *launch*, not the decision. |
| 30 | 2023-03-22 | B | SHDF Wave 2.1 awards announced, £778m | tighten | product_revenue | |
| 31 | 2023-07-1? | C | Whitby hydrogen village trial cancelled | loosen | product_revenue | Narrow channel — hydrogen-ready boiler makers only. |
| 32 | **2023-09-19 evening** | **A** | **Net zero package: PRS EPC C requirement scrapped; off-grid boiler phase-out moved 2026→2035; exemptions; BUS raised to £7,500** | **loosen** | residential_stock, product_revenue | **See §3. One event, not four. t0 is the 19th, not the 20th.** |
| 33 | 2023-10-23 | A | BUS grant uplift to £7,500 takes effect | tighten | product_revenue | `sched` consequence of #32. Not an independent event. |
| 34 | **2023-12-13** | A | Future Homes and Buildings Standards 2023 consultation launched | tighten | delivered_stock | **WMS HCWS119** — laid during the sitting day, so intraday. |
| 35 | 2023-12-14 | B | Redcar hydrogen village not proceeding | loosen | product_revenue | Ends the hydrogen-heating option entirely. |

### 2024–2025

| # | Date | Grade | Instrument | Dir | Channels | Notes |
|---|---|---|---|---|---|---|
| 36 | **2024-03-14** | A | Clean Heat Market Mechanism delayed to April 2025 | **loosen** | product_revenue | **WMS HCWS341.** Resolves the shortlist's `mar2024-chmm-delayed`, which had month only. The boiler manufacturers' obligation — the cleanest single-name shock to that channel in the sample. |
| 37 | **2024-10-30 ~12:30** | A | Autumn Budget 2024: £3.4bn Warm Homes Plan; £1.29bn Warm Homes Social Housing Fund | tighten | product_revenue | **Absent from the sweep.** |
| 38 | **2024-12-04** | A | Reforms to the Energy Performance of Buildings regime — consultation launched | tighten | residential_stock | Sweep has this as "December 2024". |
| 39 | **2025-02-07** | A | *Improving the energy performance of privately rented homes: 2025 update* — EPC C by 2030 proposed | **tighten** | residential_stock | **The mirror image of #32: the reinstatement of the requirement Sunak scrapped.** Same channel, opposite sign, 17 months apart. **Absent from the sweep.** The single most valuable pairing in the study. |
| 40 | 2025-03-?? | C | Warm Homes: Social Housing Fund Wave 3 awards announced | tighten | product_revenue | |
| 41 | 2025-03-31 | A | Home Upgrade Grant ends | loosen | product_revenue | `sched`. |
| 42 | **2025-06-11 ~12:30** | A | Spending Review 2025: £13.2bn Warm Homes Plan confirmed to 2029-30 | tighten | product_revenue | **Absent from the sweep.** Was in genuine doubt beforehand — real surprise content. |
| 43 | **2025-07-02** | A | Reformed Decent Homes Standard consultation **and** social rented MEES (EPC C by 2030) consultation, published together | tighten | residential_stock | Two instruments, one day — must be one event row. **Absent from the sweep.** |
| 44 | **2025-11-26 ~12:30** | **A** | **Budget 2025: ECO abolished from 2026-03-31; £2.3bn of levies moved to the Exchequer; ~£150 off bills** | **loosen** | product_revenue | **See §3. The sweep dates this "March 2026" — a five-month error on the largest demand shock to insulation installers in the sample.** |

### 2026

| # | Date | Grade | Instrument | Dir | Channels | Notes |
|---|---|---|---|---|---|---|
| 45 | **2026-01-21** | A | **Warm Homes Plan published (£15bn)** + PRS MEES government response (EPC C by 2030-10-01, £10k cap) + EPC regime partial response | tighten | residential_stock, product_revenue | Three documents, one day. One event row. Landlord obligation made real with a date and a cost cap. |
| 46 | **2026-01-28** | A | Social rented sector MEES response: EPC C or equivalent by 2030-04-01 | tighten | residential_stock | Hits registered providers and their contractors, not the listed landlords. Check exposure actually loads on any name before keeping. |
| 47 | **2026-03-24** | **A** | **Future Homes Standard published — implementation delayed to 2028**; 75% emissions cut, solar mandate ≥40% of floor area, heat pumps; in force 2027-03-24 with 12-month transition | **mixed** | delivered_stock (loosen), product_revenue (tighten) | **Opposite-signed across two channels under one shock** — the most informative shape available. Also dates the HEM delay: `hem-delayed-2026` ("early 2026") is a consequence of this, not a separate event. |
| 48 | 2026-03-31 | A | ECO4 and GBIS end | loosen | product_revenue | `sched` consequence of #44. **Not an independent event** — the sweep's rows 23 and 24 both belong here and must be folded into 2025-11-26. |
| 49 | 2026-04-01 | A | £150 bill cut takes effect | — | — | `sched` consequence of #44. Not an event. |

---

## 2. Diff against `shortlist_final_2026-08-16.md`

### 2.1 In the hand list, missing from the sweep — 10 rows

These are the sweep's false negatives, and the pattern in them is the finding.

| Hand row | Instrument | Why the sweep missed it |
|---|---|---|
| 5 | Green Deal funding ended, 2015-07-23 | Pre-dates the Commons Library chronologies' detailed coverage |
| 17 | GHG voucher scheme closed, 2021-03-27 | Closure announced on a Saturday by press notice, never got its own gov.uk publication page |
| 22 | VAT zero-rate on ESMs, 2022-03-23 | Fiscal measure — lives in an HMT document, not a DESNZ one |
| 27 | ECO+ announced, 2022-11-17 | Same: fiscal event |
| 31, 35 | Hydrogen village cancellations | Cancellations, no document of their own |
| 37 | Autumn Budget 2024, £3.4bn | Fiscal event |
| 39 | **PRS EPC C reinstated, 2025-02-07** | Consultation, not a decision — no instrument noun in the chronology sentence |
| 42 | Spending Review 2025, £13.2bn | Fiscal event |
| 43 | DHS + social MEES consultations, 2025-07-02 | Consultation |

Row 44 (ECO abolished, 2025-11-26) is not counted here — the sweep *has* it, but
dated to its effect month. It appears in §2.3 instead, and it is the more
damaging of the two error types.

**Two failure modes, both systematic.**

1. **Fiscal events.** Four of ten, five counting row 44. Every energy-efficiency measure that arrived
   through a Budget, Spending Review or Autumn Statement was missed, because the
   sweep indexes DESNZ and MHCLG publication pages and these live in HMT
   documents. The `fiscal_events` family has 154 corpus mentions and 32 dated
   references in the completeness audit, so the corpus knows about them — the
   *sweep* does not reach them. This is a source-coverage gap, not an extractor
   gap, and no amount of extractor tuning fixes it.
2. **Announcement-date vs effect-date collapse.** Rows 44 and 48 are the same
   decision. Chronologies write *"funding stops after March 2026"* because that
   is what matters to a policy reader; an event study needs 26 November 2025.
   Any sweep that takes its date from the sentence rather than from the
   publication will make this error on every scheme closure.

Both failure modes bite hardest on `loosen` events, which was already the thin
side. The direction balance in `shortlist_final` (9 tighten / 14 loosen) is
therefore not the reassurance it appears to be — it was reached by hand-adding
seven deferrals, and the hand list finds ten more misses plus one mis-dating,
of which five are `loosen` or mixed.

### 2.2 In the sweep, not in the hand list — 6 rows to interrogate

Not necessarily wrong; each needs one primary-source check before it is kept.

| Sweep # | Month | Family | Status |
|---|---|---|---|
| 5 | March 2015 | `eco` | Evidence sentence is forward-looking policy prose, not an announcement. **Likely strike.** |
| 7 | September 2018 | `eco` | ECO3's *start*, described from a scheme-duration sentence. The event is the Order date, ~Nov 2018 (hand row 9). **Redate.** |
| 13 | March 2021 | `mees_nondomestic` | Non-domestic MEES closure — real, but check it loads on any name in the universe. |
| 15 | December 2021 | `heat_buildings_strategy` | Evidence is a bullet summarising the Heat and Buildings Strategy (Oct 2021). Probably a duplicate of hand row 20. **Likely strike.** |
| 16 | March 2023 | `heat_buildings_strategy` | Evidence is *"last updated March 2023"* — a gov.uk page-update stamp, exactly the trap the protocol warns about. **Strike.** |
| 21 | January 2026 | `boiler_upgrade` | BUS expansion — same day as hand row 45. **Merge, not a separate event.** |

### 2.3 Rows the sweep dates wrongly

| Sweep # | Sweep date | Correct date | Cost of the error |
|---|---|---|---|
| 1–4 | September 2023 | **2023-09-19 evening** | Four rows for one event; and t0 is the leak, not the podium |
| 6 | "2015", unresolved | **2015-07-10** | Was flagged unusable; now usable |
| 18 | March 2024 | **2024-03-14** | Month → day |
| 22 | January 2026 | consequence of **2026-03-24** | Not an independent event |
| 23, 24 | March 2026 | **2025-11-26** | Five months; effect date mistaken for announcement date |

---

## 3. The two events that carry the study

**2023-09-19 — the net zero rollback.** Rows 1–4 of the sweep are one
announcement. It scrapped the landlord EPC C requirement, moved the off-grid
boiler phase-out from 2026 to 2035, exempted some homes outright, and raised
the BUS grant 50% to £7,500. Landlords and insulation manufacturers take
opposite signs under it, which is the most informative shape an event can have
in a dose-response design.

**The date is the 19th, not the 20th.** The substance leaked on the evening of
Tuesday 19 September and the leak is *why* the speech happened when it did —
it was brought forward from later that week. So the information was public
before the 20th opened. Set `announcement_timestamp_utc` to the evening of the
19th, record the formal timestamp separately, and treat 20 September as the
first full trading session. Getting this wrong does not add noise; it puts the
entire reaction in the pre-window and biases the estimate toward zero.

**2025-11-26 — the Budget that abolished ECO.** ECO ran for thirteen years and
was the demand floor under the UK retrofit installer market. Ending it is the
largest single demand shock to `product_revenue` in the sample, and it is
currently in the shortlist as two separate rows both dated March 2026. Fixing
this is worth more than any further extractor work.

Both are heavily-trailed events, and both need the §4 treatment.

---

## 4. Leak risk — the rows that need a 10-day back-search

Per Step 2 of the curation protocol. Ranked by how likely the substance was
public before the formal announcement:

| Row | Instrument | Risk |
|---|---|---|
| 32 | Net zero rollback | **Confirmed leaked.** t0 already moved. |
| 44 | Budget 2025 | **High.** Budget measures are routinely pre-briefed; the £150 figure circulated beforehand. If disclosure was gradual, the row is unusable — drop it and say why rather than picking a date. |
| 2 | Green levies package 2013 | **High.** Trailed through November 2013; two candidate formal dates as well. |
| 20 | Heat and Buildings Strategy | **High.** Trailed for weeks; publication slipped repeatedly. |
| 14 | Ten Point Plan | **Medium.** Trailed ~a week, but embargoed release at 00:01 keeps day 0 clean. |
| 45 | Warm Homes Plan | **Medium.** Long-signalled; the *content* (£15bn, October 2030 date, £10k cap) is the surprise, not the existence. |
| 47 | Future Homes Standard | **Medium.** The delay to 2028 was speculated on; the solar mandate less so. |
| 37, 42 | Fiscal events | **Medium.** Standard pre-Budget briefing. |
| 11, 22, 27 | Fiscal events | **Medium.** Same. |
| 17 | GHG closure | **Low.** Saturday 17:00, no trailing. Cleanest event in the list. |
| 34, 36 | WMS | **Low.** Written statements are rarely pre-briefed. |
| 10, 18, 38, 39, 43 | Consultation launches | **Low.** |

---

## 5. What to do next, and where to stop

1. Resolve the 8 `C` grades against legislation.gov.uk and the gov.uk content
   API. Anything still `C` after one pass is dropped, not guessed.
2. Merge the four September 2023 rows into one, and the two March 2026 rows into
   2025-11-26. Strike sweep rows 5, 15 and 16.
3. Run the §4 leak searches in risk order. Stop at row 44 — if Budget 2025 turns
   out to have been disclosed gradually, it is unusable and that is a finding
   about the event list, not a reason to keep looking.
4. Add a `source_coverage` note to the write-up recording that the sweep does
   not index HMT documents, and that this was found by hand-list diff rather
   than by the completeness audit. The completeness audit could not have found
   it: it audits the corpus against the extractor, and both share the same
   source gap.
5. **Then freeze and tag.** The remaining uncertainty in this list is smaller
   than the uncertainty in any single-day abnormal return. Further curation does
   not improve the estimate.

## 6. Sources

Primary and near-primary, in date order of the instrument they support. News
sources appear only where they establish a leak date, which is the one thing a
primary source cannot give.

- Zero carbon homes (row 4) — [HMT, *Fixing the Foundations*, 10 July 2015](https://commonslibrary.parliament.uk/research-briefings/sn06678/)
- Green Deal funding ended (row 5) — [DECC blog, 23 July 2015](https://decc.blog.gov.uk/2015/07/23/changes-to-green-home-improvement-policies-announced-today); [Green Deal ORB notice](https://gdorb.energysecurity.gov.uk/2015/07/24/important-message-green-deal-finance-company-funding-to-end-thursday-23-july-2015/)
- ECO / green levies 2013 (row 2) — [Commons Library SN06814](https://commonslibrary.parliament.uk/research-briefings/sn06814/)
- MEES amendment £3,500 cap (row 8) — [The Energy Efficiency (Private Rented Property) (Amendment) Regulations 2018, legislation.gov.uk](https://www.legislation.gov.uk/ukdsi/2018/9780111175217)
- FHS 2019 consultation (row 10) — [gov.uk consultation page](https://www.gov.uk/government/consultations/the-future-homes-standard-changes-to-part-l-and-part-f-of-the-building-regulations-for-new-dwellings)
- FHS 2019 response (row 16) — [Government response, assets.publishing.service.gov.uk](https://assets.publishing.service.gov.uk/media/60114c6c8fa8f565494239a7/Government_response_to_Future_Homes_Standard_consultation.pdf)
- Green Homes Grant closure (row 17) — [NAO, *Green Homes Grant Voucher Scheme*](https://www.nao.org.uk/wp-content/uploads/2021/09/Green-Homes-Grant-Voucher-Scheme.pdf); [Commons Library CBP-10797](https://commonslibrary.parliament.uk/research-briefings/CBP-10797/)
- ECO4 consultation (row 18) — [gov.uk consultation page](https://www.gov.uk/government/consultations/design-of-the-energy-company-obligation-eco4-2022-2026); [ECO4 government response, April 2022](https://assets.publishing.service.gov.uk/media/6246c8c4d3bf7f32b65d72ca/eco4-government-response.pdf)
- Ten Point Plan (row 14) — [gov.uk publication page](https://www.gov.uk/government/publications/the-ten-point-plan-for-a-green-industrial-revolution)
- Heat and Buildings Strategy (row 20) — [gov.uk publication page](https://www.gov.uk/government/publications/heat-and-buildings-strategy); [CP 388 as presented to Parliament](https://assets.publishing.service.gov.uk/government/uploads/system/uploads/attachment_data/file/1036227/E02666137_CP_388_Heat_and_Buildings_Elay.pdf)
- Part L 2021 (row 21) — [Planning Portal, Approved Document L Volume 1](https://www.planningportal.co.uk/applications/building-control-applications/building-control/approved-documents/part-l-conservation-of-fuel-and-power/approved-document-l-conservation-of-fuel-and-power-volume-1-dwellings/)
- British Energy Security Strategy (row 24) — [gov.uk](https://www.gov.uk/government/publications/british-energy-security-strategy/british-energy-security-strategy)
- GBIS / ECO+ (rows 27–29) — [GB Insulation Scheme final-stage impact assessment](https://assets.publishing.service.gov.uk/media/6464afb90b72d3000c3445f9/gb-insulation-scheme-final-stage-ia.pdf); [Ofgem GBIS](https://www.ofgem.gov.uk/environmental-and-social-schemes/great-british-insulation-scheme)
- Net zero rollback (row 32) — [Carbon Brief in-depth Q&A](https://www.carbonbrief.org/in-depth-qa-what-do-rishi-sunaks-u-turns-mean-for-uk-climate-policy/) (establishes the leak and the brought-forward timing)
- FHBS 2023 consultation (row 34) — [WMS HCWS119, 13 December 2023](https://questions-statements.parliament.uk/written-statements/detail/2023-12-13/hcws119); [gov.uk consultation](https://consult.communities.gov.uk/energy-performance-of-buildings/fhbs-2023-consultation)
- Hydrogen village (rows 31, 35) — [gov.uk open letter to Gas Distribution Networks](https://www.gov.uk/government/publications/hydrogen-village-trial-open-letter-to-gas-distribution-networks); [Ofgem Stage 2 close-down](https://www.ofgem.gov.uk/consultation/hydrogen-village-trial-stage-2-close-down)
- CHMM delay (row 36) — [WMS HCWS341, 14 March 2024](https://questions-statements.parliament.uk/written-statements/detail/2024-03-14/hcws341); [November 2024 CHMM addendum response](https://assets.publishing.service.gov.uk/media/673e0f644ebce30ac7baef55/clean-heat-market-mechanism-addendum-response.pdf)
- Autumn Budget 2024 (row 37) — [Commons Library CBP-10124](https://commonslibrary.parliament.uk/research-briefings/cbp-10124/)
- EPC regime reform (rows 38, 45) — [gov.uk consultation](https://gov.uk/government/consultations/reforms-to-the-energy-performance-of-buildings-regime); [partial government response](https://gov.uk/government/consultations/reforms-to-the-energy-performance-of-buildings-regime/outcome/reforms-to-the-energy-performance-of-buildings-regime-partial-government-response)
- PRS MEES 2025 consultation and response (rows 39, 45) — [consultation document, 7 February 2025](https://assets.publishing.service.gov.uk/media/67a4e511baccec3af36b3c70/improving-the-energy-performance-of-prs-homes-consultation-document.pdf); [government response](https://www.gov.uk/government/consultations/improving-the-energy-performance-of-privately-rented-homes-2025-update/outcome/improving-the-energy-performance-of-privately-rented-homes-government-response-html)
- Decent Homes Standard and social MEES (rows 43, 46) — [DHS consultation](https://consult.communities.gov.uk/decent-homes-team/a-reformed-decent-homes-standard); [SRS MEES consultation](https://assets.publishing.service.gov.uk/media/68b852a83f3e5483efdba94e/SRS_MEES_Consultation__FINAL-Publication_version_.pdf); [gov.uk outcome](https://www.gov.uk/government/consultations/improving-the-energy-efficiency-of-socially-rented-homes-in-england)
- Budget 2025 / ECO abolition (row 44) — [Carbon Brief, UK budget 2025](https://www.carbonbrief.org/uk-budget-2025-key-climate-and-energy-announcements/); [Ofgem, treatment of ECO and RO in the price cap from April 2026](https://www.ofgem.gov.uk/sites/default/files/2026-01/Treatment%20of%20ECO%20and%20RO%20in%20the%20price%20cap%20from%20April%202026%20%281%29-20260126113009.pdf)
- Warm Homes Plan (row 45) — [gov.uk, Warm Homes Plan (HTML)](https://www.gov.uk/government/publications/warm-homes-plan/warm-homes-plan-html); [Carbon Brief Q&A](https://www.carbonbrief.org/qa-what-uks-warm-homes-plan-means-for-climate-change-and-energy-bills)
- Spending Review 2025 (row 42) — [Commons Library / Nesta summary](https://www.nesta.org.uk/blog/what-could-132-billion-do-to-improve-british-homes/)
- Future Homes Standard 2026 (row 47) — [Solar Power Portal, FHS mandates low carbon housing from 2028](https://www.solarpowerportal.co.uk/energy-policy/future-homes-standard-mandates-low-carbon-housing-from-2028) — **replace with the gov.uk publication page before use**
- SHDF waves (rows 19, 30, 40) — [SHDF Wave 2.1 competition guidance](https://assets.publishing.service.gov.uk/media/6703ed813b919067bb482d53/shdf-wave-2-1-competition-guidance-notes.pdf); [gov.uk SHDF statistics](https://www.gov.uk/government/statistics/social-housing-decarbonisation-fund-statistics-april-2026/summary-of-the-social-housing-decarbonisation-fund-statistics-april-2026)
