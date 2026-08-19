r"""Daily equity prices for the configured universe.

Structure
---------
Network access and panel construction are separate on purpose:

* :func:`fetch_prices` touches yfinance and caches to `data/raw/`;
* :func:`build_panel` is pure and takes the fetched frames as input.

Everything with a point-in-time consequence -- adjustment, clock alignment,
liquidity screening, calendar intersection -- lives in the pure half, so it is
covered by tests that never open a socket, and so a reviewer can read the
point-in-time logic without reading a scraper.

Adjustment
----------
`docs/data_inventory.md` §7 flags the trap: yfinance's ``auto_adjust`` applies
adjustment factors retroactively across the whole series, so **a split in 2025
rewrites the 2020 prices**. Under `CLAUDE.md` §2.4 that is a point-in-time
violation. There is no default here; the caller states which mode they want
and it is carried through to every downstream estimate and printed in every
table.

**How much of that trap actually bites a returns-based study is worth stating
precisely, because the answer is "less than it first appears".** Write a
back-adjusted price as :math:`A_t = C_t / B_t` where
:math:`B_t = \prod_{s>t} f_s` collects every factor dated after :math:`t`.
Then

.. math:: \frac{A_t}{A_{t-1}} = \frac{C_t}{C_{t-1}}\cdot\frac{B_{t-1}}{B_t}
          = \frac{C_t}{C_{t-1}} f_t,

because :math:`B_{t-1} = f_t B_t`. **Every factor dated after :math:`t`
cancels between numerator and denominator.** The retroactive restatement moves
the price *level* but leaves consecutive returns depending only on the factor
effective on the day itself -- which is exactly what the point-in-time
construction uses.

Two consequences, and the design leans on both:

* The reason `config/universe.yaml` `notes.matching_variable` bans price
  levels as the SC matching variable is not only that levels are trivially
  easy to fit. Levels are also where the retroactive contamination lives. A
  returns-based outcome is immune to it; a level-based one is not.
* The residual exposure is factor **revision**, not factor **timing**: Yahoo
  silently corrects a split ratio or a dividend after the fact, and *that*
  does change past returns. Vintaged caching (the download date is in every
  cache filename) is the defence, and comparing two vintages is the only way
  to measure it.

:class:`Adjustment` therefore has three members that answer three questions:

``POINT_IN_TIME``
    Raw closes plus the dated corporate-action schedule, applied forward only:
    :math:`r_t = (f_t C_t + D_t)/C_{t-1} - 1`. Nothing dated after :math:`t`
    enters. This is the mode the report uses.
``AUTO_ADJUST``
    yfinance's own ``auto_adjust=True`` series, **fetched rather than
    reconstructed** -- reproducing Yahoo's exact dividend convention offline
    would be guesswork, and a mode that silently reduces to POINT_IN_TIME
    tests nothing. Marked `RETROACTIVE-ADJUSTMENT` at the call site, in the
    spirit of `CLAUDE.md` §2.1's `REALISED-WEATHER-DIAGNOSTIC`. Its purpose is
    to *measure* the residual difference against POINT_IN_TIME, which by the
    algebra above should be small and confined to ex-dividend dates. If it is
    not small, something is wrong with the action schedule and that is worth
    knowing.
``UNADJUSTED``
    Raw closes, nothing applied. A 2-for-1 split appears as a -50% return, so
    this mode manufactures enormous fake abnormal returns on ex-dates. It
    exists to show what the adjustment is doing, not to estimate with, and
    :func:`build_panel` refuses it unless explicitly forced.

Currency
--------
`config/universe.yaml` `notes.fx`: donor prices are never converted to GBP,
because UK policy news moves GBP and the conversion would inject that move
into every donor return as a spurious treatment effect. This module has no
currency-conversion code path. The only FX in the project is
`meta.fx_screen_rates_to_gbp`, used solely to compare turnover across
listings when screening for liquidity -- a pool-selection step, not a return
transformation.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Final

import numpy as np
import pandas as pd

from policy_event_study.data.universe import (
    Alignment,
    ClockClass,
    Outcome,
    Universe,
    load_universe,
)
from policy_event_study.paths import RAW_DIR

if TYPE_CHECKING:  # pragma: no cover - import cost only
    pass

YFINANCE_CACHE: Final[Path] = RAW_DIR / "yfinance"


class PriceSourceUnreachableError(RuntimeError):
    """The price source could not be reached at all.

    Distinct from "the symbol returned no rows", and the distinction is not
    pedantic. Under a blocked egress route yfinance does not raise on every
    path: it logs a transport failure, returns an EMPTY frame, and emits
    ``$TICKER: possibly delisted; no timezone found``. A caller that treats
    empty as delisting will then be told that Grainger and Genuit have
    delisted, which is false, and will go looking for a corporate action that
    never happened.

    That failure mode is especially dangerous in this project, because
    ``config/universe.yaml`` deliberately contains names that *genuinely* were
    delisted inside the sample (`PRSR.L`, `CSH.L`). A connectivity fault and a
    real delisting are indistinguishable from a single empty frame, so they
    are separated here by looking at the batch: if nothing at all came back,
    the network is the explanation, not thirty simultaneous delistings.
    """


#: Columns `fetch_prices` guarantees on every returned frame. `close_auto_adj`
#: is Yahoo's own back-adjusted series, stored alongside the raw close so the
#: AUTO_ADJUST comparison uses Yahoo's convention rather than a guess at it.
PRICE_COLUMNS: Final[tuple[str, ...]] = (
    "close",
    "close_auto_adj",
    "volume",
    "dividend",
    "split_ratio",
)


class Adjustment(enum.StrEnum):
    """How corporate actions enter the return series. See the module docstring."""

    POINT_IN_TIME = "point_in_time"
    AUTO_ADJUST = "auto_adjust"
    UNADJUSTED = "unadjusted"

    @property
    def is_retroactive(self) -> bool:
        """True where past returns depend on factors published later."""
        return self is Adjustment.AUTO_ADJUST


@dataclass(frozen=True)
class PanelProvenance:
    """Everything a table must disclose about how a panel was built.

    Carried on every :class:`ReturnPanel` and copied onto every effect
    estimate, so a result cannot be reported without its adjustment mode,
    its clock convention, or the survivorship caveat.
    """

    vintage: str
    adjustment: Adjustment
    alignment: Alignment
    universe_path: str
    source: str = "yfinance (unofficial Yahoo Finance scraper)"
    licence: str = (
        "No public redistribution licence. Personal research use only; price "
        "data is gitignored and never committed. See docs/data_inventory.md §7."
    )
    lagged_tickers: tuple[str, ...] = ()
    early_close_tickers: tuple[str, ...] = ()
    screened_out: Mapping[str, str] = field(default_factory=dict)
    calendar_days_dropped: int = 0
    survivorship_biased: bool = True
    #: Always False. `notes.fx` forbids converting returns; asserted, not assumed.
    fx_converted: bool = False

    @property
    def retroactive_adjustment(self) -> bool:
        """True when the adjustment mode rewrites history. Labels report rows."""
        return self.adjustment.is_retroactive

    def caveats(self) -> tuple[str, ...]:
        """Disclosures the report is required to carry for this panel."""
        notes: list[str] = []
        if self.retroactive_adjustment:
            notes.append(
                "RETROACTIVE-ADJUSTMENT: prices use yfinance auto_adjust, which "
                "applies split and dividend factors backwards across the whole "
                "series. A corporate action after the event date alters "
                "pre-event prices (CLAUDE.md §2.4)."
            )
        if self.adjustment is Adjustment.UNADJUSTED:
            notes.append(
                "UNADJUSTED prices: ex-dates carry mechanical jumps that are not "
                "returns. Diagnostic use only."
            )
        if self.survivorship_biased:
            notes.append(
                "SURVIVORSHIP: the pool is built from tickers yfinance still "
                "serves. Firms acquired or delisted during the sample are absent, "
                "which flatters pre-treatment fit (CLAUDE.md §2.4; "
                "config/universe.yaml notes.survivorship)."
            )
        if self.lagged_tickers:
            notes.append(
                f"CLOCK ALIGNMENT ({self.alignment}): {list(self.lagged_tickers)} "
                "close after the LSE and are lagged one trading day so each "
                "observation completed before the London close."
            )
        if self.early_close_tickers:
            notes.append(
                f"RESIDUAL MISALIGNMENT: {list(self.early_close_tickers)} close "
                "*before* the LSE. Correcting this would need a lead, which is "
                "future information, so it is disclosed rather than fixed."
            )
        if self.screened_out:
            notes.append(f"SCREENED OUT: {dict(self.screened_out)}")
        return tuple(notes)


@dataclass(frozen=True)
class ReturnPanel:
    """Aligned daily simple returns for the universe.

    Attributes
    ----------
    returns
        Wide frame, tz-aware UTC `DatetimeIndex` of trading dates by ticker.
        Simple returns in **local currency** -- see `notes.fx`.
    market
        Market-index simple returns on the same index, for the market-model
        baseline. Never a donor.
    provenance
        See :class:`PanelProvenance`.
    """

    returns: pd.DataFrame
    market: pd.Series
    provenance: PanelProvenance
    outcome_kind: Outcome = Outcome.CUMULATIVE_SIMPLE_RETURNS

    @property
    def tickers(self) -> tuple[str, ...]:
        """Every ticker with a return series in this panel."""
        return tuple(str(column) for column in self.returns.columns)

    @property
    def trading_days(self) -> pd.DatetimeIndex:
        """The panel's common trading calendar."""
        index = self.returns.index
        assert isinstance(index, pd.DatetimeIndex)
        return index

    def window(self, start: pd.Timestamp, end: pd.Timestamp) -> ReturnPanel:
        """Restrict to `[start, end]` inclusive, preserving provenance."""
        mask = (self.returns.index >= start) & (self.returns.index <= end)
        return ReturnPanel(
            returns=self.returns.loc[mask],
            market=self.market.loc[mask],
            provenance=self.provenance,
            outcome_kind=self.outcome_kind,
        )

    def outcome(self, tickers: Sequence[str] | None = None) -> pd.DataFrame:
        """Build the SC/SDiD matching variable.

        `config/universe.yaml` `notes.matching_variable` requires cumulative
        returns rather than price levels. `meta.outcome` selects between the
        cumulative *sum* of simple returns (the default, which keeps the
        estimated gap directly interpretable as a cumulative abnormal return
        and therefore comparable with the market-model CAR) and cumulative log
        returns.

        The series starts at zero on the first row of whatever window this
        panel covers, so the level is meaningless and only the path matters --
        which is the point.
        """
        columns = list(tickers) if tickers is not None else list(self.returns.columns)
        frame = self.returns.loc[:, columns]
        if self.outcome_kind is Outcome.CUMULATIVE_LOG_RETURNS:
            return pd.DataFrame(
                np.log1p(frame.to_numpy(dtype=float)),
                index=frame.index,
                columns=frame.columns,
            ).cumsum()
        return frame.cumsum()

    def complete_units(
        self, units: Sequence[str], start: pd.Timestamp, end: pd.Timestamp
    ) -> tuple[str, ...]:
        """Units with no missing return over `[start, end]`.

        Completeness is a property of the *window*, not of the panel. Units
        with availability bounds (the two Barratt units) and the several
        hundred names of the dose-response cross-section have listing dates
        scattered across the sample, so a panel-wide completeness rule would
        either discard most of the universe or silently admit NaNs into a fit.
        """
        present = [unit for unit in units if unit in self.returns.columns]
        if not present:
            return ()
        block = self.returns.loc[
            (self.returns.index >= start) & (self.returns.index <= end), present
        ]
        if block.empty:
            return ()
        return tuple(str(unit) for unit in block.columns[block.notna().all()])

    def equal_weighted(self, tickers: Sequence[str], name: str) -> pd.Series:
        """Equal-weighted portfolio return series over `tickers`.

        Implements `notes.power`: pooling same-signed treated names into one
        unit raises signal-to-noise at the cost of firm-level detail. The
        config is explicit that opposite-signed units must not be pooled, so
        the caller supplies the sign-consistent list -- see
        :meth:`Universe.signed_portfolio_members`.
        """
        missing = [ticker for ticker in tickers if ticker not in self.returns.columns]
        if missing:
            msg = f"not in panel: {missing}"
            raise KeyError(msg)
        series = self.returns.loc[:, list(tickers)].mean(axis=1)
        series.name = name
        return series

    def with_unit(self, series: pd.Series) -> ReturnPanel:
        """Return a copy with an extra synthetic unit appended as a column."""
        if series.name is None:
            msg = "series must be named to be added as a panel unit"
            raise ValueError(msg)
        merged = self.returns.copy()
        merged[str(series.name)] = series.reindex(self.returns.index)
        return ReturnPanel(
            returns=merged,
            market=self.market,
            provenance=self.provenance,
            outcome_kind=self.outcome_kind,
        )


