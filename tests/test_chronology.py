"""Deductive discovery: the taxonomy frame and chronology extraction."""

from __future__ import annotations

import pandas as pd

from policy_event_study.events.chronology import (
    Briefing,
    DatedReference,
    extract_dated_references,
)
from policy_event_study.events.taxonomy import (
    FAMILIES,
    LifecycleStage,
    empty_grid,
    family,
    grid_frame,
)

BRIEFING = Briefing(code="CBP-0000", title="Test briefing", url="https://example.org")


def reference(sentence: str, month: str = "October 2021") -> DatedReference:
    return DatedReference(
        month_year=month,
        sentence=sentence,
        source_code="CBP-0000",
        source_title="Test",
        page=1,
    )


# -- the frame -------------------------------------------------------------


def test_every_family_declares_match_terms_and_channels() -> None:
    for entry in FAMILIES:
        assert entry.match_terms, f"{entry.key} has no match terms"
        assert entry.exposure_channels, f"{entry.key} reaches no exposure channel"
        assert entry.chronology_queries


def test_grid_is_the_full_cross_product() -> None:
    cells = empty_grid()
    assert len(cells) == len(FAMILIES) * len(LifecycleStage)
    assert not any(cell.answered for cell in cells)
    assert not grid_frame(cells)["answered"].any()


def test_unknown_family_raises() -> None:
    try:
        family("no_such_family")
    except KeyError as exc:
        assert "no_such_family" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected KeyError")


def test_newsworthy_stages_are_the_ones_carrying_surprise() -> None:
    assert LifecycleStage.CONSULTATION_OUTCOME.typically_newsworthy
    assert LifecycleStage.TARGET_CHANGE.typically_newsworthy
    assert not LifecycleStage.REGULATIONS_LAID.typically_newsworthy


# -- the match-terms bug ---------------------------------------------------


def test_match_terms_are_not_the_discovery_queries() -> None:
    """Regression: matching sentences on the multi-word query empties the grid.

    "energy efficiency private rented homes" is a good query for ranking a
    chronology document and never occurs verbatim in prose. Using it as the
    sentence matcher made `mees_domestic` read as entirely absent from a
    briefing that discusses it at length.
    """
    mees = family("mees_domestic")
    prose = reference(
        "Under the 2015 Regulations, privately rented homes must meet EPC "
        "band E since April 2020."
    )
    assert not prose.matches_family(mees.chronology_queries)
    assert prose.matches_family(mees.match_terms)


def test_family_matching_is_case_insensitive() -> None:
    assert reference("The MEES regulations changed.").matches_family(
        family("mees_domestic").match_terms
    )


# -- extraction ------------------------------------------------------------


def test_a_date_alone_is_not_an_instrument_reference() -> None:
    """Briefings are dense with dates that are citations, not policy events."""
    pages = ["The chart below covers the period to March 2024. " * 2]
    assert extract_dated_references(BRIEFING, pages) == []


def test_a_date_with_an_instrument_word_is_extracted() -> None:
    pages = [
        "In October 2021 the government published the Heat and Buildings "
        "Strategy, which sets out its policies for decarbonising homes."
    ]
    found = extract_dated_references(BRIEFING, pages)
    assert len(found) == 1
    assert found[0].month_year == "October 2021"
    assert found[0].page == 1


def test_extraction_cites_the_page_it_came_from() -> None:
    pages = [
        "Nothing dated here.",
        "A consultation was published in March 2023 on the future standard.",
    ]
    found = extract_dated_references(BRIEFING, pages)
    assert len(found) == 1
    assert found[0].page == 2, "a citation to a 48-page document is not a citation"


def test_reference_period_is_month_granular() -> None:
    """No day is invented -- exact timestamps come from the content API."""
    assert reference("A scheme launched in October 2021.").period == pd.Period(
        "2021-10", freq="M"
    )


def test_very_long_and_very_short_sentences_are_skipped() -> None:
    pages = ["Scheme March 2024.", "x " * 400 + "scheme March 2024."]
    assert extract_dated_references(BRIEFING, pages) == []
