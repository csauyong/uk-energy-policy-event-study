"""Exposure measure: channels, sign convention, point-in-time, standardisation."""

from __future__ import annotations

import pandas as pd
import pytest

from policy_event_study.exposure.build import (
    ExposureConfig,
    build_exposure_panel,
    exposure_dispersion,
    load_exposure_config,
    parse_exposure_inputs,
    score_firm,
    unscoreable_targets,
    validate_exposure_inputs,
)
from policy_event_study.exposure.channels import band_index, share_below_band
from policy_event_study.exposure.schema import (
    Direction,
    ExposureValidationError,
    FirmAttribute,
    PolicyTarget,
    Scope,
    filter_knowable,
    latest_by_attribute,
)

BANDS = ("A", "B", "C", "D", "E", "F", "G")
ANNOUNCEMENT = pd.Timestamp("2023-09-20T19:00:00Z")


@pytest.fixture
def config() -> ExposureConfig:
    return load_exposure_config()


def attribute(
    unit: str,
    name: str,
    value: float,
    *,
    knowable: str = "2023-01-15",
    as_of: str = "2022-12-31",
) -> FirmAttribute:
    return FirmAttribute(
        unit_id=unit,
        attribute=name,
        value=value,
        as_of_date=pd.Timestamp(as_of),
        knowable_from=pd.Timestamp(knowable),
        source_url="https://example.com/report",
        vintage="2023-annual",
    )


def target(**overrides: object) -> PolicyTarget:
    fields: dict[str, object] = {
        "event_id": "E1",
        "mandated_min_band": "C",
        "affected_categories": ("insulation", "heating"),
        "scope": Scope.ALL_DOMESTIC,
        "direction": Direction.TIGHTEN,
    }
    fields.update(overrides)
    return PolicyTarget(**fields)  # type: ignore[arg-type]  # kwargs typed above


# -- band arithmetic -------------------------------------------------------


def test_share_below_band_counts_only_worse_bands() -> None:
    stock = {"B": 10.0, "C": 10.0, "D": 20.0, "F": 10.0}
    # Mandate at C: B and C comply, D and F do not -> 30/50.
    assert share_below_band(stock, "C", BANDS) == pytest.approx(0.6)


def test_share_below_band_is_zero_for_a_compliant_portfolio() -> None:
    assert share_below_band({"A": 5.0, "B": 5.0}, "C", BANDS) == 0.0


def test_empty_stock_scores_zero_not_missing() -> None:
    assert share_below_band({}, "C", BANDS) == 0.0


def test_unknown_band_is_refused() -> None:
    """A typo must not be silently treated as the worst band."""
    with pytest.raises(ValueError, match="unknown EPC band"):
        band_index("Z", BANDS)


# -- channels --------------------------------------------------------------


def test_landlord_dose_is_the_non_compliant_share(config: ExposureConfig) -> None:
    attributes = {
        "dwellings_band_B": attribute("GRI.L", "dwellings_band_B", 200.0),
        "dwellings_band_E": attribute("GRI.L", "dwellings_band_E", 300.0),
    }
    score = score_firm("GRI.L", attributes, target(), config)
    assert score.channel == "residential_stock"
    assert score.magnitude == pytest.approx(0.6)
    # Unfunded capex: negative under a tightening.
    assert score.signed == pytest.approx(-0.6)


def test_portfolio_size_does_not_drive_the_dose(config: ExposureConfig) -> None:
    """A large compliant portfolio scores below a small non-compliant one."""
    big_clean = score_firm(
        "BIG",
        {"dwellings_band_A": attribute("BIG", "dwellings_band_A", 100_000.0)},
        target(),
        config,
    )
    small_dirty = score_firm(
        "SMALL",
        {"dwellings_band_F": attribute("SMALL", "dwellings_band_F", 500.0)},
        target(),
        config,
    )
    assert big_clean.magnitude == 0.0
    assert small_dirty.magnitude == 1.0


