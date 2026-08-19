"""Firm-level controls for the dose-response regression, from prices alone.

WHY THERE ARE THREE CONTROLS AND NOT FOUR
-----------------------------------------
`DEFAULT_CONTROLS` used to name four: `size`, `book_to_market`, `momentum`
and `pre_event_vol`. Three of those are functions of a return series the
project already has. `book_to_market` is not: it needs point-in-time book
values, which means a fundamentals vendor, a vintage discipline for restated
accounts, and a mapping from ~250 listings to their filings.

**`book_to_market` is dropped.** The reason is cost, and the cost is not
marginal -- acquiring point-in-time book values was the single largest
remaining workstream in the project, larger than everything else outstanding
combined, and it sat between a finished pipeline and any result at all.

The caveat that replaces it has a direction, which is the standard this
project holds itself to (`CLAUDE.md` section 6):

    Exposure to energy-efficiency policy is concentrated in building-products
    and housebuilding names, which trade at higher book-to-market ratios than
    the market. Value stocks earn a positive average premium. So if exposure
    correlates with a value tilt, part of what beta measures is that premium
    rather than the policy channel, and beta is biased **away from zero**.

    **The estimate is therefore an upper bound on the policy effect.** A null
    result is strengthened by this -- if beta is indistinguishable from zero
    even with the value premium loaded onto it, the policy channel is smaller
    still. A positive result is weakened by it and must be read as a ceiling.

`pre_event_vol` does part of the job by proxy: value and distress both raise
realised volatility, so a firm whose exposure comes with a value tilt is
partly controlled for through its riskiness. Partly. This is a mitigation,
not a substitute, and it is not claimed as one.

WHY SIZE IS TURNOVER AND NOT MARKET CAP
---------------------------------------
Market capitalisation needs shares outstanding, and every free source serves
**today's** share count. Applying it to a 2015 price manufactures a market cap
that never existed -- and does so with a look-ahead, because share counts move
on the buybacks and issues that follow the events being studied.

Average daily turnover in GBP is computed from `close * volume`, both of which
are point-in-time by construction, and it correlates with market cap strongly
enough to absorb a size tilt. It is a different variable wearing the same hat,
and it is named `size` because that is the role it plays in the regression.

EVERY CONTROL IS MEASURED BEFORE ITS EVENT
------------------------------------------
All three are computed over a window that closes `gap` trading days before
`t0`, using the same estimation window the market model fits on. A control
measured over the event window would be contaminated by the event, and a
control measured over the full sample would be contaminated by everything.
:func:`build_controls` takes the resolved windows rather than dates so this
cannot be got wrong by a caller.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import numpy as np
import pandas as pd

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Mapping, Sequence

    from policy_event_study.data.prices import ReturnPanel
    from policy_event_study.estimators.base import EventSpec

#: Trading days per year, for annualising the volatility control.
TRADING_DAYS_PER_YEAR: Final[int] = 252

#: Momentum skips the most recent month, as the asset-pricing literature does,
#: because the last month is dominated by short-horizon reversal rather than
#: by the medium-horizon trend the control is meant to absorb.
MOMENTUM_SKIP_DAYS: Final[int] = 21

#: Momentum is measured over the twelve months before the skip.
MOMENTUM_LOOKBACK_DAYS: Final[int] = 252


class ControlError(ValueError):
    """Raised when a control cannot be computed from the data available."""


def _log_turnover(close: pd.Series, volume: pd.Series, *, pence_quoted: bool) -> float:
    """Mean daily turnover over the window, logged.

    Yahoo quotes London listings in pence. Dividing by 100 there and not
    elsewhere is the whole of the currency handling, and getting it wrong
    shifts every London name by log(100) = 4.6 relative to every overseas one
    -- which would make `size` a UK-listing dummy rather than a size control.
    """
    turnover = (close * volume).mean()
    if not np.isfinite(turnover) or turnover <= 0:
        return float("nan")
    if pence_quoted:
        turnover = turnover / 100.0
    return float(np.log(turnover))


def build_controls(
    panel: ReturnPanel,
    spec: EventSpec,
    units: Sequence[str],
    *,
    closes: Mapping[str, pd.Series] | None = None,
    volumes: Mapping[str, pd.Series] | None = None,
    pence_quoted: Mapping[str, bool] | None = None,
) -> pd.DataFrame:
    """Compute `size`, `momentum` and `pre_event_vol` for one event.

    Parameters
    ----------
    panel
        Aligned return panel. Supplies the calendar and the return series.
    spec
        The event. Its resolved windows fix the measurement period, which ends
        `spec.gap` trading days before `t0`.
    units
        Units to compute controls for. A unit absent from the panel gets a row
        of NaN rather than being dropped, so the caller can see the hole.
    closes, volumes
        Raw close and volume series per unit, for the turnover-based `size`.
        When absent, `size` falls back to the log of realised return variance,
        which is a much weaker proxy -- the fallback exists so tests can run on
        a synthetic panel without price levels, and it warns by returning a
        frame whose `size_is_fallback` column is True.
    pence_quoted
        Unit to whether its close is quoted in pence. Defaults to True for
        `.L` suffixed tickers and False otherwise.

    Returns
    -------
    pd.DataFrame
        Indexed by `unit_id`, with columns `size`, `momentum`, `pre_event_vol`
        and `size_is_fallback`.

    Raises
    ------
    ControlError
        If the estimation window is too short to measure momentum over. This
        raises rather than truncating, because a momentum control silently
        computed over 40 days instead of 252 is a different variable with the
        same name.
    """
    windows = spec.resolve(panel.trading_days)
    days = panel.trading_days
    measurement_end = windows.pre_days[-1]
    end_index = int(days.get_indexer(pd.DatetimeIndex([measurement_end]))[0])

    momentum_end = end_index - MOMENTUM_SKIP_DAYS
    momentum_start = momentum_end - MOMENTUM_LOOKBACK_DAYS
    if momentum_start < 0:
        msg = (
            f"event {spec.event_id!r} has only {end_index} trading days of "
            f"history before its estimation window closes, but momentum needs "
            f"{MOMENTUM_LOOKBACK_DAYS + MOMENTUM_SKIP_DAYS}. Truncating would "
            "silently redefine the control"
        )
        raise ControlError(msg)

    momentum_days = days[momentum_start:momentum_end]
    volatility_days = windows.pre_days
    fallback = closes is None or volumes is None

    rows: list[dict[str, object]] = []
    for unit in units:
        if unit not in panel.returns.columns:
            rows.append(
                {
                    "unit_id": unit,
                    "size": float("nan"),
                    "momentum": float("nan"),
                    "pre_event_vol": float("nan"),
                    "size_is_fallback": fallback,
                }
            )
            continue

        series = panel.returns[unit]
        window_returns = series.reindex(momentum_days).dropna()
        momentum = (
            float(np.expm1(np.log1p(window_returns).sum()))
            if len(window_returns) > 0
            else float("nan")
        )

        pre_returns = series.reindex(volatility_days).dropna()
        pre_event_vol = (
            float(pre_returns.std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR))
            if len(pre_returns) > 1
            else float("nan")
        )

        if fallback:
            size = (
                float(np.log(pre_returns.var(ddof=1)))
                if len(pre_returns) > 1 and pre_returns.var(ddof=1) > 0
                else float("nan")
            )
        else:
            assert closes is not None and volumes is not None
            close = closes.get(unit)
            volume = volumes.get(unit)
            if close is None or volume is None:
                size = float("nan")
            else:
                in_pence = (
                    pence_quoted.get(unit, unit.endswith(".L"))
                    if pence_quoted is not None
                    else unit.endswith(".L")
                )
                size = _log_turnover(
                    close.reindex(volatility_days).dropna(),
                    volume.reindex(volatility_days).dropna(),
                    pence_quoted=in_pence,
                )

        rows.append(
            {
                "unit_id": unit,
                "size": size,
                "momentum": momentum,
                "pre_event_vol": pre_event_vol,
                "size_is_fallback": fallback,
            }
        )

    return pd.DataFrame(rows).set_index("unit_id")
