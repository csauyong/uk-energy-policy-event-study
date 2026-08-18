"""The four exposure channels, and the explicit zero.

Each channel maps curated firm attributes plus a policy target to a magnitude
in [0, 1] -- the fraction of the firm's business the policy touches. The
common scale is what makes a housebuilder and an insulation manufacturer
comparable in one cross-sectional regression.

Why "share below the mandated band" rather than portfolio size
--------------------------------------------------------------
A landlord with 100,000 dwellings all at band B has no capex obligation under
a mandate at C, and a landlord with 5,000 dwellings all at band F has a large
one. Dose is the share of the portfolio *requiring work*, not the portfolio's
size, and scaling by size would mostly recover market capitalisation -- which
the regression already controls for and which would make the exposure
coefficient a size effect wearing a policy label.

The same logic applies to housebuilders, with an extra term: a builder already
delivering to the mandated standard has zero dose however large it is.

Why the utility channel scores zero by default
----------------------------------------------
`config/exposure.yaml` sets `domestic_supply.channel_sign: 0`. Electrification
of heat is a volume gain for networks and a volume loss for gas supply, and
several of these firms sit on both sides. A channel whose sign cannot be
determined ex ante contributes no information to a *signed* dose-response
test; guessing the sign would contribute noise dressed as signal. These firms
therefore enter with exposure zero and are analysed separately, with the
sensitivity run assigning +1 and -1 and reporting both.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Final

from policy_event_study.exposure.schema import FirmAttribute, PolicyTarget, Scope

#: Attribute name for a firm's own build standard, as an EPC band.
BUILD_STANDARD_ATTRIBUTE: Final[str] = "build_standard_band"
UK_SHARE_ATTRIBUTE: Final[str] = "uk_revenue_share"
DOMESTIC_SUPPLY_ATTRIBUTE: Final[str] = "domestic_supply_share_gb"

#: Band-profile prefix for a landlord that does not split its stock by tenure.
GENERIC_STOCK_PREFIX: Final[str] = "dwellings_band_"
#: ...and the tenure-specific prefixes a landlord discloses instead.
PRS_STOCK_PREFIX: Final[str] = "dwellings_prs_band_"
SOCIAL_STOCK_PREFIX: Final[str] = "dwellings_social_band_"

#: Which band profiles a residential landlord may be scored on, per scope.
#:
#: MEES binds by TENURE, not by building type, so the tenure the firm lets on
#: is what decides whether an instrument reaches it. A scope absent from this
#: map does not reach a residential landlord at all -- `new_build` is the
#: housebuilder channel and `off_gas_grid` has no banded target row.
#:
#: The generic prefix means "domestic stock, tenure NOT disclosed" and appears
#: only under `all_domestic`. That is deliberate and it has teeth: a landlord
#: curated without a tenure split scores nothing at a tenure-specific event
#: rather than scoring as though it were fully exposed. The curator is thereby
#: forced to state the tenure, which is a disclosure, instead of the code
#: assuming one, which would be a fabricated value under R5.
STOCK_PREFIXES_BY_SCOPE: Final[Mapping[Scope, tuple[str, ...]]] = {
    Scope.ALL_DOMESTIC: (GENERIC_STOCK_PREFIX, PRS_STOCK_PREFIX, SOCIAL_STOCK_PREFIX),
    Scope.DOMESTIC_PRS: (PRS_STOCK_PREFIX,),
    Scope.SOCIAL_RENTED: (SOCIAL_STOCK_PREFIX,),
}


def band_index(band: str, bands: Sequence[str]) -> int:
    """Position of an EPC band in the best-to-worst ordering.

    Raises
    ------
    ValueError
        On an unrecognised band. Silently treating a typo as the worst band
        would hand the firm maximal exposure.
    """
    normalised = band.strip().upper()
    try:
        return list(bands).index(normalised)
    except ValueError:
        msg = f"unknown EPC band {band!r}; expected one of {list(bands)}"
        raise ValueError(msg) from None


def share_below_band(
    stock: Mapping[str, float], mandated_band: str, bands: Sequence[str]
) -> float:
    """Share of a stock profile sitting worse than the mandated band.

    Parameters
    ----------
    stock
        Band letter to dwelling (or unit) count. Absent bands count as zero.
    mandated_band
        The minimum band the policy requires.
    bands
        Best-to-worst ordering, e.g. ``("A", ..., "G")``.

    Returns
    -------
    float
        Share in [0, 1]. Zero when the stock is empty, which is the correct
        answer for a firm holding no dwellings rather than a missing value.
    """
    threshold = band_index(mandated_band, bands)
    total = sum(max(count, 0.0) for count in stock.values())
    if total <= 0:
        return 0.0
    below = sum(
        max(count, 0.0)
        for band, count in stock.items()
        if band_index(band, bands) > threshold
    )
    return float(below / total)


def _collect_stock(
    attributes: Mapping[str, FirmAttribute], prefix: str, bands: Sequence[str]
) -> dict[str, float]:
    """Pull a band profile out of the attribute map by prefix."""
    profile: dict[str, float] = {}
    for band in bands:
        key = f"{prefix}{band}"
        if key in attributes:
            profile[band] = attributes[key].value
    return profile


def residential_stock_magnitude(
    attributes: Mapping[str, FirmAttribute],
    target: PolicyTarget,
    bands: Sequence[str],
) -> tuple[float, tuple[str, ...]] | None:
    """Dose for a residential landlord or REIT, for the tenure the policy binds.

    **Gated on ``target.scope``** (see :data:`STOCK_PREFIXES_BY_SCOPE`). A
    private-rented landlord is not reached by a social-rented mandate and a
    social housing REIT is not reached by the PRS track, so each scores against
    the band profile of its own tenure and a measured zero against the other.
    Before 2026-08-17 scope was ignored and both scored fully against both.

    Under ``all_domestic`` the tenure profiles are summed with the generic one,
    which is the correct reading of an instrument that reaches every tenure.

    Returns ``None`` when the channel does not apply: either the scope does not
    reach residential landlords at all, or the firm discloses no band profile
    for the tenure in question. That is not the same as a dose of zero, and
    `docs/exposure_construction.md` section 3 turns on the difference.
    """
    prefixes = STOCK_PREFIXES_BY_SCOPE.get(target.scope)
    if prefixes is None:
        return None

    profile: dict[str, float] = {}
    used: list[str] = []
    for prefix in prefixes:
        for band, count in _collect_stock(attributes, prefix, bands).items():
            profile[band] = profile.get(band, 0.0) + count
            used.append(f"{prefix}{band}")
    if not profile:
        return None
    return share_below_band(profile, target.mandated_min_band, bands), tuple(used)


def delivered_stock_magnitude(
    attributes: Mapping[str, FirmAttribute],
    target: PolicyTarget,
    bands: Sequence[str],
    *,
    prefix: str = "delivered_units_band_",
) -> tuple[float, tuple[str, ...]] | None:
    """Dose for a housebuilder.

    Combines the band profile of delivered stock with the gap between the
    firm's current build standard and the mandated one. Where the firm
    discloses a build standard, that gap **caps** the dose: a builder already
    delivering at or above the mandate faces no compliance cost regardless of
    what its historic delivered profile looks like.

    **Gated on ``target.scope``: only ``NEW_BUILD`` reaches a housebuilder.**
    A minimum-EPC mandate on let property is an obligation on the holder of the
    stock, not on whoever built it. The channel is retired in any case
    (`reports/decision_log.md`, 2026-08-16) because no new-build instrument
    states a mandated band, so this gate is belt and braces rather than load
    bearing today.
    """
    if target.scope is not Scope.NEW_BUILD:
        return None
    profile = _collect_stock(attributes, prefix, bands)
    if not profile:
        return None
    used = [f"{prefix}{band}" for band in profile]
    magnitude = share_below_band(profile, target.mandated_min_band, bands)

    standard = attributes.get(BUILD_STANDARD_ATTRIBUTE)
    if standard is not None:
        used.append(BUILD_STANDARD_ATTRIBUTE)
        # `value` holds the band's index in the best-to-worst ordering, so a
        # smaller number is a better standard. The curator records it that way
        # because a CSV cell cannot hold a letter and a number in one column.
        current = int(standard.value)
        mandated = band_index(target.mandated_min_band, bands)
        if current <= mandated:
            magnitude = 0.0

    return magnitude, tuple(used)


def product_revenue_magnitude(
    attributes: Mapping[str, FirmAttribute],
    target: PolicyTarget,
    *,
    prefix: str = "revenue_share_",
) -> tuple[float, tuple[str, ...]] | None:
    """Dose for a building-products, insulation or heating manufacturer.

    Revenue share in the affected categories multiplied by UK revenue share.
    Both terms matter: a firm with a large insulation business and no UK
    revenue has no *UK* policy exposure, and a firm with 100% UK revenue and
    no insulation line has none either.

    A missing `uk_revenue_share` is treated as unknown and returns ``None``
    rather than defaulting to 1.0 -- defaulting would hand every foreign
    manufacturer full UK exposure.
    """
    shares = {
        name.removeprefix(prefix): attribute
        for name, attribute in attributes.items()
        if name.startswith(prefix)
    }
    if not shares:
        return None

    affected = {category.strip().lower() for category in target.affected_categories}
    matched = {
        category: attribute
        for category, attribute in shares.items()
        if category.lower() in affected
    }
    if not matched:
        # The firm discloses revenue shares but none in the affected
        # categories: a measured zero, not an inapplicable channel.
        return 0.0, tuple(f"{prefix}{category}" for category in shares)

    uk_share = attributes.get(UK_SHARE_ATTRIBUTE)
    if uk_share is None:
        return None

    total = sum(max(attribute.value, 0.0) for attribute in matched.values())
    magnitude = min(total, 1.0) * max(min(uk_share.value, 1.0), 0.0)
    used = (*(f"{prefix}{category}" for category in matched), UK_SHARE_ATTRIBUTE)
    return float(magnitude), used


def domestic_supply_magnitude(
    attributes: Mapping[str, FirmAttribute],
) -> tuple[float, tuple[str, ...]] | None:
    """Dose for a utility or energy retailer."""
    supply = attributes.get(DOMESTIC_SUPPLY_ATTRIBUTE)
    if supply is None:
        return None
    return float(max(min(supply.value, 1.0), 0.0)), (DOMESTIC_SUPPLY_ATTRIBUTE,)