def test_housebuilder_already_at_standard_scores_zero(config: ExposureConfig) -> None:
    """A builder delivering at the mandated standard faces no compliance cost."""
    attributes = {
        "delivered_units_band_D": attribute("PSN.L", "delivered_units_band_D", 1000.0),
        # band_index("B") == 1, mandate at C == 2, so 1 <= 2: already compliant.
        "build_standard_band": attribute("PSN.L", "build_standard_band", 1.0),
    }
    score = score_firm("PSN.L", attributes, target(scope=Scope.NEW_BUILD), config)
    assert score.channel == "delivered_stock"
    assert score.magnitude == 0.0


def test_housebuilder_below_standard_carries_dose(config: ExposureConfig) -> None:
    attributes = {
        "delivered_units_band_D": attribute("PSN.L", "delivered_units_band_D", 1000.0),
        "build_standard_band": attribute("PSN.L", "build_standard_band", 3.0),
    }
    score = score_firm("PSN.L", attributes, target(scope=Scope.NEW_BUILD), config)
    assert score.magnitude == pytest.approx(1.0)


def test_product_dose_multiplies_by_uk_revenue_share(config: ExposureConfig) -> None:
    attributes = {
        "revenue_share_insulation": attribute(
            "KRX.IR", "revenue_share_insulation", 0.5
        ),
        "uk_revenue_share": attribute("KRX.IR", "uk_revenue_share", 0.4),
    }
    score = score_firm("KRX.IR", attributes, target(), config)
    assert score.channel == "product_revenue"
    assert score.magnitude == pytest.approx(0.2)
    assert score.signed == pytest.approx(0.2)  # demand channel: positive


def test_foreign_manufacturer_without_uk_share_is_not_defaulted(
    config: ExposureConfig,
) -> None:
    """Defaulting the UK share to 1.0 would hand every foreign firm full exposure."""
    attributes = {
        "revenue_share_insulation": attribute("OC", "revenue_share_insulation", 0.6)
    }
    score = score_firm("OC", attributes, target(), config)
    assert score.channel == "none"


def test_revenue_outside_the_affected_categories_is_a_measured_zero(
    config: ExposureConfig,
) -> None:
    attributes = {
        "revenue_share_flooring": attribute("X.L", "revenue_share_flooring", 0.9),
        "uk_revenue_share": attribute("X.L", "uk_revenue_share", 1.0),
    }
    score = score_firm("X.L", attributes, target(), config)
    assert score.channel == "product_revenue"
    assert score.magnitude == 0.0


def test_utility_channel_scores_zero_by_configuration(config: ExposureConfig) -> None:
    """`domestic_supply.channel_sign` is 0: the sign cannot be signed ex ante."""
    attributes = {
        "domestic_supply_share_gb": attribute("CNA.L", "domestic_supply_share_gb", 0.7)
    }
    score = score_firm("CNA.L", attributes, target(), config)
    assert score.channel == "domestic_supply"
    assert score.magnitude == pytest.approx(0.7)
    assert score.signed == 0.0


# -- unscoreable targets (2026-08-17) --------------------------------------


def test_unscoreable_target_is_skipped_not_scored_as_zero(
    config: ExposureConfig,
) -> None:
    """An exposure the design could not measure is not an exposure of zero.

    Scoring the 8 blank `new_build` rows would put a fabricated zero on every
    firm at 8 events, dragging beta toward zero through rows that carry no
    information. It would also crash the moment a landlord band profile exists,
    because a blank band reaches `band_index`.
    """
    blank = target(event_id="E_BLANK", mandated_min_band="", affected_categories=())
    scored = target(event_id="E_OK")
    assert unscoreable_targets([blank, scored]) == (blank,)

    times = {"E_BLANK": ANNOUNCEMENT, "E_OK": ANNOUNCEMENT}
    landlord = [attribute("GRI.L", "dwellings_prs_band_E", 1000.0)]
    panel = build_exposure_panel(["GRI.L"], landlord, [blank, scored], times, config)

    assert set(panel["event_id"]) == {"E_OK"}
    assert panel.attrs["unscoreable_event_ids"] == ("E_BLANK",)
    assert panel.attrs["n_unscoreable_targets"] == 1


