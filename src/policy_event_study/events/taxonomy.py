"""The deductive frame for event discovery: policy families x lifecycle stages.

Why the workflow is inverted
----------------------------
The first attempt discovered candidates by sweeping gov.uk search and then
filtering. That is a **search-ranking exercise**, and its failure mode is
silent and directional: large cross-cutting announcements are written in
general language ("net zero", "cost of living") while scheme adjustments are
written in technical language, so a category sweep ranks the latter. The
September 2023 rollback -- the highest-value single event in the study by
`docs/data_inventory.md` §8 -- did not surface at all under twelve technical
queries. **Recall was biased toward small events and away from large ones**,
and there is no way to audit how much was missed, because "what search did not
rank" is not enumerable.

Discovery is therefore deductive instead. This module declares a grid:

    policy family  x  instrument lifecycle stage

Each cell is a question -- *did this family produce an instrument at this
stage, and when?* -- answered from a policy chronology rather than from a
search ranking. A cell answered "none" is as much a result as a cell answered
with a date, and **that is what makes completeness auditable**: a reader can
check the grid against the same published chronologies and find a gap. Nobody
can check a search ranking.

What this module does and does not contain
------------------------------------------
It contains the **frame** -- the families and the lifecycle stages. That is
methodology, and declaring it before looking at any chronology is what stops
the taxonomy being reverse-engineered from whatever was found.

It contains **no instrument instances and no dates.** Those come from
`chronology.py`, which reads House of Commons Library research briefings and
gov.uk collection pages, and every instance carries the citation it came from.
Populating instances from recall would reintroduce exactly the unauditable
step the inversion was meant to remove -- and a date remembered wrongly is
worse than one ranked badly, because it carries no source to check it against.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Final

import pandas as pd


class LifecycleStage(enum.StrEnum):
    """Where an instrument sits in its policy lifecycle.

    Stages are ordered by how much *news* they typically carry, which is not
    the same as how much administrative weight they carry. A consultation
    outcome that settles a parameter moves prices; the regulations that later
    enact the settled parameter usually do not.
    """

    CONSULTATION_LAUNCH = "consultation_launch"
    CONSULTATION_OUTCOME = "consultation_outcome"
    STRATEGY = "strategy"
    REGULATIONS_LAID = "regulations_laid"
    SCHEME_LAUNCH = "scheme_launch"
    SCHEME_AMENDMENT = "scheme_amendment"
    SCHEME_EXTENSION = "scheme_extension"
    SCHEME_CLOSURE = "scheme_closure"
    TARGET_CHANGE = "target_change"
    REVIEW = "review"

    @property
    def typically_newsworthy(self) -> bool:
        """Whether this stage usually carries unanticipated content.

        A heuristic for prioritising leak checks, which are the expensive
        step. Not a filter: a regulations-laid step that departs from the
        consulted position is a genuine surprise, and the grid keeps it.
        """
        return self in {
            LifecycleStage.CONSULTATION_OUTCOME,
            LifecycleStage.STRATEGY,
            LifecycleStage.SCHEME_LAUNCH,
            LifecycleStage.SCHEME_AMENDMENT,
            LifecycleStage.SCHEME_CLOSURE,
            LifecycleStage.TARGET_CHANGE,
        }


@dataclass(frozen=True)
class PolicyFamily:
    """One coherent policy strand to enumerate instruments for.

    Attributes
    ----------
    key
        Stable identifier, used as the row key of the completeness grid.
    exposure_channels
        Which `config/exposure.yaml` channels this family can reach. A family
        touching no channel cannot produce a dose-response event and is
        carried only for contrast -- see `protocol` Step 5.
    chronology_queries
        Terms for locating a published chronology of this family, **not** for
        locating the events themselves. The distinction is the whole point of
        the inversion: search finds the timeline document, the timeline
        document enumerates the instruments.
    match_terms
        Terms that identify a *sentence* as belonging to this family, once a
        chronology has been read. Deliberately separate from
        `chronology_queries` and deliberately shorter. A query is a phrase
        chosen to rank a document; a match term is a token that appears in
        running prose. Using the query as the matcher is a bug that looks like
        an empty grid: "energy efficiency private rented homes" never occurs
        verbatim in a sentence such as "privately rented homes must meet EPC
        band E", so the family reads as absent when it is merely phrased
        differently.
    """

    key: str
    label: str
    exposure_channels: tuple[str, ...]
    chronology_queries: tuple[str, ...]
    match_terms: tuple[str, ...] = ()
    collection_hints: tuple[str, ...] = ()
    note: str = ""


#: The families to enumerate. Chosen to span the exposure channels rather than
#: to span "UK energy policy": a family that cannot reach any channel produces
#: no dose and cannot identify anything, however important it is politically.
FAMILIES: Final[tuple[PolicyFamily, ...]] = (
    PolicyFamily(
        key="mees_domestic",
        label="Minimum energy efficiency standards, domestic private rented",
        exposure_channels=("residential_stock",),
        chronology_queries=("energy efficiency private rented homes", "MEES landlords"),
        match_terms=(
            "private rented",
            "privately rented",
            "landlord",
            "mees",
            "minimum energy efficiency",
        ),
        collection_hints=("private-rented-sector-energy-efficiency",),
        note="The clearest landlord-capex channel in the study.",
    ),
    PolicyFamily(
        key="mees_nondomestic",
        label="Minimum energy efficiency standards, non-domestic",
        exposure_channels=("residential_stock",),
        chronology_queries=(
            "non-domestic private rented",
            "commercial property energy efficiency",
            "minimum energy efficiency standards",
        ),
        match_terms=(
            "non-domestic",
            "commercial property",
            "non domestic private rented",
        ),
        note=(
            "Drives the Segro per-event override; commercial, not domestic. "
            "NO CHRONOLOGY SOURCE FOUND as of the 2026-08-15 run: the Commons "
            "Library returns nothing for any non-domestic MEES query and no "
            "gov.uk collection groups the instruments. Treat this family as "
            "unenumerated rather than empty -- the instruments exist, the "
            "timeline document does not."
        ),
    ),
    PolicyFamily(
        key="future_homes",
        label="Future Homes Standard and Part L building regulations",
        exposure_channels=("delivered_stock", "product_revenue"),
        chronology_queries=(
            "Future Homes Standard",
            "building regulations energy homes",
        ),
        match_terms=(
            "future homes",
            "part l",
            "building regulations",
            "new build",
            "new homes",
            "sap ",
        ),
        collection_hints=("approved-documents",),
        note="The housebuilder build-standard channel.",
    ),
    PolicyFamily(
        key="epc_regime",
        label="EPC and the Energy Performance of Buildings regime",
        exposure_channels=("residential_stock", "delivered_stock"),
        chronology_queries=("energy performance certificates reform",),
        match_terms=(
            "epc",
            "energy performance certificate",
            "energy performance of buildings",
        ),
        note="Changes the measurement every stock-based dose is scored against.",
    ),
    PolicyFamily(
        key="eco",
        label="Energy Company Obligation phases",
        exposure_channels=("product_revenue", "domestic_supply"),
        chronology_queries=("energy company obligation", "ECO scheme"),
        match_terms=(
            "energy company obligation",
            "eco1",
            "eco2",
            "eco3",
            "eco4",
            "obligation",
        ),
        collection_hints=("green-deal-and-energy-company-obligation-eco-statistics",),
    ),
    PolicyFamily(
        key="gbis",
        label="Great British Insulation Scheme",
        exposure_channels=("product_revenue",),
        chronology_queries=(
            "Great British Insulation Scheme",
            "ECO+",
        ),
        match_terms=("great british insulation", "gbis", "eco+", "insulation scheme"),
    ),
    PolicyFamily(
        key="green_homes_grant",
        label="Green Homes Grant",
        exposure_channels=("product_revenue",),
        chronology_queries=("Green Homes Grant",),
        match_terms=("green homes grant", "ghgvs", "ghg voucher", "voucher scheme"),
        collection_hints=("green-homes-grant-scheme",),
        note="Launch and cancellation are an unusually clean pair of opposite-signed shocks.",
    ),
    PolicyFamily(
        key="boiler_upgrade",
        label="Boiler Upgrade Scheme and heat pump grants",
        exposure_channels=("product_revenue",),
        chronology_queries=(
            "Boiler Upgrade Scheme",
            "Renewable Heat Incentive",
            "heat pump grant",
        ),
        match_terms=(
            "boiler upgrade",
            "heat pump grant",
            "renewable heat incentive",
            "rhi",
        ),
        collection_hints=("boiler-upgrade-scheme-statistics",),
    ),
    PolicyFamily(
        key="boiler_phase_out",
        label="Gas boiler phase-out dates and heating targets",
        exposure_channels=("product_revenue", "domestic_supply"),
        chronology_queries=("gas boiler phase out", "heat in buildings targets"),
        match_terms=(
            "gas boiler",
            "boiler phase",
            "phase out",
            "phased out",
            "2035",
            "2025 ",
            "fossil fuel boiler",
            "net zero",
        ),
        note="Where the September 2023 rollback lands. Target changes, not schemes.",
    ),
    PolicyFamily(
        key="warm_homes",
        label="Warm Homes Plan, Home Upgrade Grant, social housing funds",
        exposure_channels=("product_revenue", "residential_stock"),
        chronology_queries=("Warm Homes Plan", "home upgrade grant social housing"),
        match_terms=(
            "warm homes",
            "home upgrade grant",
            "social housing decarbonisation",
            "warm home",
        ),
    ),
    PolicyFamily(
        key="heat_buildings_strategy",
        label="Heat and Buildings Strategy and successors",
        exposure_channels=("product_revenue", "residential_stock", "delivered_stock"),
        chronology_queries=("heat and buildings strategy",),
        match_terms=(
            "heat and buildings",
            "heat in buildings",
            "decarbonising homes",
            "decarbonisation of homes",
        ),
    ),
    PolicyFamily(
        key="uk_ets_buildings",
        label="UK ETS scope and carbon pricing reaching buildings",
        exposure_channels=("domestic_supply",),
        chronology_queries=("UK emissions trading scheme buildings scope",),
        match_terms=("emissions trading", "carbon price", "ets"),
        collection_hints=(
            "uk-emissions-trading-scheme-uk-ets-reports-and-scheme-reviews",
        ),
        note="Reaches the channel scored zero by configuration; carried for completeness.",
    ),
    PolicyFamily(
        key="decent_homes",
        label="Decent Homes Standard, social and private rented",
        exposure_channels=("residential_stock",),
        chronology_queries=("decent homes standard private rented",),
        match_terms=(
            "decent homes",
            "dhs",
            "housing health and safety",
            "awaab",
            "hhsrs",
        ),
    ),
    PolicyFamily(
        key="fiscal_events",
        label="Budgets and fiscal statements carrying buildings measures",
        exposure_channels=("product_revenue", "residential_stock"),
        chronology_queries=("budget energy efficiency VAT insulation",),
        match_terms=(
            "budget",
            "spring statement",
            "autumn statement",
            "vat",
            "spending review",
        ),
        note=(
            "Confounded by construction -- a measure inside a fiscal statement "
            "cannot be separated from the statement. Enumerated so the "
            "confounding is recorded rather than discovered late."
        ),
    ),
)


@dataclass
class GridCell:
    """One family x stage cell of the completeness grid."""

    family: str
    stage: LifecycleStage
    instruments: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)

    @property
    def answered(self) -> bool:
        """True when at least one instrument was found for this cell."""
        return bool(self.instruments)


def empty_grid() -> list[GridCell]:
    """Build the unpopulated completeness grid.

    Every cell starts empty and unanswered. That is the point: the grid is a
    checklist of questions to put to a chronology, and an unanswered cell is a
    visible gap rather than an absence nobody looked for.
    """
    return [
        GridCell(family=family.key, stage=stage)
        for family in FAMILIES
        for stage in LifecycleStage
    ]


def grid_frame(cells: list[GridCell]) -> pd.DataFrame:
    """Render the grid as a frame, one row per family x stage."""
    return pd.DataFrame(
        [
            {
                "family": cell.family,
                "stage": str(cell.stage),
                "newsworthy": cell.stage.typically_newsworthy,
                "n_instruments": len(cell.instruments),
                "answered": cell.answered,
                "instruments": " | ".join(cell.instruments[:3]),
            }
            for cell in cells
        ]
    )


def family(key: str) -> PolicyFamily:
    """Look up a family by key."""
    for candidate in FAMILIES:
        if candidate.key == key:
            return candidate
    msg = f"unknown policy family {key!r}"
    raise KeyError(msg)
