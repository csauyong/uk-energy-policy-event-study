"""Price panel: adjustment modes, clock alignment, screening, calendar."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from policy_event_study.data.prices import (
    Adjustment,
    ReturnPanel,
    build_panel,
    compute_returns,
)
from policy_event_study.data.universe import load_universe


def cell(frame: pd.DataFrame, row: pd.Timestamp, column: str) -> float:
    """Read one float from a frame.

    pandas-stubs types `.loc[row, col]` as a wide scalar union, so a bare
    `float(...)` on it fails strict mypy. Narrowing once here beats an ignore
    comment at every call site.
    """
    return float(
        frame.to_numpy(dtype=float)[
            frame.index.get_loc(row), frame.columns.get_loc(column)
        ]
    )


def raw_frame(
    n_days: int = 400,
    *,
    start: str = "2022-01-03",
    price: float = 100.0,
    volume: float = 5_000_000.0,
    seed: int = 3,
    drop_dates: tuple[str, ...] = (),
) -> pd.DataFrame:
    """A synthetic yfinance-shaped frame: raw closes plus a dated action schedule."""
    rng = np.random.default_rng(seed)
    index = pd.DatetimeIndex(pd.bdate_range(start=start, periods=n_days, tz="UTC"))
    if drop_dates:
        index = index.drop([pd.Timestamp(date, tz="UTC") for date in drop_dates])
    closes = price * np.exp(np.cumsum(rng.normal(0.0002, 0.01, size=len(index))))
    return pd.DataFrame(
        {
            "close": closes,
            "close_auto_adj": closes,
            "volume": np.full(len(index), volume),
            "dividend": np.zeros(len(index)),
            "split_ratio": np.zeros(len(index)),
        },
        index=index,
    )


def universe_frames(**overrides: pd.DataFrame) -> dict[str, pd.DataFrame]:
    tickers = (
        "TRT1.L",
        "TRT2.L",
        "TRT3.L",
        "MERGED.L",
        "DON1.L",
        "DON2.L",
        "USDON",
        "EUDON.PA",
        "DKDON.CO",
        "FLIP.L",
        "BANNED.L",
        "^IDX",
    )
    frames = {ticker: raw_frame(seed=index) for index, ticker in enumerate(tickers)}
    frames.update(overrides)
    return frames


# -- adjustment ------------------------------------------------------------


def test_adjustment_is_a_required_argument() -> None:
    """No default. The caller states which mode, and it reaches every table."""
    universe = load_universe(Path("tests/data/test_universe.yaml"))
    with pytest.raises(TypeError):
        build_panel(universe_frames(), universe, vintage="test")  # type: ignore[call-arg]


def test_point_in_time_split_uses_only_the_current_ratio() -> None:
    """A 2-for-1 split leaves a ~0% return, not -50%, and touches nothing earlier."""
    frame = raw_frame(n_days=50)
    split_position = 30
    ex_date = frame.index[split_position]
    frame.loc[ex_date, "split_ratio"] = 2.0
    # Quoted price halves on the ex-date, as it does in reality.
    frame.loc[ex_date:, "close"] /= 2.0

    returns = compute_returns(frame, Adjustment.POINT_IN_TIME)
    assert abs(float(returns.iloc[split_position])) < 0.05

    unadjusted = compute_returns(frame, Adjustment.UNADJUSTED)
    assert float(unadjusted.iloc[split_position]) < -0.4  # the fake -50%

    # And the returns before the split are identical under both, because a
    # forward-only adjustment cannot reach backwards.
    pd.testing.assert_series_equal(
        returns.iloc[1:split_position],
        unadjusted.iloc[1:split_position],
        check_names=False,
    )


@pytest.mark.pointintime
def test_retroactive_adjustment_moves_levels_but_not_consecutive_returns() -> None:
    """The precise scope of the `CLAUDE.md` §2.4 exposure, pinned down.

    Back-adjust a series for a split dated at the *end* of the sample. Every
    price before the ex-date is rewritten -- that is the violation
    docs/data_inventory.md §7 warns about. But consecutive *returns* are
    unchanged, because the retroactive factor appears in both numerator and
    denominator and cancels.

    This is why `config/universe.yaml` `notes.matching_variable` banning price
    levels as the matching variable is load-bearing rather than stylistic: the
    ban is what keeps the contamination out of the estimates.
    """
    base = raw_frame(n_days=200)
    early = slice(1, 100)

    # Yahoo-style back-adjustment for a 3-for-1 split at position 190.
    back_adjusted = base["close"].copy()
    back_adjusted.iloc[:190] /= 3.0

    unadjusted_levels = base["close"].iloc[early]
    adjusted_levels = back_adjusted.iloc[early]
    assert not np.allclose(unadjusted_levels, adjusted_levels), (
        "the back-adjustment must move pre-split levels, or the fixture is wrong"
    )

    pd.testing.assert_series_equal(
        unadjusted_levels.pct_change(),
        adjusted_levels.pct_change(),
        check_names=False,
    )


def test_auto_adjust_requires_the_fetched_column() -> None:
    """The mode differences Yahoo's series; it never reconstructs one."""
    frame = raw_frame(n_days=20).drop(columns=["close_auto_adj"])
    with pytest.raises(KeyError, match="close_auto_adj"):
        compute_returns(frame, Adjustment.AUTO_ADJUST)


def test_auto_adjust_differences_the_fetched_series() -> None:
    frame = raw_frame(n_days=20)
    frame["close_auto_adj"] = frame["close"] * 0.5  # any monotone rescaling
    pd.testing.assert_series_equal(
        compute_returns(frame, Adjustment.AUTO_ADJUST),
        frame["close_auto_adj"].pct_change(),
        check_names=False,
    )