def test_all_targets_unscoreable_raises(config: ExposureConfig) -> None:
    """A silent empty panel is worse than a crash."""
    blank = target(mandated_min_band="", affected_categories=())
    with pytest.raises(ValueError, match="no channel can score any of them"):
        build_exposure_panel(["GRI.L"], [], [blank], {"E1": ANNOUNCEMENT}, config)


# -- scope gating (2026-08-17) ---------------------------------------------


def test_prs_landlord_is_not_reached_by_a_social_rented_mandate(
    config: ExposureConfig,
) -> None:
    """MEES binds by tenure. Before this gate, both scored fully against both."""
    prs_landlord = {
        "dwellings_prs_band_E": attribute("GRI.L", "dwellings_prs_band_E", 1000.0)
    }
    on_prs = score_firm("GRI.L", prs_landlord, target(scope=Scope.DOMESTIC_PRS), config)
    on_social = score_firm(
        "GRI.L", prs_landlord, target(scope=Scope.SOCIAL_RENTED), config
    )
    assert on_prs.channel == "residential_stock"
    assert on_prs.magnitude == pytest.approx(1.0)
    # Measured zero, not an artefact: the firm holds no social rented stock.
    assert on_social.channel == "none"
    assert on_social.magnitude == 0.0


def test_all_domestic_sums_every_tenure(config: ExposureConfig) -> None:
    """An instrument reaching every tenure sees the whole portfolio."""
    mixed = {
        "dwellings_prs_band_B": attribute("RESI.L", "dwellings_prs_band_B", 300.0),
        "dwellings_social_band_E": attribute(
            "RESI.L", "dwellings_social_band_E", 700.0
        ),
    }
    score = score_firm("RESI.L", mixed, target(scope=Scope.ALL_DOMESTIC), config)
    assert score.magnitude == pytest.approx(0.7)


def test_undisclosed_tenure_does_not_score_a_tenure_specific_event(
    config: ExposureConfig,
) -> None:
    """The generic prefix means tenure NOT disclosed, so it must not be assumed.

    Scoring it as though the whole portfolio were private rented would be a
    fabricated value under R5. Returning "does not apply" forces the curator to
    state the tenure, which is a disclosure.
    """
    undisclosed = {
        "dwellings_band_E": attribute("X.L", "dwellings_band_E", 1000.0),
    }
    assert (
        score_firm("X.L", undisclosed, target(scope=Scope.DOMESTIC_PRS), config).channel
        == "none"
    )
    assert score_firm(
        "X.L", undisclosed, target(scope=Scope.ALL_DOMESTIC), config
    ).magnitude == pytest.approx(1.0)


def test_housebuilder_is_not_reached_by_a_let_property_mandate(
    config: ExposureConfig,
) -> None:
    """A minimum-EPC mandate binds whoever holds the stock, not whoever built it."""
    builder = {
        "delivered_units_band_E": attribute("PSN.L", "delivered_units_band_E", 1000.0)
    }
    score = score_firm("PSN.L", builder, target(scope=Scope.DOMESTIC_PRS), config)
    assert score.channel == "none"


def test_unmatched_firm_scores_an_explicit_zero(config: ExposureConfig) -> None:
    """Zero-exposure firms are the identification, not discards."""
    score = score_firm("GRG.L", {}, target(), config)
    assert score.channel == "none"
    assert score.is_explicit_zero


# -- the sign convention ---------------------------------------------------


def test_loosening_flips_every_sign(config: ExposureConfig) -> None:
    """A rollback should move exposed firms the opposite way. The falsification test."""
    attributes = {
        "revenue_share_insulation": attribute(
            "KRX.IR", "revenue_share_insulation", 0.5
        ),
        "uk_revenue_share": attribute("KRX.IR", "uk_revenue_share", 1.0),
    }
    tightening = score_firm("KRX.IR", attributes, target(), config)
    loosening = score_firm(
        "KRX.IR", attributes, target(direction=Direction.LOOSEN), config
    )
    assert tightening.signed == pytest.approx(-loosening.signed)
    assert tightening.magnitude == loosening.magnitude


