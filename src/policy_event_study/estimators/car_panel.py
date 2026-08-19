"""Stack per-unit CARs into the firm x event panel the dose-response fits on.

WHAT WAS MISSING
----------------
`market_model.car_by_window` computes CARs for **one** unit at **one** event.
`estimate_dose_response` wants one row per unit per event, carrying `car`, an
exposure column, the controls and a cluster id. Nothing joined the two, which
is why the estimator had never been run on real data despite being finished
and tested.

This module is that join, and it is deliberately thin. Every hard decision --
which window, which adjustment, how events group into clusters, how exposure
is scored -- was made elsewhere and is passed in. What is left is bookkeeping,
and the risk in bookkeeping is silent loss.

THE THREE WAYS A ROW CAN VANISH, AND WHY EACH IS COUNTED
--------------------------------------------------------
1. **The event window does not fit.** `EventSpec.resolve` raises `WindowError`
   when a listing lacks the estimation history before `t0` or the post-window
   after it. For an event in 2015 and a firm that listed in 2021, that is
   correct and expected.
2. **The unit is not available on the date.** `Listing.available_on` closes
   the Barratt pre/post-merger boundary. A row that crosses it would splice
   two companies.
3. **Exposure is missing.** The unit x event pair has no exposure row.

All three are recorded on `CARPanel.dropped` with a reason, and
:meth:`CARPanel.attrition_table` renders the counts. A panel that quietly
shrank from 24 events to 9 while reporting "24 events" is the failure mode
this guards against, and the count is carried into `reports/results.md`
rather than being available only to whoever ran the code.

WINDOW CHOICE IS THE CALLER'S, AND IT IS ONE CHOICE
---------------------------------------------------
`reports/dose_response.md` section 2.5 found short windows dominate: [0,1]
costs about 40% more MDE than [0,0] and [0,20] roughly four times. The default
here is **(0, 1)** -- one day is too tight against a timestamp that is
sometimes only known to the day, and two trading days still sits near the
efficient end of that curve.

Running several windows and reporting the best is the multiple-comparisons
failure `reports/decision_log.md` counts specifications to prevent. So this
builder takes exactly one window. Comparing windows is a separate, declared
robustness exercise, not something a default makes easy to do by accident.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, Protocol, cast

import numpy as np
import pandas as pd

from policy_event_study.estimators.base import WindowError
from policy_event_study.estimators.controls import ControlError, build_controls
from policy_event_study.estimators.market_model import MarketModelEstimator

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Mapping, Sequence

    from policy_event_study.data.prices import ReturnPanel
    from policy_event_study.estimators.base import EventSpec

#: Default event window, in trading days relative to t0. See the module
#: docstring for why this is a single window and not a menu.
DEFAULT_WINDOW: Final[tuple[int, int]] = (0, 1)


class Availability(Protocol):
    """Anything that can say whether a unit exists on a date.

    Structural rather than nominal so a test can pass a stub without importing
    the universe machinery. `data.universe.Listing` satisfies it.
    """

    def available_on(self, moment: pd.Timestamp) -> bool:
        """Report whether the unit exists on the given date."""
        ...


class CARPanelError(ValueError):
    """Raised when the stacked panel cannot be built or is not usable."""


@dataclass(frozen=True)
class CARPanel:
    """One row per unit x event, ready for `estimate_dose_response`.

    Attributes
    ----------
    frame
        Columns `unit_id`, `event_id`, `cluster_id`, `car`, the exposure
        columns and the controls.
    dropped
        `(unit_id, event_id)` to the reason that pair produced no row.
    window
        The event window every CAR in `frame` was computed over.
    """

    frame: pd.DataFrame
    dropped: Mapping[tuple[str, str], str]
    window: tuple[int, int]
    events_requested: int = 0
    units_requested: int = 0
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def n_events(self) -> int:
        """Events that contributed at least one row."""
        return int(self.frame["event_id"].nunique()) if len(self.frame) else 0

    @property
    def n_clusters(self) -> int:
        """Event groups that contributed at least one row.

        This, not `n_events`, is what the bootstrap p-value floor is computed
        from. Two announcements a fortnight apart share trading days and are
        not two independent draws.
        """
        if not len(self.frame) or "cluster_id" not in self.frame.columns:
            return 0
        return int(self.frame["cluster_id"].nunique())

    def attrition_table(self) -> pd.DataFrame:
        """Count dropped pairs by reason, most common first."""
        if not self.dropped:
            return pd.DataFrame(columns=["reason", "pairs"])
        tally: dict[str, int] = {}
        for reason in self.dropped.values():
            key = reason.split(":")[0]
            tally[key] = tally.get(key, 0) + 1
        return pd.DataFrame(
            {"reason": list(tally), "pairs": [tally[key] for key in tally]}
        ).sort_values("pairs", ascending=False, ignore_index=True)

    def check_identified(self, exposure_column: str) -> None:
        """Fail loudly if the panel cannot identify a dose-response.

        Duplicates the estimator's own guard on purpose. The estimator raises
        after a caller has already spent the run; this raises while the panel
        is being built, where the message can name the cause.

        Raises
        ------
        CARPanelError
            If no event has within-event variation in exposure.
        """
        if not len(self.frame):
            msg = "the stacked panel is empty; every unit x event pair dropped"
            raise CARPanelError(msg)
        if exposure_column not in self.frame.columns:
            msg = f"panel has no {exposure_column!r} column"
            raise CARPanelError(msg)
        spread = self.frame.groupby("event_id")[exposure_column].std(ddof=1)
        live = spread.fillna(0.0)
        if float(live.max()) <= 0:
            msg = (
                f"no event has any within-event variation in "
                f"{exposure_column!r}. Every firm scores the same, so beta is "
                "collinear with the event fixed effects. This is an exposure "
                "curation failure, not a numerical one"
            )
            raise CARPanelError(msg)


def build_car_panel(
    panel: ReturnPanel,
    specs: Sequence[EventSpec],
    exposure: pd.DataFrame,
    *,
    window: tuple[int, int] = DEFAULT_WINDOW,
    cluster_ids: Mapping[str, str] | None = None,
    closes: Mapping[str, pd.Series] | None = None,
    volumes: Mapping[str, pd.Series] | None = None,
    availability: Mapping[str, Availability] | None = None,
    estimator: MarketModelEstimator | None = None,
) -> CARPanel:
    """Stack market-model CARs across every unit and event into one frame.

    Parameters
    ----------
    panel
        Aligned return panel from `prices.build_panel`.
    specs
        One `EventSpec` per event in the frozen dictionary.
    exposure
        The exposure panel from `exposure.build.build_exposure_panel`, with
        `unit_id`, `event_id` and the exposure columns. Units absent from it
        for a given event are treated as **structurally missing**, not as
        zeros -- assuming a zero is a curation decision and does not belong in
        a bookkeeping module.
    window
        `(start, end)` in trading days relative to `t0`.
    cluster_ids
        Event id to group id, from `events.grouping.assign_event_groups`.
        Falls back to one cluster per event, which over-states independence
        and so **under-states** the standard error. Passing real groups is
        strongly preferred and the fallback is recorded in `CARPanel.notes`.
    closes, volumes
        Raw price levels for the turnover-based `size` control.
    availability
        Unit id to a `Listing`-like object with an `available_on` method,
        closing merger boundaries. Units absent from the mapping are assumed
        always available.
    estimator
        Market model. Defaults to a plain OLS market model.

    Returns
    -------
    CARPanel
    """
    engine = estimator if estimator is not None else MarketModelEstimator()
    start, end = window
    if start > end:
        msg = f"window {window} runs backwards"
        raise CARPanelError(msg)

    exposure_columns = [
        column
        for column in (
            "exposure_continuous",
            "exposure_rank",
            "exposure_magnitude",
            "exposure_signed",
        )
        if column in exposure.columns
    ]
    if not exposure_columns:
        msg = (
            "exposure frame carries none of the expected exposure columns; "
            "expected at least one of exposure_continuous, exposure_rank, "
            "exposure_magnitude, exposure_signed"
        )
        raise CARPanelError(msg)

    # A plain dict rather than a MultiIndex `.loc`. Two reasons: `.loc` on a
    # MultiIndex returns a Series for a unique key and a DataFrame for a
    # duplicated one, which is a silent widening waiting to happen; and the
    # repeated lookups are the hot loop here.
    lookup: dict[tuple[str, str], dict[str, float]] = {}
    for record in exposure[["unit_id", "event_id", *exposure_columns]].to_dict(
        orient="records"
    ):
        pair = (str(record["unit_id"]), str(record["event_id"]))
        lookup.setdefault(
            pair, {column: float(record[column]) for column in exposure_columns}
        )
    units = tuple(str(column) for column in panel.returns.columns)

    rows: list[dict[str, object]] = []
    dropped: dict[tuple[str, str], str] = {}
    notes: list[str] = []
    if cluster_ids is None:
        notes.append(
            "no event grouping supplied; each event was treated as its own "
            "cluster, which over-states independence and under-states se(beta)"
        )

    for spec in specs:
        try:
            windows = spec.resolve(panel.trading_days)
        except WindowError as exc:
            for unit in units:
                dropped[(unit, spec.event_id)] = f"window does not fit: {exc}"
            continue

        try:
            controls = build_controls(
                panel, spec, units, closes=closes, volumes=volumes
            )
        except ControlError as exc:
            for unit in units:
                dropped[(unit, spec.event_id)] = f"controls unavailable: {exc}"
            continue
        control_lookup = cast(
            "dict[str, dict[str, float]]",
            controls[["size", "momentum", "pre_event_vol"]].to_dict(orient="index"),
        )

        days = panel.trading_days
        origin = int(days.get_indexer(pd.DatetimeIndex([windows.t0]))[0])
        first, last = origin + start, origin + end
        if first < 1 or last >= len(days):
            for unit in units:
                dropped[(unit, spec.event_id)] = (
                    f"window ({start:+d},{end:+d}) falls outside the calendar"
                )
            continue

        cluster = (
            cluster_ids.get(spec.event_id, spec.event_id)
            if cluster_ids is not None
            else spec.event_id
        )

        for unit in units:
            key = (unit, spec.event_id)

            listing = availability.get(unit) if availability is not None else None
            if listing is not None and not listing.available_on(windows.t0):
                dropped[key] = (
                    "unit not available on the event date: outside its "
                    "listing window, so a row here would splice two firms"
                )
                continue

            exposures = lookup.get(key)
            if exposures is None:
                dropped[key] = (
                    "no exposure row: the unit x event pair was never scored, "
                    "and a zero here would be an assumption not a measurement"
                )
                continue

            try:
                estimate = engine.estimate(panel, spec, unit)
            except (KeyError, ValueError, np.linalg.LinAlgError) as exc:
                dropped[key] = f"market model failed: {exc}"
                continue

            segment = estimate.gap.reindex(days[first - 1 : last + 1])
            if segment.isna().any():
                dropped[key] = "abnormal return series has gaps inside the event window"
                continue

            row: dict[str, object] = {
                "unit_id": unit,
                "event_id": spec.event_id,
                "cluster_id": cluster,
                "car": float(segment.iloc[-1] - segment.iloc[0]),
            }
            for column in exposure_columns:
                row[column] = exposures[column]
            unit_controls = control_lookup[unit]
            for column in ("size", "momentum", "pre_event_vol"):
                row[column] = unit_controls[column]
            rows.append(row)

    frame = pd.DataFrame(rows)
    if len(frame):
        frame = frame.sort_values(["event_id", "unit_id"], ignore_index=True)

    return CARPanel(
        frame=frame,
        dropped=dropped,
        window=window,
        events_requested=len(specs),
        units_requested=len(units),
        notes=tuple(notes),
    )
