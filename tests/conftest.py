"""Shared fixtures.

Every fixture here is synthetic and deterministic. No test in this suite
touches the network: `fetch_prices` is the only function that does, and it is
deliberately separated from `build_panel` so that all the point-in-time logic
is exercised offline.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from policy_event_study.data.prices import Adjustment, PanelProvenance, ReturnPanel
from policy_event_study.data.universe import Alignment, Outcome
from policy_event_study.estimators.base import EventSpec
from policy_event_study.events.schema import (
    AnticipationRisk,
    EventDayConvention,
    EventTiming,
    ExpectedDirection,
)

TESTS_DIR = Path(__file__).parent


def make_trading_days(n_days: int, start: str = "2019-01-02") -> pd.DatetimeIndex:
    """Business-day calendar in UTC, standing in for a panel's trading days."""
    return pd.DatetimeIndex(
        pd.bdate_range(start=start, periods=n_days, tz="UTC"), name="date"
    )


def make_panel(
    *,
    seed: int = 7,
    n_donors: int = 15,
    n_days: int = 420,
    effect: float = 0.0,
    effect_from: int | None = None,
    effect_length: int = 21,
    treated_loadings: tuple[float, ...] = (0.5, 0.3, 0.2),
    idiosyncratic_sd: float = 0.002,
) -> ReturnPanel:
    """Build a synthetic return panel with a known, injectable treatment effect.

    The treated unit is a convex combination of the first few donors plus
    idiosyncratic noise, so a synthetic control *should* be able to reconstruct
    it -- which makes recovery of `effect` a meaningful test rather than a
    test of whether the optimiser runs.

    Parameters
    ----------
    effect
        Total cumulative abnormal return injected into the treated unit,
        spread evenly over `effect_length` days from `effect_from`.
    """
    rng = np.random.default_rng(seed)
    days = make_trading_days(n_days)

    market = rng.normal(0.0003, 0.010, size=n_days)
    betas = rng.uniform(0.6, 1.4, size=n_donors)
    donor_names = [f"DONOR{index:02d}" for index in range(n_donors)]
    donor_returns = np.outer(market, betas) + rng.normal(
        0.0, 0.008, size=(n_days, n_donors)
    )

    loadings = np.zeros(n_donors)
    loadings[: len(treated_loadings)] = treated_loadings
    treated = donor_returns @ loadings + rng.normal(0.0, idiosyncratic_sd, size=n_days)

    if effect != 0.0:
        start = effect_from if effect_from is not None else n_days - 40
        treated[start : start + effect_length] += effect / effect_length

    frame = pd.DataFrame(donor_returns, index=days, columns=donor_names)
    frame.insert(0, "TREATED", treated)

    provenance = PanelProvenance(
        vintage="test",
        adjustment=Adjustment.POINT_IN_TIME,
        alignment=Alignment.LAG_LATE_MARKETS,
        universe_path="<synthetic>",
        survivorship_biased=False,
    )
    return ReturnPanel(
        returns=frame,
        market=pd.Series(market, index=days, name="^MKT"),
        provenance=provenance,
        outcome_kind=Outcome.CUMULATIVE_SIMPLE_RETURNS,
    )


def make_spec(
    panel: ReturnPanel,
    *,
    t0_index: int = -40,
    estimation_length: int = 200,
    gap: int = 10,
    post_horizon: int = 20,
    expected_direction: ExpectedDirection = ExpectedDirection.AMBIGUOUS,
    anticipation_risk: AnticipationRisk = AnticipationRisk.LOW,
) -> EventSpec:
    """Build an `EventSpec` anchored on a positional index into the panel."""
    days = panel.trading_days
    t0 = pd.Timestamp(days[t0_index])
    timing = EventTiming(
        announcement_ts_utc=t0 - pd.Timedelta(hours=16),
        time_known=True,
        straddling_day=None,
        first_clean_day=t0,
        t0=t0,
        convention=EventDayConvention.FIRST_CLEAN_CLOSE,
    )
    return EventSpec(
        event_id="TEST-EVENT",
        timing=timing,
        donors=tuple(column for column in panel.returns.columns if column != "TREATED"),
        estimation_length=estimation_length,
        gap=gap,
        post_horizon=post_horizon,
        anticipation_risk=anticipation_risk,
        expected_direction=expected_direction,
    )


@pytest.fixture
def null_panel() -> ReturnPanel:
    """Panel with no treatment effect."""
    return make_panel(effect=0.0)


@pytest.fixture
def effect_panel() -> ReturnPanel:
    """Panel with a +8% cumulative abnormal return injected from day -40."""
    return make_panel(effect=0.08, effect_from=380, effect_length=21)


@pytest.fixture
def null_spec(null_panel: ReturnPanel) -> EventSpec:
    """Spec matching `null_panel`."""
    return make_spec(null_panel)


@pytest.fixture
def effect_spec(effect_panel: ReturnPanel) -> EventSpec:
    """Spec whose t0 coincides with the injected effect's start."""
    return make_spec(effect_panel, t0_index=380)


@pytest.fixture
def test_universe_path() -> Path:
    """Path to the miniature universe config used by the config tests."""
    return TESTS_DIR / "data" / "test_universe.yaml"
