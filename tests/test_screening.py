"""Tests for the screening-universe builder."""

from __future__ import annotations

import pandas as pd
import pytest

from policy_event_study.data.screening import (
    Candidate,
    ScreeningError,
    epic_to_yahoo,
    filter_candidates,
    is_investment_vehicle,
    screen_on_prices,
)


class TestEpicToYahoo:
    """The two symbology wrinkles that a naive f-string gets wrong."""

    def test_plain_epic_gains_the_london_suffix(self) -> None:
        assert epic_to_yahoo("III") == "III.L"

    def test_trailing_dot_is_padding_and_is_stripped(self) -> None:
        # BP. -> BP.L, not BP..L. Getting this wrong fetches empty and the
        # empty result reads as a delisting.
        assert epic_to_yahoo("BP.") == "BP.L"
        assert epic_to_yahoo("AV.") == "AV.L"

    def test_internal_dot_is_a_share_class_and_becomes_a_hyphen(self) -> None:
        assert epic_to_yahoo("BT.A") == "BT-A.L"

    def test_lowercase_is_normalised(self) -> None:
        assert epic_to_yahoo("tsco") == "TSCO.L"

    def test_empty_epic_raises_rather_than_producing_a_bare_suffix(self) -> None:
        with pytest.raises(ScreeningError, match="empty EPIC"):
            epic_to_yahoo("   ")


class TestInvestmentVehicleFilter:
    """Closed-end funds out; operating companies and REITs in."""

    @pytest.mark.parametrize(
        "name",
        [
            "JPMorgan Japanese Investment Trust",
            "Scottish Mortgage Investment Trust",
            "Bluefield Solar Income Fund",
            "HarbourVest Global Private Equity",
            "Utilico Emerging Markets",
            "Law Debenture",
            "3i Group",
        ],
    )
    def test_vehicles_are_excluded(self, name: str) -> None:
        assert is_investment_vehicle(name) is True

    @pytest.mark.parametrize(
        "name",
        ["Greggs", "Travis Perkins", "Marshalls", "Genuit Group", "Grainger"],
    )
    def test_operating_companies_are_kept(self, name: str) -> None:
        assert is_investment_vehicle(name) is False

    def test_reits_are_operating_companies_not_vehicles(self) -> None:
        # "Supermarket Income REIT" contains the `income` keyword. A REIT owns
        # and lets buildings, so it is a firm; `reit` must short-circuit.
        assert is_investment_vehicle("Supermarket Income REIT") is False
        assert is_investment_vehicle("Target Healthcare REIT") is False


class TestFilterCandidates:
    """The two pre-price filters, and the reasons they record."""

    @staticmethod
    def _candidate(epic: str, name: str) -> Candidate:
        return Candidate(epic=epic, name=name, index_name="FTSE 250", source_url="u")

    def test_already_curated_names_are_dropped_with_a_reason(self) -> None:
        candidates = [self._candidate("GEN", "Genuit Group")]
        survivors, reasons = filter_candidates(candidates, exclude_tickers=["GEN.L"])
        assert survivors == ()
        assert "already curated" in reasons["GEN.L"]

    def test_a_curated_name_is_never_readmitted_as_an_assumed_zero(self) -> None:
        # This is the failure that would silently destroy the treatment: the
        # exposed firm re-enters the panel scoring zero.
        candidates = [self._candidate("KRX", "Kingspan")]
        survivors, _ = filter_candidates(candidates, exclude_tickers=["KRX.L"])
        assert survivors == ()

    def test_dual_index_membership_yields_one_candidate_not_two(self) -> None:
        candidates = [
            self._candidate("TW.", "Taylor Wimpey"),
            self._candidate("TW.", "Taylor Wimpey"),
        ]
        survivors, _ = filter_candidates(candidates, exclude_tickers=[])
        assert len(survivors) == 1

    def test_operating_company_survives_both_filters(self) -> None:
        candidates = [self._candidate("GRG", "Greggs")]
        survivors, reasons = filter_candidates(candidates, exclude_tickers=[])
        assert [c.ticker for c in survivors] == ["GRG.L"]
        assert reasons == {}


