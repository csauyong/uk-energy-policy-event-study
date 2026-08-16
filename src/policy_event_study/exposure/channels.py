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

from policy_event_study.exposure.schema import FirmAttribute, PolicyTarget

#: Attribute name for a firm's own build standard, as an EPC band.
BUILD_STANDARD_ATTRIBUTE: Final[str] = "build_standard_band"
UK_SHARE_ATTRIBUTE: Final[str] = "uk_revenue_share"
DOMESTIC_SUPPLY_ATTRIBUTE: Final[str] = "domestic_supply_share_gb"


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
    *,
    prefix: str = "dwellings_band_",
) -> tuple[float, tuple[str, ...]] | None:
    """Dose for a residential landlord or REIT.

    Returns ``None`` when the firm has no dwelling profile at all -- meaning
    the channel does not apply, not that the dose is zero.
    """
    profile = _collect_stock(attributes, prefix, bands)
    if not profile:
        return None
    used = tuple(f"{prefix}{band}" for band in profile)
    return share_below_band(profile, target.mandated_min_band, bands), used


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
    """
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
