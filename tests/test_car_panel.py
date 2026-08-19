"""Tests for the controls builder and the stacked CAR panel."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from policy_event_study.data.prices import (
    Adjustment,
    PanelProvenance,
    ReturnPanel,
)
from policy_event_study.data.universe import Alignment
from policy_event_study.estimators.base import EventSpec
from policy_event_study.estimators.car_panel import (
    CARPanel,
    CARPanelError,
    build_car_panel,
)
from policy_event_study.estimators.controls import (
    MOMENTUM_LOOKBACK_DAYS,
    MOMENTUM_SKIP_DAYS,
    ControlError,
    build_controls,
)
from policy_event_study.estimators.dose_response import DEFAULT_CONTROLS
from policy_event_study.events.schema import resolve_event_timing

UNITS = ("AAA.L", "BBB.L", "CCC.L", "DDD.L")


def _provenance() -> PanelProvenance:
    """Minimal provenance for a synthetic panel."""
    return PanelProvenance(
        vintage="test",
        adjustment=Adjustment.POINT_IN_TIME,
        alignment=Alignment.LAG_LATE_MARKETS,
        universe_path="tests/synthetic",
        source="synthetic",
    )


@pytest.fixture
def panel() -> ReturnPanel:
    """A synthetic panel with enough history for the momentum lookback."""
    rng = np.random.default_rng(20260818)
    days = pd.date_range("2015-01-01", periods=1200, freq="B", tz="UTC")
    market = pd.Series(rng.normal(0.0, 0.01, len(days)), index=days, name="market")
    returns = pd.DataFrame(
        {
            unit: market * (0.8 + 0.1 * index) + rng.normal(0.0, 0.008, len(days))
            for index, unit in enumerate(UNITS)
        },
        index=days,
    )
    return ReturnPanel(
        returns=returns,
        market=market,
        provenance=_provenance(),
    )


def _spec(panel: ReturnPanel, offset: int, event_id: str = "e1") -> EventSpec:
    t0 = panel.trading_days[offset]
    timing = resolve_event_timing(t0, panel.trading_days, time_known=True)
    return EventSpec(event_id=event_id, timing=timing, donors=UNITS)


class TestDefaultControls:
    """The dropped control, asserted so it cannot come back by accident."""

    def test_book_to_market_is_not_a_default_control(self) -> None:
        assert "book_to_market" not in DEFAULT_CONTROLS

    def test_the_three_price_derived_controls_are(self) -> None:
        assert DEFAULT_CONTROLS == ("size", "momentum", "pre_event_vol")


class TestBuildControls:
    def test_returns_one_row_per_requested_unit(self, panel: ReturnPanel) -> None:
        controls = build_controls(panel, _spec(panel, 900), UNITS)
        assert list(controls.index) == list(UNITS)
        assert {"size", "momentum", "pre_event_vol"} <= set(controls.columns)

    def test_a_unit_absent_from_the_panel_gets_nan_not_a_dropped_row(
        self, panel: ReturnPanel
    ) -> None:
        # Dropping it would hide the hole; the caller must be able to see it.
        controls = build_controls(panel, _spec(panel, 900), (*UNITS, "ZZZ.L"))
        assert "ZZZ.L" in controls.index
        assert bool(
            controls.loc["ZZZ.L", "momentum"] != controls.loc["ZZZ.L", "momentum"]
        )

    def test_insufficient_history_raises_rather_than_truncating(
        self, panel: ReturnPanel
    ) -> None:
        # A momentum control silently computed over 40 days instead of 252 is a
        # different variable with the same name.
        with pytest.raises(ControlError, match="momentum needs"):
            build_controls(panel, _spec(panel, 300), UNITS)

    def test_controls_use_only_pre_event_data(self, panel: ReturnPanel) -> None:
        # Corrupt everything from t0 onwards. The controls must not move.
        spec = _spec(panel, 900)
        t0 = spec.timing.t0
        before = build_controls(panel, spec, UNITS)

        corrupted = panel.returns.copy()
        corrupted.loc[corrupted.index >= t0] = 99.0
        after = build_controls(
            ReturnPanel(
                returns=corrupted, market=panel.market, provenance=panel.provenance
            ),
            spec,
            UNITS,
        )
        pd.testing.assert_frame_equal(before, after)

    def test_momentum_skips_the_most_recent_month(self, panel: ReturnPanel) -> None:
        spec = _spec(panel, 900)
        windows = spec.resolve(panel.trading_days)
        days = panel.trading_days
        end = int(days.get_indexer(pd.DatetimeIndex([windows.pre_days[-1]]))[0])
        skipped = days[end - MOMENTUM_SKIP_DAYS : end]

        baseline = build_controls(panel, spec, UNITS)
        bumped = panel.returns.copy()
        bumped.loc[bumped.index.isin(skipped)] += 0.05
        moved = build_controls(
            ReturnPanel(
                returns=bumped, market=panel.market, provenance=panel.provenance
            ),
            spec,
            UNITS,
        )
        # The skipped month must not enter momentum.
        assert moved["momentum"].equals(baseline["momentum"])
        assert MOMENTUM_LOOKBACK_DAYS > MOMENTUM_SKIP_DAYS

    def test_turnover_size_differs_from_the_variance_fallback(
        self, panel: ReturnPanel
    ) -> None:
        spec = _spec(panel, 900)
        fallback = build_controls(panel, spec, UNITS)
        assert bool(fallback["size_is_fallback"].all())

        closes = {unit: pd.Series(500.0, index=panel.trading_days) for unit in UNITS}
        volumes = {
            unit: pd.Series(1_000_000.0, index=panel.trading_days) for unit in UNITS
        }
        real = build_controls(panel, spec, UNITS, closes=closes, volumes=volumes)
        assert not bool(real["size_is_fallback"].any())
        # 500p x 1e6 / 100 = 5,000,000 GBP; log is about 15.4.
        assert real.loc["AAA.L", "size"] == pytest.approx(np.log(5_000_000.0))


class TestBuildCarPanel:
    @staticmethod
    def _exposure(events: tuple[str, ...]) -> pd.DataFrame:
        rows = []
        for event in events:
            for index, unit in enumerate(UNITS):
                rows.append(
                    {
                        "unit_id": unit,
                        "event_id": event,
                        "exposure_continuous": float(index),
                        "exposure_rank": float(index),
                        "exposure_magnitude": float(index) / 10.0,
                        "exposure_signed": float(index) / 10.0,
                    }
                )
        return pd.DataFrame(rows)

    def test_builds_one_row_per_unit_per_event(self, panel: ReturnPanel) -> None:
        specs = [_spec(panel, 900, "e1"), _spec(panel, 1000, "e2")]
        result = build_car_panel(panel, specs, self._exposure(("e1", "e2")))
        assert len(result.frame) == len(UNITS) * 2
        assert result.n_events == 2

    def test_carries_the_columns_the_estimator_requires(
        self, panel: ReturnPanel
    ) -> None:
        specs = [_spec(panel, 900, "e1")]
        result = build_car_panel(panel, specs, self._exposure(("e1",)))
        required = {"unit_id", "event_id", "car", "exposure_continuous"}
        assert required <= set(result.frame.columns)
        assert set(DEFAULT_CONTROLS) <= set(result.frame.columns)

    def test_a_pair_without_an_exposure_row_is_dropped_not_zeroed(
        self, panel: ReturnPanel
    ) -> None:
        # Assuming a zero is a curation decision; a bookkeeping module must not
        # make it.
        exposure = self._exposure(("e1",))
        exposure = exposure.loc[exposure["unit_id"] != "CCC.L"]
        result = build_car_panel(panel, [_spec(panel, 900, "e1")], exposure)
        assert "CCC.L" not in set(result.frame["unit_id"])
        assert "no exposure row" in result.dropped[("CCC.L", "e1")]

    def test_an_event_whose_window_does_not_fit_is_recorded_not_silently_lost(
        self, panel: ReturnPanel
    ) -> None:
        specs = [_spec(panel, 900, "e1"), _spec(panel, 300, "e2")]
        result = build_car_panel(panel, specs, self._exposure(("e1", "e2")))
        assert result.n_events == 1
        assert any(key[1] == "e2" for key in result.dropped)

    def test_cluster_ids_are_used_when_supplied(self, panel: ReturnPanel) -> None:
        specs = [_spec(panel, 900, "e1"), _spec(panel, 1000, "e2")]
        result = build_car_panel(
            panel,
            specs,
            self._exposure(("e1", "e2")),
            cluster_ids={"e1": "grp", "e2": "grp"},
        )
        assert result.n_clusters == 1
        assert result.n_events == 2

    def test_missing_grouping_is_flagged_because_it_understates_the_se(
        self, panel: ReturnPanel
    ) -> None:
        specs = [_spec(panel, 900, "e1")]
        result = build_car_panel(panel, specs, self._exposure(("e1",)))
        assert any("over-states independence" in note for note in result.notes)

    def test_unavailable_units_are_dropped_at_the_listing_boundary(
        self, panel: ReturnPanel
    ) -> None:
        class _Closed:
            def available_on(self, _moment: pd.Timestamp) -> bool:
                return False

        result = build_car_panel(
            panel,
            [_spec(panel, 900, "e1")],
            self._exposure(("e1",)),
            availability={"AAA.L": _Closed()},
        )
        assert "AAA.L" not in set(result.frame["unit_id"])
        assert "not available" in result.dropped[("AAA.L", "e1")]

    def test_a_backwards_window_raises(self, panel: ReturnPanel) -> None:
        with pytest.raises(CARPanelError, match="runs backwards"):
            build_car_panel(
                panel, [_spec(panel, 900)], self._exposure(("e1",)), window=(5, 0)
            )

    def test_exposure_frame_without_any_exposure_column_raises(
        self, panel: ReturnPanel
    ) -> None:
        bare = pd.DataFrame({"unit_id": ["AAA.L"], "event_id": ["e1"]})
        with pytest.raises(CARPanelError, match="none of the expected exposure"):
            build_car_panel(panel, [_spec(panel, 900)], bare)


class TestCheckIdentified:
    """The guard that names the cause before the estimator spends a run."""

    @staticmethod
    def _panel(values: list[float]) -> CARPanel:
        frame = pd.DataFrame(
            {
                "unit_id": [f"U{i}" for i in range(len(values))],
                "event_id": ["e1"] * len(values),
                "cluster_id": ["e1"] * len(values),
                "car": [0.01] * len(values),
                "exposure_continuous": values,
            }
        )
        return CARPanel(frame=frame, dropped={}, window=(0, 1))

    def test_passes_when_an_event_has_within_event_variation(self) -> None:
        self._panel([0.0, 1.0, 2.0]).check_identified("exposure_continuous")

    def test_raises_when_every_firm_scores_the_same(self) -> None:
        with pytest.raises(CARPanelError, match="within-event variation"):
            self._panel([0.0, 0.0, 0.0]).check_identified("exposure_continuous")

    def test_raises_on_an_empty_panel(self) -> None:
        empty = CARPanel(frame=pd.DataFrame(), dropped={}, window=(0, 1))
        with pytest.raises(CARPanelError, match="empty"):
            empty.check_identified("exposure_continuous")

    def test_message_names_curation_rather_than_arithmetic(self) -> None:
        # The distinction matters: this is not a numerical failure to work
        # around, it is missing data.
        with pytest.raises(CARPanelError, match="curation failure"):
            self._panel([1.0, 1.0]).check_identified("exposure_continuous")