def test_opposite_channels_carry_opposite_signs(config: ExposureConfig) -> None:
    """The reason exposure is signed at all."""
    maker = score_firm(
        "KRX.IR",
        {
            "revenue_share_insulation": attribute(
                "KRX.IR", "revenue_share_insulation", 1.0
            ),
            "uk_revenue_share": attribute("KRX.IR", "uk_revenue_share", 1.0),
        },
        target(),
        config,
    )
    landlord = score_firm(
        "GRI.L",
        {"dwellings_band_G": attribute("GRI.L", "dwellings_band_G", 100.0)},
        target(),
        config,
    )
    assert maker.signed > 0 > landlord.signed
    assert maker.magnitude == landlord.magnitude == 1.0


def test_ambiguous_channels_are_flagged_for_sensitivity(config: ExposureConfig) -> None:
    assert set(config.ambiguous_channels) == {"delivered_stock", "domestic_supply"}


# -- point-in-time ---------------------------------------------------------


@pytest.mark.pointintime
def test_attributes_published_after_the_announcement_are_withheld() -> None:
    """The core leak: a post-event disclosure must not enter a pre-event score."""
    before = attribute("GRI.L", "dwellings_band_E", 100.0, knowable="2023-01-15")
    after = attribute("GRI.L", "dwellings_band_E", 900.0, knowable="2023-11-01")
    knowable, withheld = filter_knowable([before, after], ANNOUNCEMENT)
    assert knowable == (before,)
    assert withheld == (after,)


@pytest.mark.pointintime
def test_withheld_attributes_are_reported_not_silently_dropped() -> None:
    """A silent drop is indistinguishable from an absent attribute."""
    after = attribute("GRI.L", "dwellings_band_E", 900.0, knowable="2023-11-01")
    _, withheld = filter_knowable([after], ANNOUNCEMENT)
    assert len(withheld) == 1


@pytest.mark.pointintime
def test_naive_announcement_timestamp_is_refused() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        filter_knowable([], pd.Timestamp("2023-09-20"))


def test_freshest_knowable_vintage_wins() -> None:
    old = attribute("GRI.L", "dwellings_band_E", 100.0, knowable="2021-03-01")
    new = attribute("GRI.L", "dwellings_band_E", 250.0, knowable="2023-03-01")
    latest = latest_by_attribute([old, new])
    assert latest[("GRI.L", "dwellings_band_E")].value == 250.0


@pytest.mark.parametrize("reverse", [False, True])
def test_knowable_from_tie_is_broken_on_as_of_not_row_order(reverse: bool) -> None:
    """R7 guarantees this tie, so row order must not decide the score.

    A prior-year comparative carries the *later* report's `knowable_from`, so
    every attribute curated with a comparative yields two equally-knowable rows
    differing only in the period described. Ranking on `knowable_from` alone
    left the pair unordered and the CSV's row order picked the winner: sorting
    `firm_attributes.csv` would have swapped the current-year figure for the
    prior-year one, silently, with a plausible number.

    Live instances at the time of writing: GEN.L and MSLH.L `uk_revenue_share`
    (FY2024 and its FY2023 comparative, both knowable 2025-03-10) and KRX.IR
    `uk_revenue_share` (FY2020 and the restated FY2019, both knowable
    2021-02-19).
    """
    current = attribute(
        "KRX.IR", "uk_revenue_share", 0.1625, knowable="2021-02-19", as_of="2020-12-31"
    )
    comparative = attribute(
        "KRX.IR", "uk_revenue_share", 0.1821, knowable="2021-02-19", as_of="2019-12-31"
    )
    rows = [comparative, current] if reverse else [current, comparative]
    chosen = latest_by_attribute(rows)[("KRX.IR", "uk_revenue_share")]
    assert chosen.as_of_date == pd.Timestamp("2020-12-31")
    assert chosen.value == 0.1625


@pytest.mark.pointintime
def test_panel_scores_from_pre_announcement_data_only(config: ExposureConfig) -> None:
    """End-to-end: the post-event disclosure must not change the score."""
    honest = [attribute("GRI.L", "dwellings_band_E", 100.0, knowable="2023-01-15")]
    contaminated = [
        *honest,
        attribute("GRI.L", "dwellings_band_B", 900.0, knowable="2023-11-01"),
    ]
    times = {"E1": ANNOUNCEMENT}
    clean = build_exposure_panel(["GRI.L"], honest, [target()], times, config)
    leaky = build_exposure_panel(["GRI.L"], contaminated, [target()], times, config)
    assert float(clean["exposure_magnitude"].iloc[0]) == pytest.approx(
        float(leaky["exposure_magnitude"].iloc[0])
    )
    assert int(leaky["n_withheld_not_knowable"].iloc[0]) == 1