# --------------------------------------------------------------------------
# network half
# --------------------------------------------------------------------------


def _cache_path(ticker: str, vintage: str) -> Path:
    """Cache location for one ticker's raw history at a given vintage."""
    safe = ticker.replace("/", "_").replace("^", "idx_")
    return YFINANCE_CACHE / f"{safe}__{vintage}.parquet"


def load_cached_prices(
    tickers: Sequence[str], *, vintage: str
) -> tuple[dict[str, pd.DataFrame], tuple[str, ...]]:
    """Read cached history for `tickers`, touching no network at all.

    `fetch_prices` prefers the cache but falls back to the network on a miss,
    which makes an estimation run silently dependent both on connectivity and
    on whatever Yahoo serves *today* rather than at `vintage`. Estimation must
    be reproducible from a fixed vintage, so it uses this instead.

    A missing ticker is **returned, not raised on**. Two symbols in this
    project's universe are genuine delistings that no vintage will ever
    contain (`PRSR.L`, `SIG.L`), and a loader that raised on them would make
    estimation impossible to run at all. The caller decides what an absence
    means, and every caller in this repository reports the list rather than
    swallowing it.

    Returns
    -------
    tuple
        Ticker to frame for everything the cache had, and the tickers it did
        not, in sorted order.
    """
    frames: dict[str, pd.DataFrame] = {}
    absent: list[str] = []
    for ticker in tickers:
        cached = _cache_path(ticker, vintage)
        if cached.exists():
            frames[ticker] = pd.read_parquet(cached)
        else:
            absent.append(ticker)
    return frames, tuple(sorted(absent))