class TestScreenOnPrices:
    """History and liquidity floors, and the survivorship measurement."""

    @staticmethod
    def _frame(days: int, close: float, volume: float) -> pd.DataFrame:
        index = pd.date_range("2013-01-01", periods=days, freq="B", tz="UTC")
        return pd.DataFrame(
            {
                "close": [close] * days,
                "close_auto_adj": [close] * days,
                "volume": [volume] * days,
                "dividend": [0.0] * days,
                "split_ratio": [0.0] * days,
            },
            index=index,
        )

    @staticmethod
    def _candidate(epic: str) -> Candidate:
        return Candidate(
            epic=epic, name=f"{epic} plc", index_name="FTSE 250", source_url="u"
        )

    def test_a_liquid_long_history_is_admitted(self) -> None:
        candidates = [self._candidate("AAA")]
        # 500p x 1,000,000 shares = 5,000,000 GBP a day, well over the floor.
        frames = {"AAA.L": self._frame(700, 500.0, 1_000_000)}
        result = screen_on_prices(
            candidates,
            frames,
            min_history_days=250,
            min_avg_daily_volume_gbp=250_000,
            screen_end=pd.Timestamp("2015-06-30", tz="UTC"),
        )
        assert result.admitted == 1
        assert result.frame.loc[0, "unit_id"] == "AAA.L"

    def test_short_history_is_rejected_with_the_day_count(self) -> None:
        result = screen_on_prices(
            [self._candidate("BBB")],
            {"BBB.L": self._frame(100, 500.0, 1_000_000)},
            min_history_days=250,
            min_avg_daily_volume_gbp=250_000,
            screen_end=pd.Timestamp("2015-06-30", tz="UTC"),
        )
        assert result.admitted == 0
        assert "history floor" in result.rejected["BBB.L"]

    def test_turnover_is_read_in_pence_not_pounds(self) -> None:
        # 300p x 10,000 shares = 30,000 pence-units... the point of the test is
        # that the conversion happens: 3,000,000 pence is 30,000 GBP, which is
        # BELOW a 250,000 floor. Without the /100 it would read as 3,000,000
        # GBP and be admitted.
        result = screen_on_prices(
            [self._candidate("CCC")],
            {"CCC.L": self._frame(700, 300.0, 10_000)},
            min_history_days=250,
            min_avg_daily_volume_gbp=250_000,
            screen_end=pd.Timestamp("2015-06-30", tz="UTC"),
        )
        assert result.admitted == 0
        assert "turnover" in result.rejected["CCC.L"]

    def test_an_absent_frame_is_counted_as_survivorship_not_hidden(self) -> None:
        candidates = [self._candidate("DDD"), self._candidate("EEE")]
        frames = {"DDD.L": self._frame(700, 500.0, 1_000_000)}
        result = screen_on_prices(
            candidates,
            frames,
            min_history_days=250,
            min_avg_daily_volume_gbp=250_000,
            screen_end=pd.Timestamp("2015-06-30", tz="UTC"),
        )
        assert result.no_data == ("EEE.L",)
        assert result.attempted == 2
        assert result.survivorship_rate == pytest.approx(0.5)

    def test_every_candidate_is_admitted_or_explained(self) -> None:
        # A silent no-op is worse than a crash: a candidate in neither bucket
        # means a filter dropped a row without saying so.
        candidates = [self._candidate(epic) for epic in ("FFF", "GGG", "HHH")]
        frames = {
            "FFF.L": self._frame(700, 500.0, 1_000_000),
            "GGG.L": self._frame(50, 500.0, 1_000_000),
        }
        result = screen_on_prices(
            candidates,
            frames,
            min_history_days=250,
            min_avg_daily_volume_gbp=250_000,
            screen_end=pd.Timestamp("2015-06-30", tz="UTC"),
        )
        result.check_partition(candidates)

    def test_partition_check_raises_when_a_candidate_is_unaccounted_for(self) -> None:
        candidates = [self._candidate("III"), self._candidate("JJJ")]
        result = screen_on_prices(
            [candidates[0]],
            {"III.L": self._frame(700, 500.0, 1_000_000)},
            min_history_days=250,
            min_avg_daily_volume_gbp=250_000,
            screen_end=pd.Timestamp("2015-06-30", tz="UTC"),
        )
        with pytest.raises(ScreeningError, match="neither admitted nor rejected"):
            result.check_partition(candidates)

    def test_liquidity_window_is_the_year_before_screen_end_not_the_sample(
        self,
    ) -> None:
        # Screening on post-event activity is selection on the outcome. A firm
        # that only became liquid after the window must not be admitted.
        index = pd.date_range("2013-01-01", periods=900, freq="B", tz="UTC")
        volume = [1_000.0] * 700 + [10_000_000.0] * 200
        frame = pd.DataFrame(
            {
                "close": [500.0] * 900,
                "close_auto_adj": [500.0] * 900,
                "volume": volume,
                "dividend": [0.0] * 900,
                "split_ratio": [0.0] * 900,
            },
            index=index,
        )
        result = screen_on_prices(
            [self._candidate("KKK")],
            {"KKK.L": frame},
            min_history_days=250,
            min_avg_daily_volume_gbp=250_000,
            screen_end=pd.Timestamp("2015-06-30", tz="UTC"),
        )
        assert result.admitted == 0