# -- panel assembly --------------------------------------------------------


def test_panel_standardises_within_event(config: ExposureConfig) -> None:
    attributes = [
        attribute("A.L", "dwellings_band_G", 100.0),
        attribute("B.L", "dwellings_band_A", 100.0),
    ]
    units = ["A.L", "B.L", "C.L", "D.L"]
    panel = build_exposure_panel(
        units, attributes, [target()], {"E1": ANNOUNCEMENT}, config
    )
    assert len(panel) == 4
    assert float(panel["exposure_continuous"].mean()) == pytest.approx(0.0, abs=1e-9)
    assert "exposure_rank" in panel.columns


def test_panel_records_zero_exposure_firms(config: ExposureConfig) -> None:
    panel = build_exposure_panel(
        ["A.L", "B.L", "C.L"],
        [attribute("A.L", "dwellings_band_G", 10.0)],
        [target()],
        {"E1": ANNOUNCEMENT},
        config,
    )
    assert (panel["channel"] == "none").sum() == 2
    assert (panel["exposure_magnitude"] == 0.0).sum() == 2


def test_panel_requires_an_announcement_timestamp(config: ExposureConfig) -> None:
    with pytest.raises(KeyError, match="point-in-time"):
        build_exposure_panel(["A.L"], [], [target()], {}, config)


def test_dispersion_table_reports_what_power_depends_on(config: ExposureConfig) -> None:
    attributes = [
        attribute("A.L", "dwellings_band_G", 100.0),
        attribute("B.L", "dwellings_band_A", 100.0),
    ]
    panel = build_exposure_panel(
        ["A.L", "B.L", "C.L"], attributes, [target()], {"E1": ANNOUNCEMENT}, config
    )
    table = exposure_dispersion(panel)
    assert int(table["n_firms"].iloc[0]) == 3
    assert int(table["n_nonzero"].iloc[0]) == 1


# -- validation ------------------------------------------------------------


def attribute_frame(**overrides: str) -> pd.DataFrame:
    row = {
        "unit_id": "GRI.L",
        "attribute": "dwellings_band_E",
        "value": "100",
        "as_of_date": "2022-12-31",
        "knowable_from": "2023-03-15",
        "source_url": "https://example.com/ar2022.pdf",
        "vintage": "2022-annual",
    }
    row.update(overrides)
    return pd.DataFrame([row])


def target_frame(**overrides: str) -> pd.DataFrame:
    row = {
        "event_id": "E1",
        "mandated_min_band": "C",
        "affected_categories": "insulation;heating",
        "scope": "all_domestic",
        "direction": "tighten",
    }
    row.update(overrides)
    return pd.DataFrame([row])


def test_good_inputs_validate() -> None:
    report = validate_exposure_inputs(attribute_frame(), target_frame())
    assert report.ok, report.render()


def test_knowable_before_as_of_is_refused() -> None:
    """A figure cannot be public before the period it describes has ended."""
    report = validate_exposure_inputs(
        attribute_frame(as_of_date="2023-12-31", knowable_from="2023-03-15"),
        target_frame(),
    )
    assert not report.ok


def test_missing_source_url_is_refused() -> None:
    report = validate_exposure_inputs(attribute_frame(source_url=""), target_frame())
    assert not report.ok


def test_non_numeric_value_is_refused() -> None:
    report = validate_exposure_inputs(attribute_frame(value="lots"), target_frame())
    assert not report.ok


def test_bad_direction_is_refused() -> None:
    report = validate_exposure_inputs(
        attribute_frame(), target_frame(direction="sideways")
    )
    assert not report.ok