def fetch_prices(
    tickers: Sequence[str],
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    vintage: str,
    use_cache: bool = True,
) -> dict[str, pd.DataFrame]:
    """Download daily history for `tickers`, caching to `data/raw/yfinance/`.

    Source: Yahoo Finance via the `yfinance` package
        (https://github.com/ranaroussi/yfinance). Unofficial: Yahoo publishes
        no licence permitting programmatic bulk access, so the data is used
        for personal research only and is never committed
        (docs/data_inventory.md §7).
    Licence: none granted. Do not redistribute. `data/` is gitignored.
    Vintage: the `vintage` argument, which is the download date and appears in
        every cache filename. Yahoo silently revises historical values, so two
        vintages of the "same" series are not necessarily identical -- which
        is exactly why the vintage is in the filename rather than implied.
    Publication lag: daily bars are knowable from that exchange's close. The
        close time differs by exchange and that difference is handled in
        :func:`build_panel`, not here -- see `config/universe.yaml`
        `notes.timezone`.

    Fetches **both** the unadjusted series with actions and Yahoo's own
    back-adjusted close, in two calls. The raw close plus the dated action
    schedule is what the point-in-time construction needs; Yahoo's adjusted
    close is stored beside it because reproducing Yahoo's dividend convention
    offline would be a guess, and a comparison against a guess measures the
    guess rather than the data.

    Returns
    -------
    dict[str, pd.DataFrame]
        Ticker to frame with columns `PRICE_COLUMNS` and a tz-aware UTC
        `DatetimeIndex` normalised to midnight.
    """
    import yfinance  # imported here so the pure half needs no network dependency

    YFINANCE_CACHE.mkdir(parents=True, exist_ok=True)
    frames: dict[str, pd.DataFrame] = {}
    empty_tickers: list[str] = []
    fetched_live = 0  # tickers that hit the network AND came back with rows

    for ticker in tickers:
        cached = _cache_path(ticker, vintage)
        if use_cache and cached.exists():
            frames[ticker] = pd.read_parquet(cached)
            continue

        handle = yfinance.Ticker(ticker)
        try:
            raw = handle.history(
                start=start.date().isoformat(),
                end=end.date().isoformat(),
                interval="1d",
                auto_adjust=False,  # see module docstring: adjust offline, forward only
                actions=True,
            )
        # Broad by design: yfinance surfaces transport failures as whatever
        # the underlying HTTP stack raised, and none of it is a typed API.
        except Exception as exc:
            msg = (
                f"could not reach the price source while fetching {ticker!r}: "
                f"{type(exc).__name__}: {exc}. This is a transport failure, "
                "NOT evidence about the symbol."
            )
            raise PriceSourceUnreachableError(msg) from exc
        # RETROACTIVE-ADJUSTMENT: this second series is Yahoo's back-adjusted
        # close. Every value in it may be rewritten by a corporate action
        # dated later than the value itself. Stored for the labelled
        # comparison in Adjustment.AUTO_ADJUST; never used by POINT_IN_TIME.
        adjusted = handle.history(
            start=start.date().isoformat(),
            end=end.date().isoformat(),
            interval="1d",
            auto_adjust=True,
            actions=False,
        )
        if raw.empty:
            # Defer the verdict. An empty frame alone cannot distinguish a
            # delisted symbol from a blocked route; only the batch can.
            empty_tickers.append(ticker)
            continue

        frame = pd.DataFrame(
            {
                "close": raw["Close"].astype(float),
                "close_auto_adj": adjusted["Close"].reindex(raw.index).astype(float),
                "volume": raw["Volume"].astype(float),
                "dividend": raw.get(
                    "Dividends", pd.Series(0.0, index=raw.index)
                ).astype(float),
                "split_ratio": raw.get(
                    "Stock Splits", pd.Series(0.0, index=raw.index)
                ).astype(float),
            }
        )
        frame.index = pd.DatetimeIndex(frame.index).tz_convert("UTC").normalize()
        frame.index.name = "date"
        frame.to_parquet(cached)
        frames[ticker] = frame
        fetched_live += 1

    if empty_tickers:
        if fetched_live == 0:
            msg = (
                f"every live fetch returned an empty frame "
                f"({len(empty_tickers)} of {len(tickers)} tickers: "
                f"{', '.join(empty_tickers)}). Nothing reached the source, so "
                "this is a transport or egress failure and says NOTHING about "
                "whether any of these symbols is current. Do not go looking "
                "for delistings on the strength of this message."
            )
            raise PriceSourceUnreachableError(msg)
        msg = (
            f"the source returned no rows for {empty_tickers} over "
            f"{start.date()}..{end.date()}, while {fetched_live} other "
            "ticker(s) fetched normally, so the route is fine and these "
            "symbols are the problem. Verify each against "
            "config/universe.yaml: several UK mid-caps were acquired or "
            "delisted inside the sample and need a `listed_to` window rather "
            "than a live symbol."
        )
        raise ValueError(msg)

    return frames


