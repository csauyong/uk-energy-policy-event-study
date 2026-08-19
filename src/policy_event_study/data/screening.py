"""The broad cross-section the dose-response design identifies from.

WHY THIS MODULE EXISTS
----------------------
The dose-response estimand regresses cumulative abnormal return on exposure
with an event fixed effect. That fixed effect is what absorbs the market-wide
move on the announcement day, and it is estimated almost entirely from firms
with **zero** exposure. Without them, `alpha_e` is fitted off the handful of
treated names and beta is no longer identified off anything meaningful.

So the screening universe is not decoration around the treated set. It is the
control group, and its members earn their place by being *unaffected*.

HOW BIG IT NEEDS TO BE
----------------------
Smaller than the design document assumed. `reports/dose_response.md` section
2.5 measured it: going from 100 to 600 firms moved the MDE by under 5%, while
going from 4 to 15 events roughly halved it. With large clusters, effective N
is governed by the number of independent dates, not by the cross-section.

That finding is why this module targets a FTSE-350-scale list rather than the
"several hundred names" the original `config/universe.yaml` note called for.
Curation effort belongs on events, not on breadth.

WHAT IS IN AND WHAT IS OUT
--------------------------
In: London-listed **operating companies**, from the published FTSE 100 and
FTSE 250 membership lists recorded in `data/universe/index_membership.csv`.

Out, in three passes, each of which records its reason rather than silently
dropping a row:

1. **Closed-end investment vehicles.** An investment trust's return tracks the
   NAV of a portfolio that is mostly not UK-domiciled and never UK-policy
   exposed. Including one adds a row whose abnormal return is noise around a
   foreign index, which inflates the residual variance that `se(beta)` is
   computed from without adding any identifying variation. REITs and listed
   operating companies stay: a REIT owns and operates buildings, so it is a
   firm, not a wrapper. See :data:`INVESTMENT_VEHICLE_KEYWORDS` and
   :data:`INVESTMENT_VEHICLES_BY_NAME`.
2. **Names already curated in `config/universe.yaml`.** They enter the panel
   with a curated exposure score. Re-adding them here as assumed zeros would
   overwrite the curation with a default and quietly destroy the treatment.
3. **Names failing the history or liquidity floors** in the
   `screening_universe:` block of `config/universe.yaml`.

SURVIVORSHIP IS MEASURED HERE, NOT ASSUMED
------------------------------------------
Yahoo does not serve delisted symbols. The FTSE 100 list used is a published
snapshot that still contains firms acquired or delisted during the sample --
Avast, AVEVA, EVRAZ, Polymetal, RSA, Morrisons, DS Smith and others. They are
kept in the *attempted* list on purpose, so that the fetch failure count is a
**measurement** of the survivorship gap rather than a hypothetical about it.
:class:`ScreeningResult` reports that count.

The direction of the bias matters, and it is not the usual one. Survivorship
in a *screening* universe is not survivorship in a treated set. These firms
carry zero exposure whether or not they survived, so their absence:

* does not move the exposure gradient, because dropping zero-exposure rows
  does not change the covariance between exposure and CAR that beta is; and
* does slightly reduce the precision of `alpha_e`, because the event fixed
  effect is estimated from fewer firms.

**So survivorship here inflates the standard error and leaves the point
estimate alone.** That makes any significant result conservative and any null
weaker than it looks. Stated in `reports/results.md` in those terms.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

import pandas as pd

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Iterable, Mapping, Sequence
    from pathlib import Path

#: London Stock Exchange suffix in Yahoo's symbology.
LSE_SUFFIX: Final[str] = ".L"

#: Substrings that mark a listing as a closed-end investment vehicle rather
#: than an operating company. Matched case-insensitively on the name.
#:
#: Deliberately broad. A false positive costs one control observation out of
#: two hundred; a false negative puts a Japanese equity portfolio into a study
#: of UK building regulations.
INVESTMENT_VEHICLE_KEYWORDS: Final[tuple[str, ...]] = (
    "investment trust",
    "investment company",
    "investments",
    "capital partners",
    "private equity",
    "smaller companies",
    "emerging markets",
    "growth & income",
    "dividend income",
    "income fund",
    "income trust",
    "opportunity fund",
    "infrastructure company",
    "infrastructure investments",
    " fund",
    " trust",
)

#: Closed-end vehicles whose names carry none of the keywords above. Listed
#: explicitly so the exclusion is auditable rather than buried in a regex.
#:
#: The rule these share: the entity holds a portfolio of assets and reports a
#: NAV, and its share price tracks that NAV. `3i Group` is the borderline case
#: and is excluded on the same ground -- it is a balance sheet of holdings, not
#: a trading business, whatever its FTSE 100 classification says.
INVESTMENT_VEHICLES_BY_NAME: Final[frozenset[str]] = frozenset(
    {
        "3i group",
        "3i infrastructure",
        "aberdeen asia focus",
        "aberforth smaller companies trust",
        "allianz technology trust",
        "ashoka india equity investment trust",
        "avi global trust",
        "bankers investment trust",
        "bh macro",
        "biopharma credit",
        "bluefield solar income fund",
        "brunner investment trust",
        "caledonia investments",
        "capital gearing trust",
        "chrysalis investments",
        "city of london investment trust",
        "edinburgh investment trust",
        "edinburgh worldwide investment trust",
        "european smaller companies trust",
        "foresight environmental infrastructure",
        "gcp infrastructure investments",
        "global smaller companies trust",
        "greencoat uk wind",
        "harbourvest global private equity",
        "herald investment trust",
        "hg capital trust",
        "hicl infrastructure company",
        "icg enterprise trust",
        "impax environmental markets",
        "international public partnerships",
        "invesco asia dragon trust",
        "ip group",
        "law debenture",
        "mercantile investment trust",
        "merchants trust",
        "molten ventures",
        "monks investment trust",
        "murray income trust",
        "murray international trust",
        "nb private equity partners",
        "north atlantic smaller companies investment trust",
        "oakley capital investments",
        "pacific horizon investment trust",
        "pantheon infrastructure",
        "pantheon international",
        "partners group private equity",
        "patria private equity trust",
        "personal assets trust",
        "polar capital global healthcare trust",
        "rit capital partners",
        "rtw biotech opportunities",
        "ruffer investment company",
        "schiehallion fund",
        "scottish american investment company",
        "scottish mortgage investment trust",
        "sequoia economic infrastructure income fund",
        "syncona",
        "temple bar investment trust",
        "the renewables infrastructure group",
        "tr property investment trust",
        "twentyfour income fund",
        "utilico emerging markets",
        "vietnam enterprise investments",
        "vinacapital vietnam opportunity fund",
        "worldwide healthcare trust",
        "pershing square holdings",
    }
)


class ScreeningError(ValueError):
    """Raised when the screening universe cannot be assembled coherently."""


def epic_to_yahoo(epic: str) -> str:
    """Convert an LSE EPIC code to Yahoo Finance's symbol for the same listing.

    Yahoo's convention for London listings has two wrinkles that a naive
    ``f"{epic}.L"`` gets wrong, and both appear in the FTSE 100:

    * a **trailing** dot in the EPIC is a padding character, not part of the
      symbol -- ``BP.`` is ``BP.L``, not ``BP..L``;
    * an **internal** dot separates a share class and Yahoo writes it as a
      hyphen -- ``BT.A`` is ``BT-A.L``.

    Getting either wrong produces a symbol that fetches empty, which would be
    silently misread as a delisting and inflate the measured survivorship gap.

    Examples
    --------
    >>> epic_to_yahoo("III")
    'III.L'
    >>> epic_to_yahoo("BP.")
    'BP.L'
    >>> epic_to_yahoo("BT.A")
    'BT-A.L'
    """
    cleaned = epic.strip().upper()
    if not cleaned:
        msg = "empty EPIC code"
        raise ScreeningError(msg)
    cleaned = cleaned.rstrip(".")
    cleaned = cleaned.replace(".", "-")
    return f"{cleaned}{LSE_SUFFIX}"


def is_investment_vehicle(name: str) -> bool:
    """Report whether a listing is a closed-end fund rather than an operating firm.

    Two tests, in order: the explicit name list, then the keyword scan. The
    explicit list is checked first so a name on it cannot be rescued by a
    keyword rule that happens not to match.

    REITs are **not** vehicles by this definition. `Supermarket Income REIT`
    and `Target Healthcare REIT` own and let buildings; a keyword match on
    ``income`` would wrongly exclude the first, so ``reit`` short-circuits.

    Examples
    --------
    >>> is_investment_vehicle("JPMorgan Japanese Investment Trust")
    True
    >>> is_investment_vehicle("Greggs")
    False
    >>> is_investment_vehicle("Supermarket Income REIT")
    False
    """
    lowered = name.strip().lower()
    if not lowered:
        return False
    if re.search(r"\breit\b", lowered):
        return False
    if lowered in INVESTMENT_VEHICLES_BY_NAME:
        return True
    return any(keyword in lowered for keyword in INVESTMENT_VEHICLE_KEYWORDS)


@dataclass(frozen=True)
class Candidate:
    """One name proposed for the screening universe, before any price is seen."""

    epic: str
    name: str
    index_name: str
    source_url: str

    @property
    def ticker(self) -> str:
        """Yahoo symbol for this listing."""
        return epic_to_yahoo(self.epic)


@dataclass(frozen=True)
class ScreeningResult:
    """The assembled screening universe, with every drop accounted for.

    Attributes
    ----------
    frame
        One row per admitted unit, with the columns
        `data/universe/uk_listed_universe.csv` carries.
    rejected
        Ticker to the reason it did not make it. Every candidate that is not
        in `frame` is in here; the two partition the candidate list, and
        :meth:`check_partition` asserts it.
    attempted
        How many candidates were put to the price source. The denominator of
        the survivorship figure.
    no_data
        Candidates the price source returned nothing for. These are the
        delisted and acquired names, and this count is the survivorship gap
        as measured rather than assumed.
    """

    frame: pd.DataFrame
    rejected: Mapping[str, str]
    attempted: int
    no_data: tuple[str, ...] = field(default_factory=tuple)

    @property
    def admitted(self) -> int:
        """How many units made it into the universe."""
        return len(self.frame)

    @property
    def survivorship_rate(self) -> float:
        """Share of attempted candidates the price source still serves."""
        if self.attempted == 0:
            return float("nan")
        return 1.0 - len(self.no_data) / self.attempted

    def check_partition(self, candidates: Sequence[Candidate]) -> None:
        """Assert every candidate is either admitted or rejected with a reason.

        A silent no-op is worse than a crash (CLAUDE.md section 6). A candidate
        that is in neither bucket means a filter dropped a row without saying
        so, which is exactly the class of defect this project keeps finding.

        Raises
        ------
        ScreeningError
            If any candidate is unaccounted for, or accounted for twice.
        """
        admitted = set(self.frame["unit_id"]) if len(self.frame) else set()
        explained = admitted | set(self.rejected)
        proposed = {candidate.ticker for candidate in candidates}
        unaccounted = sorted(proposed - explained)
        if unaccounted:
            msg = (
                f"{len(unaccounted)} candidates were neither admitted nor "
                f"rejected with a reason: {unaccounted[:10]}"
            )
            raise ScreeningError(msg)
        both = sorted(admitted & set(self.rejected))
        if both:
            msg = f"candidates both admitted and rejected: {both[:10]}"
            raise ScreeningError(msg)


def filter_candidates(
    candidates: Sequence[Candidate],
    *,
    exclude_tickers: Iterable[str],
) -> tuple[tuple[Candidate, ...], dict[str, str]]:
    """Apply the two pre-price filters, returning survivors and reasons.

    Runs before any price is fetched, which is the point: these two rules are
    about what a firm *is*, and neither may consult a return series. Rule 0
    (`docs/event_curation_protocol.md`) forbids letting price data influence
    membership, and a filter that ran after the fetch would be doing exactly
    that whatever its author intended.

    Parameters
    ----------
    candidates
        Proposed names, from the published index membership lists.
    exclude_tickers
        Source tickers already in `config/universe.yaml`. These carry curated
        exposure and must not be re-admitted as assumed zeros.

    Returns
    -------
    tuple
        Surviving candidates, and a ticker-to-reason map for the dropped ones.
    """
    excluded = {ticker.strip().upper() for ticker in exclude_tickers}
    survivors: list[Candidate] = []
    reasons: dict[str, str] = {}
    seen: set[str] = set()

    for candidate in candidates:
        ticker = candidate.ticker
        if ticker in seen:
            # Dual index membership -- B&M, Hikma, Johnson Matthey, Ocado,
            # Pennon, Taylor Wimpey and WPP appear on both published lists.
            continue
        seen.add(ticker)

        if ticker.upper() in excluded:
            reasons[ticker] = (
                "already curated in config/universe.yaml; enters the panel "
                "with its curated exposure rather than an assumed zero"
            )
            continue
        if is_investment_vehicle(candidate.name):
            reasons[ticker] = (
                "closed-end investment vehicle; its return tracks portfolio "
                "NAV rather than a UK operating business"
            )
            continue
        survivors.append(candidate)

    return tuple(survivors), reasons


def screen_on_prices(
    candidates: Sequence[Candidate],
    frames: Mapping[str, pd.DataFrame],
    *,
    min_history_days: int,
    min_avg_daily_volume_gbp: float,
    screen_end: pd.Timestamp,
) -> ScreeningResult:
    """Apply the history and liquidity floors, and build the universe frame.

    Parameters
    ----------
    candidates
        Names that survived :func:`filter_candidates`.
    frames
        Ticker to price frame, as returned by
        :func:`policy_event_study.data.prices.fetch_prices`. A ticker absent
        from this mapping, or present with no rows, is a delisting.
    min_history_days, min_avg_daily_volume_gbp
        The floors from the `screening_universe:` block of
        `config/universe.yaml`.
    screen_end
        Liquidity is measured over the year **ending here**, and this must be
        a pre-event date. Measuring it over the full sample would let activity
        after an announcement decide whether a firm is in the control group,
        which is selection on the outcome.

    Notes
    -----
    Turnover is computed in **pence** and converted, because Yahoo quotes
    London listings in pence rather than pounds. Getting this wrong scales
    every turnover figure by 100 and either admits everything or nothing --
    a failure that looks like a threshold problem and is a units problem.
    """
    if min_history_days <= 0:
        msg = f"min_history_days must be positive, got {min_history_days}"
        raise ScreeningError(msg)

    rows: list[dict[str, object]] = []
    rejected: dict[str, str] = {}
    no_data: list[str] = []
    window_start = pd.Timestamp(screen_end).tz_convert("UTC") - pd.Timedelta(days=365)

    for candidate in candidates:
        ticker = candidate.ticker
        frame = frames.get(ticker)
        if frame is None or frame.empty:
            no_data.append(ticker)
            rejected[ticker] = (
                "price source returned no rows; the listing is delisted, "
                "acquired or renamed. Counted in the survivorship gap"
            )
            continue

        if len(frame) < min_history_days:
            rejected[ticker] = (
                f"{len(frame)} trading days is below the "
                f"{min_history_days}-day history floor"
            )
            continue

        window = frame.loc[
            (frame.index >= window_start) & (frame.index <= pd.Timestamp(screen_end))
        ]
        if window.empty:
            rejected[ticker] = (
                "no trading days in the pre-event liquidity window; the "
                "listing had not started or had already stopped"
            )
            continue

        # Yahoo quotes London listings in pence.
        turnover_gbp = float((window["close"] * window["volume"]).mean()) / 100.0
        if turnover_gbp < min_avg_daily_volume_gbp:
            rejected[ticker] = (
                f"average daily turnover {turnover_gbp:,.0f} GBP is below the "
                f"{min_avg_daily_volume_gbp:,.0f} GBP floor"
            )
            continue

        rows.append(
            {
                "unit_id": ticker,
                "name": candidate.name,
                "source_ticker": ticker,
                "listed_from": frame.index[0].date().isoformat(),
                "listed_to": frame.index[-1].date().isoformat(),
                "icb_sector": "",
                "note": (
                    f"{candidate.index_name} member; screening universe, "
                    f"exposure assumed zero"
                ),
            }
        )

    frame_out = pd.DataFrame(
        rows,
        columns=[
            "unit_id",
            "name",
            "source_ticker",
            "listed_from",
            "listed_to",
            "icb_sector",
            "note",
        ],
    ).sort_values("unit_id", ignore_index=True)

    return ScreeningResult(
        frame=frame_out,
        rejected=rejected,
        attempted=len(candidates),
        no_data=tuple(sorted(no_data)),
    )


def read_index_membership(path: Path | str) -> tuple[Candidate, ...]:
    """Read the hand-recorded index membership list into candidates.

    The CSV is *source*, not data: it is a transcription of two published
    membership lists and no program in this repository can regenerate it. It
    is version controlled for the same reason the event dictionary is.
    """
    frame = pd.read_csv(path, dtype=str).fillna("")
    required = {"epic", "name", "index_name", "source_url"}
    missing = sorted(required - set(frame.columns))
    if missing:
        msg = f"index membership file is missing columns {missing}"
        raise ScreeningError(msg)
    return tuple(
        Candidate(
            epic=str(row.epic),
            name=str(row.name_),
            index_name=str(row.index_name),
            source_url=str(row.source_url),
        )
        for row in frame.rename(columns={"name": "name_"}).itertuples(index=False)
    )