def test_event_with_no_target_at_all_warns_and_is_not_refused() -> None:
    """Unscoreable is not invalid. Changed 2026-08-17; see the decision log.

    Eight `new_build` rows carry a blank band and no category on purpose: they
    are the record of the `delivered_stock` exposure the design could not
    measure. Rejecting the file would force a curator to delete that record to
    make the loader work, so the row warns, and `build_exposure_panel` skips
    and counts it instead of scoring every firm zero against it.
    """
    report = validate_exposure_inputs(
        attribute_frame(), target_frame(mandated_min_band="", affected_categories="")
    )
    assert report.ok
    assert len(report.warnings) == 1
    assert "SKIPPED and counted" in report.warnings[0].message


def test_unknown_unit_is_refused_when_a_whitelist_is_given() -> None:
    report = validate_exposure_inputs(
        attribute_frame(), target_frame(), known_units=["SGRO.L"]
    )
    assert not report.ok


def test_long_disclosure_lag_warns() -> None:
    report = validate_exposure_inputs(
        attribute_frame(as_of_date="2020-12-31", knowable_from="2023-03-15"),
        target_frame(),
    )
    assert report.ok
    assert report.warnings


def test_parse_raises_on_fatal() -> None:
    with pytest.raises(ExposureValidationError):
        parse_exposure_inputs(attribute_frame(source_url=""), target_frame())


def test_committed_templates_carry_the_schema() -> None:
    from policy_event_study.exposure.build import (
        FIRM_ATTRIBUTES_CSV,
        POLICY_TARGETS_CSV,
    )
    from policy_event_study.exposure.schema import (
        ATTRIBUTE_COLUMNS,
        POLICY_TARGET_COLUMNS,
    )

    for path, required in (
        (FIRM_ATTRIBUTES_CSV, ATTRIBUTE_COLUMNS),
        (POLICY_TARGETS_CSV, POLICY_TARGET_COLUMNS),
    ):
        header = path.read_text(encoding="utf-8").splitlines()[0].split(",")
        assert set(required).issubset(header)


def test_curated_targets_load_under_strict_validation() -> None:
    """The real file must load, not just the fixtures.

    It did not until 2026-08-17: the `Scope` enum still carried
    `domestic/commercial/both` while the curated file used the tenure
    vocabulary, so every one of the 30 rows failed. The exposure pipeline had
    never been run end to end against its own inputs.
    """
    from policy_event_study.exposure.build import (
        parse_exposure_inputs,
        read_exposure_inputs,
    )

    attributes_frame, targets_frame = read_exposure_inputs()
    _, targets, report = parse_exposure_inputs(attributes_frame, targets_frame)
    assert report.ok
    assert len(targets) == 30


def test_six_events_cannot_be_scored_at_all() -> None:
    """Pinned arithmetic: the dose-response `n` is 18 of 24, not 19.

    `reports/decision_log.md` recorded 19 on 2026-08-16 by counting only the
    seven `new_build` rows with blank bands. It missed `epc-reform-consultation`,
    whose band is blank for a *different* and deliberate reason -- the
    consultation reforms the EPC metric rather than mandating a band -- and
    which carries no affected category either. So it is unscoreable too.

    `CLAUDE.md` requires `n` to be stated separately for the event dictionary
    and for the dose-response. This is that number, and it is pinned because
    the last hand count of it was wrong by one.
    """
    from policy_event_study.exposure.build import (
        parse_exposure_inputs,
        read_exposure_inputs,
        unscoreable_targets,
    )

    attributes_frame, targets_frame = read_exposure_inputs()
    _, targets, _ = parse_exposure_inputs(attributes_frame, targets_frame)

    scoreable_events = {t.event_id for t in targets if t.is_scoreable}
    all_events = {t.event_id for t in targets}
    dead = all_events - scoreable_events

    assert len(all_events) == 24
    assert len(scoreable_events) == 18
    assert dead == {
        "zero-carbon-homes-cancelled",
        "fhs-2019-consultation",
        "fhs-2019-response",
        "part-l-2021-published",
        "fhbs-2023-consultation",
        "epc-reform-consultation",
    }
    # Two events keep a scoreable product leg while losing an unscoreable one.
    assert {t.event_id for t in unscoreable_targets(targets)} - dead == {
        "ten-point-plan",
        "future-homes-standard-2026",
    }