# --------------------------------------------------------------------------
# pure half
# --------------------------------------------------------------------------


def compute_returns(frame: pd.DataFrame, adjustment: Adjustment) -> pd.Series:
    r"""Turn one ticker's raw history into a simple return series.

    Parameters
    ----------
    frame
        Columns `PRICE_COLUMNS`, indexed by tz-aware UTC date.
    adjustment
        See :class:`Adjustment`.

    Notes
    -----
    The `POINT_IN_TIME` construction is

    .. math:: r_t = \frac{k_t P_t + D_t}{P_{t-1}} - 1

    where :math:`k_t` is the split ratio with ex-date :math:`t` (1 when there
    is no split) and :math:`D_t` the dividend with ex-date :math:`t`. Both
    factors are effective on :math:`t` and known on :math:`t`; nothing dated
    after :math:`t` enters.

    `AUTO_ADJUST` differences Yahoo's own back-adjusted close. As the module
    docstring shows, the back-adjustment factor cancels between numerator and
    denominator, so the two modes should agree closely and disagree only where
    Yahoo's dividend convention differs from the additive one above. That
    difference is a *measurement*, reported in the report's robustness
    section, not an assumption.
    """
    missing = [
        column
        for column in PRICE_COLUMNS
        if column not in frame.columns and column != "close_auto_adj"
    ]
    if missing:
        msg = f"price frame is missing columns {missing}"
        raise KeyError(msg)

    close = frame["close"].astype(float)

    if adjustment is Adjustment.UNADJUSTED:
        return close.pct_change()

    if adjustment is Adjustment.AUTO_ADJUST:
        if "close_auto_adj" not in frame.columns:
            msg = (
                "Adjustment.AUTO_ADJUST needs the `close_auto_adj` column, which "
                "fetch_prices stores from yfinance's own auto_adjust=True series. "
                "It is deliberately not reconstructed from the raw close: Yahoo's "
                "dividend convention is not documented, and a reconstruction "
                "would reduce to POINT_IN_TIME and test nothing"
            )
            raise KeyError(msg)
        # RETROACTIVE-ADJUSTMENT: every value in this series may have been
        # rewritten by a corporate action dated after it.
        return frame["close_auto_adj"].astype(float).pct_change()

    ratio = frame["split_ratio"].replace(0.0, 1.0).astype(float)
    dividend = frame["dividend"].astype(float)
    return (ratio * close + dividend) / close.shift(1) - 1.0