def test_dividend_enters_the_return_on_its_ex_date() -> None:
    frame = raw_frame(n_days=40)
    position = 20
    frame.loc[frame.index[position], "dividend"] = 5.0
    with_div = compute_returns(frame, Adjustment.POINT_IN_TIME)
    without = compute_returns(frame.assign(dividend=0.0), Adjustment.POINT_IN_TIME)
    expected = 5.0 / float(frame["close"].to_numpy()[position - 1])
    assert float(with_div.iloc[position] - without.iloc[position]) == pytest.approx(
        expected, rel=1e-9
    )


def test_unadjusted_is_refused_for_estimation() -> None:
    universe = load_universe(Path("tests/data/test_universe.yaml"))
    with pytest.raises(ValueError, match="allow_unadjusted_estimation"):
        build_panel(
            universe_frames(),
            universe,
            adjustment=Adjustment.UNADJUSTED,
            vintage="test",
        )


# -- alignment, screening, calendar ---------------------------------------


def test_late_market_is_lagged_and_recorded() -> None:
    universe = load_universe(Path("tests/data/test_universe.yaml"))
    panel = build_panel(
        universe_frames(),
        universe,
        adjustment=Adjustment.POINT_IN_TIME,
        vintage="test",
    )
    assert panel.provenance.lagged_tickers == ("USDON",)
    assert panel.provenance.early_close_tickers == ("DKDON.CO",)
    assert any("CLOCK ALIGNMENT" in note for note in panel.provenance.caveats())


def test_lag_actually_shifts_the_series() -> None:
    universe = load_universe(Path("tests/data/test_universe.yaml"))
    frames = universe_frames()
    panel = build_panel(
        frames, universe, adjustment=Adjustment.POINT_IN_TIME, vintage="test"
    )
    unlagged = compute_returns(frames["USDON"], Adjustment.POINT_IN_TIME)
    day = panel.trading_days[50]
    previous = unlagged.index[
        unlagged.index.get_indexer(pd.DatetimeIndex([day]))[0] - 1
    ]
    assert cell(panel.returns, day, "USDON") == pytest.approx(
        float(unlagged.to_numpy()[unlagged.index.get_loc(previous)])
    )


def test_illiquid_donor_is_screened_out_with_a_reason() -> None:
    universe = load_universe(Path("tests/data/test_universe.yaml"))
    frames = universe_frames()
    frames["DON2.L"] = raw_frame(volume=1.0, price=0.5)
    panel = build_panel(
        frames, universe, adjustment=Adjustment.POINT_IN_TIME, vintage="test"
    )
    assert "DON2.L" not in panel.returns.columns
    assert "DON2.L" in panel.provenance.screened_out
    assert "turnover" in panel.provenance.screened_out["DON2.L"]


def test_missing_donor_day_becomes_nan_not_a_fabricated_zero() -> None:
    """A missing day is NaN, never forward-filled into a 0% return that never happened.

    The panel spine is the LSE calendar and NaNs are preserved; completeness is
    resolved per event window, because units with availability bounds never
    overlap and a panel-wide intersection would be empty.
    """
    universe = load_universe(Path("tests/data/test_universe.yaml"))
    frames = universe_frames()
    frames["USDON"] = raw_frame(seed=5, drop_dates=("2022-07-04", "2022-11-24"))
    panel = build_panel(
        frames, universe, adjustment=Adjustment.POINT_IN_TIME, vintage="test"
    )
    assert pd.Timestamp("2022-07-04", tz="UTC") in panel.trading_days
    assert (
        panel.returns.loc[pd.Timestamp("2022-07-04", tz="UTC"), "USDON"]
        != panel.returns.loc[pd.Timestamp("2022-07-04", tz="UTC"), "USDON"]
    )


def test_no_fx_conversion_ever_happens() -> None:
    """`notes.fx`: donor returns stay in local currency, by construction."""
    universe = load_universe(Path("tests/data/test_universe.yaml"))
    frames = universe_frames()
    panel = build_panel(
        frames, universe, adjustment=Adjustment.POINT_IN_TIME, vintage="test"
    )
    assert panel.provenance.fx_converted is False
    direct = compute_returns(frames["EUDON.PA"], Adjustment.POINT_IN_TIME)
    day = panel.trading_days[100]
    assert cell(panel.returns, day, "EUDON.PA") == pytest.approx(
        float(direct.to_numpy()[direct.index.get_loc(day)])
    )


def test_survivorship_caveat_is_carried() -> None:
    universe = load_universe(Path("tests/data/test_universe.yaml"))
    panel = build_panel(
        universe_frames(),
        universe,
        adjustment=Adjustment.POINT_IN_TIME,
        vintage="test",
    )
    assert any("SURVIVORSHIP" in note for note in panel.provenance.caveats())


def test_outcome_is_cumulative_and_starts_at_the_window(
    null_panel: ReturnPanel,
) -> None:
    outcome = null_panel.window(
        null_panel.trading_days[10], null_panel.trading_days[60]
    ).outcome(["TREATED"])
    assert float(outcome.to_numpy()[0, 0]) == pytest.approx(
        cell(null_panel.returns, null_panel.trading_days[10], "TREATED")
    )
    assert len(outcome) == 51


def test_equal_weighted_portfolio(null_panel: ReturnPanel) -> None:
    series = null_panel.equal_weighted(["DONOR00", "DONOR01"], "PORT")
    expected = null_panel.returns[["DONOR00", "DONOR01"]].mean(axis=1)
    pd.testing.assert_series_equal(series, expected, check_names=False)