def _lag_late_markets(
    series_by_ticker: Mapping[str, pd.Series], universe: Universe
) -> tuple[dict[str, pd.Series], tuple[str, ...]]:
    """Shift late-closing tickers forward one of their own trading days.

    `notes.timezone`: a US donor's day-D close already contains a UK
    announcement that the London day-D close also contains -- but the US close
    is four and a half hours later, so its day-D observation spans information
    the London day-D observation cannot. Shifting the donor forward by one of
    *its own* trading days makes its day-D observation end before the London
    day-D close, restoring the ordering.
    """
    lagged: dict[str, pd.Series] = {}
    shifted: list[str] = []
    for ticker, series in series_by_ticker.items():
        if universe.clock_alignment(ticker).clock_class is ClockClass.LATE:
            lagged[ticker] = series.shift(1)
            shifted.append(ticker)
        else:
            lagged[ticker] = series
    return lagged, tuple(shifted)


def _liquidity_screen(
    frames: Mapping[str, pd.DataFrame],
    universe: Universe,
    candidates: Sequence[str],
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> dict[str, str]:
    """Screen donors on average daily turnover. Returns ticker -> rejection reason.

    Turnover is compared across listings using `meta.fx_screen_rates_to_gbp`.
    This is the only FX in the project and it never touches a return series --
    see `notes.fx`. The screen selects the pool, and the pool is fixed before
    estimation, so a coarse long-run rate is adequate and a point-in-time rate
    would be false precision.
    """
    threshold = universe.meta.min_avg_daily_volume_gbp
    rejected: dict[str, str] = {}
    for ticker in candidates:
        frame = frames[universe.listing(ticker).source_ticker]
        window = frame.loc[(frame.index >= start) & (frame.index <= end)]
        if window.empty:
            rejected[ticker] = "no observations in the screening window"
            continue
        currency = universe.listing(ticker).exchange.currency
        rate = universe.meta.fx_screen_rates_to_gbp[currency]
        turnover = float((window["close"] * window["volume"]).mean()) * rate
        if turnover < threshold:
            rejected[ticker] = (
                f"average daily turnover {turnover:,.0f} GBP is below the "
                f"{threshold:,.0f} GBP floor; illiquid names distort SC weights"
            )
    return rejected


def build_panel(
    frames: Mapping[str, pd.DataFrame],
    universe: Universe,
    *,
    adjustment: Adjustment,
    vintage: str,
    screen_start: pd.Timestamp | None = None,
    screen_end: pd.Timestamp | None = None,
    allow_unadjusted_estimation: bool = False,
) -> ReturnPanel:
    """Assemble aligned, screened daily returns from fetched price frames.

    This is the pure half of the module: no network, deterministic, and the
    place every point-in-time decision is made.

    Parameters
    ----------
    frames
        Ticker to raw price frame, as returned by :func:`fetch_prices`.
    universe
        Parsed `config/universe.yaml`.
    adjustment
        Required. There is no default -- see the module docstring.
    vintage
        Download date of `frames`, recorded in the provenance.
    screen_start, screen_end
        Window over which donor liquidity is measured. Defaults to the full
        sample. Should be a *pre-event* window so the screen cannot select on
        post-event activity.
    allow_unadjusted_estimation
        `Adjustment.UNADJUSTED` manufactures fake abnormal returns on every
        ex-date, so it is refused unless this is set. Diagnostic use only.

    Steps, in order
    ---------------
    1. returns per ticker on its own calendar, with the chosen adjustment;
    2. late-closing tickers lagged one trading day (`notes.timezone`);
    3. donors failing the liquidity screen dropped (`meta.min_avg_daily_volume_gbp`);
    4. all series intersected onto a common calendar -- intersection rather
       than forward-fill, because a forward-filled price yields a zero return
       that a synthetic control happily fits and that never happened.
    """
    if adjustment is Adjustment.UNADJUSTED and not allow_unadjusted_estimation:
        msg = (
            "Adjustment.UNADJUSTED yields a -50% return on every 2-for-1 split "
            "ex-date, which any estimator will read as an enormous abnormal "
            "return. Pass allow_unadjusted_estimation=True only to measure the "
            "adjustment's effect; use Adjustment.POINT_IN_TIME to estimate."
        )
        raise ValueError(msg)

    required = set(universe.source_tickers)
    absent = sorted(required - set(frames))
    if absent:
        msg = f"no price frame supplied for {absent}"
        raise KeyError(msg)

    # One fetch per source ticker; one column per *unit*. Aliased units share a
    # source and are separated by their availability bounds -- which is the
    # whole point: BARRATT_PRE and BTRW.L come from the same Yahoo symbol and
    # must never both carry data on the same date.
    series_by_ticker: dict[str, pd.Series] = {}
    for listing in universe.all_listings:
        series = compute_returns(frames[listing.source_ticker], adjustment)
        if listing.available_from is not None:
            series = series[series.index >= listing.available_from.tz_localize("UTC")]
        if listing.available_to is not None:
            series = series[series.index <= listing.available_to.tz_localize("UTC")]
        series_by_ticker[listing.unit_id] = series

    if universe.meta.alignment is Alignment.LAG_LATE_MARKETS:
        series_by_ticker, lagged = _lag_late_markets(series_by_ticker, universe)
    else:
        lagged = ()

    sample_start = min(series.index.min() for series in series_by_ticker.values())
    sample_end = max(series.index.max() for series in series_by_ticker.values())
    rejected = _liquidity_screen(
        frames,
        universe,
        [listing.unit_id for listing in universe.donors],
        start=screen_start if screen_start is not None else sample_start,
        end=screen_end if screen_end is not None else sample_end,
    )

    index_unit = universe.market_index.unit_id
    keep = [
        listing.unit_id
        for listing in universe.all_listings
        if listing.unit_id not in rejected and listing.unit_id != index_unit
    ]

    # The LSE calendar is the spine. Units are reindexed onto it and **NaNs are
    # preserved**, not intersected away: units with availability bounds (the
    # two Barratt units) never overlap, so a strict intersection would return
    # an empty panel, and the dose-response design's several-hundred-name
    # cross-section has listing dates scattered across the sample. Completeness
    # is therefore resolved per event window by `ReturnPanel.complete_units`,
    # where it is a property of the window rather than of the whole panel.
    spine = pd.DatetimeIndex(sorted(series_by_ticker[index_unit].dropna().index))

    returns = pd.DataFrame(
        {unit: series_by_ticker[unit].reindex(spine) for unit in keep},
        index=spine,
    )
    market = series_by_ticker[index_unit].reindex(spine)
    market.name = index_unit
    union = spine
    common = spine

    provenance = PanelProvenance(
        vintage=vintage,
        adjustment=adjustment,
        alignment=universe.meta.alignment,
        universe_path=str(universe.source_path),
        lagged_tickers=lagged,
        early_close_tickers=universe.early_units,
        screened_out=rejected,
        calendar_days_dropped=max(len(union) - len(common), 0),
        survivorship_biased=universe.survivorship_biased,
    )
    return ReturnPanel(
        returns=returns,
        market=market,
        provenance=provenance,
        outcome_kind=universe.meta.outcome,
    )


def load_panel(
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    adjustment: Adjustment,
    vintage: str,
    universe: Universe | None = None,
    universe_path: Path | None = None,
    screen_start: pd.Timestamp | None = None,
    screen_end: pd.Timestamp | None = None,
    allow_unadjusted_estimation: bool = False,
) -> ReturnPanel:
    """Fetch and assemble in one call. Convenience wrapper; hits the network."""
    resolved = universe if universe is not None else load_universe(universe_path)
    frames = fetch_prices(resolved.source_tickers, start, end, vintage=vintage)
    return build_panel(
        frames,
        resolved,
        adjustment=adjustment,
        vintage=vintage,
        screen_start=screen_start,
        screen_end=screen_end,
        allow_unadjusted_estimation=allow_unadjusted_estimation,
    )
