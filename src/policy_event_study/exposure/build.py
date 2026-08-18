"""Assemble exposure scores: load, validate, apply point-in-time, standardise.

Pipeline, and the order is the point:

1. read the curated attributes and policy targets;
2. **drop every attribute not knowable at the announcement timestamp**;
3. keep the freshest knowable vintage of each (unit, attribute);
4. run the channels to a magnitude in [0, 1];
5. sign it: ``magnitude * channel_sign * event_direction``;
6. winsorise, then standardise cross-sectionally **within each event**;
7. also produce the decile-rank variant.

Step 6 is within-event by construction. Standardising across the pooled sample
would let a large-dispersion event dominate the pooled coefficient, and the
event fixed effect in the dose-response regression already assumes exposure is
measured on a comparable scale inside each event.

Both variants are pre-registered in `config/exposure.yaml`:
``exposure_continuous`` is the standardised signed score, ``exposure_rank`` its
decile rank. The rank variant is insensitive to the shape of the scoring
function -- if the two disagree, the functional form is doing the work.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
import yaml

from policy_event_study.exposure.channels import (
    delivered_stock_magnitude,
    domestic_supply_magnitude,
    product_revenue_magnitude,
    residential_stock_magnitude,
)
from policy_event_study.exposure.schema import (
    ATTRIBUTE_COLUMNS,
    LIST_SEPARATOR,
    POLICY_TARGET_COLUMNS,
    Direction,
    ExposureIssue,
    ExposureReport,
    ExposureScore,
    ExposureValidationError,
    FirmAttribute,
    PolicyTarget,
    Scope,
    filter_knowable,
    latest_by_attribute,
)
from policy_event_study.paths import PROJECT_ROOT

EXPOSURE_CONFIG: Final[Path] = PROJECT_ROOT / "config" / "exposure.yaml"
EXPOSURE_DIR: Final[Path] = PROJECT_ROOT / "data" / "exposure"
FIRM_ATTRIBUTES_CSV: Final[Path] = EXPOSURE_DIR / "firm_attributes.csv"
POLICY_TARGETS_CSV: Final[Path] = EXPOSURE_DIR / "policy_targets.csv"


@dataclass(frozen=True)
class ChannelSpec:
    """One channel's configuration, from `config/exposure.yaml`."""

    key: str
    channel_sign: float
    sign_ambiguous: bool
    sign_rationale: str
    description: str


@dataclass(frozen=True)
class ExposureConfig:
    """Parsed `config/exposure.yaml`."""

    bands: tuple[str, ...]
    winsorise_quantiles: tuple[float, float]
    default_magnitude: float
    rank_buckets: int
    channels: Mapping[str, ChannelSpec]
    notes: Mapping[str, str]

    def sign(self, channel: str) -> float:
        """Channel sign under a tightening."""
        return self.channels[channel].channel_sign if channel in self.channels else 0.0

    @property
    def ambiguous_channels(self) -> tuple[str, ...]:
        """Channels whose sign the report must run a sensitivity on."""
        return tuple(key for key, spec in self.channels.items() if spec.sign_ambiguous)


def load_exposure_config(path: Path | None = None) -> ExposureConfig:
    """Parse `config/exposure.yaml`.

    Source: this project's own pre-registered scoring configuration.
    Licence: project's own.
    Vintage: the file, version controlled. Any change is a new specification
        and gets a row in reports/decision_log.md.
    Publication lag: none; a configuration file.
    """
    target = path if path is not None else EXPOSURE_CONFIG
    raw: Mapping[str, Any] = yaml.safe_load(target.read_text(encoding="utf-8"))
    meta = raw["meta"]
    lower, upper = meta["winsorise_quantiles"]
    return ExposureConfig(
        bands=tuple(str(band).upper() for band in meta["epc_bands"]),
        winsorise_quantiles=(float(lower), float(upper)),
        default_magnitude=float(meta["default_magnitude"]),
        rank_buckets=int(meta["rank_buckets"]),
        channels={
            str(key): ChannelSpec(
                key=str(key),
                channel_sign=float(block.get("channel_sign", 0.0)),
                sign_ambiguous=bool(block.get("sign_ambiguous", False)),
                sign_rationale=str(block.get("sign_rationale", "")).strip(),
                description=str(block.get("description", "")).strip(),
            )
            for key, block in raw["channels"].items()
        },
        notes={str(k): str(v).strip() for k, v in raw.get("notes", {}).items()},
    )


# --------------------------------------------------------------------------
# curated inputs
# --------------------------------------------------------------------------


def _blank(value: object) -> bool:
    return value is None or str(value).strip() == ""


def validate_exposure_inputs(
    attributes_frame: pd.DataFrame,
    targets_frame: pd.DataFrame,
    *,
    known_units: Iterable[str] | None = None,
    known_events: Iterable[str] | None = None,
) -> ExposureReport:
    """Validate the curated exposure inputs. Never raises on validation grounds."""
    report = ExposureReport(
        n_attributes=len(attributes_frame), n_targets=len(targets_frame)
    )

    for frame, required, label in (
        (attributes_frame, ATTRIBUTE_COLUMNS, "firm_attributes"),
        (targets_frame, POLICY_TARGET_COLUMNS, "policy_targets"),
    ):
        missing = [column for column in required if column not in frame.columns]
        if missing:
            report.issues.append(
                ExposureIssue(
                    0, ",".join(missing), f"{label}: columns absent {missing}"
                )
            )
    if not report.ok:
        return report

    unit_whitelist = set(known_units) if known_units is not None else None
    event_whitelist = set(known_events) if known_events is not None else None

    for position, (_, row) in enumerate(attributes_frame.iterrows()):
        row_no = position + 2
        for column in ("unit_id", "attribute", "source_url", "vintage"):
            if _blank(row[column]):
                report.issues.append(
                    ExposureIssue(row_no, column, "missing; required for provenance")
                )
        try:
            float(str(row["value"]).strip())
        except (TypeError, ValueError):
            report.issues.append(
                ExposureIssue(row_no, "value", f"not numeric: {row['value']!r}")
            )
        for column in ("as_of_date", "knowable_from"):
            try:
                pd.Timestamp(str(row[column]).strip())
            except (TypeError, ValueError):
                report.issues.append(
                    ExposureIssue(row_no, column, f"unparseable date {row[column]!r}")
                )
        try:
            as_of = pd.Timestamp(str(row["as_of_date"]).strip())
            knowable = pd.Timestamp(str(row["knowable_from"]).strip())
        except (TypeError, ValueError):
            continue
        if knowable < as_of:
            report.issues.append(
                ExposureIssue(
                    row_no,
                    "knowable_from",
                    (
                        f"knowable_from {knowable.date()} precedes as_of_date "
                        f"{as_of.date()}: a figure cannot be public before the "
                        "period it describes has ended"
                    ),
                )
            )
        elif (knowable - as_of).days > 400:
            report.issues.append(
                ExposureIssue(
                    row_no,
                    "knowable_from",
                    (
                        f"disclosure lag of {(knowable - as_of).days} days is over a "
                        "year; confirm this is the publication date and not a typo"
                    ),
                    fatal=False,
                )
            )
        if (
            unit_whitelist is not None
            and str(row["unit_id"]).strip() not in unit_whitelist
        ):
            report.issues.append(
                ExposureIssue(
                    row_no,
                    "unit_id",
                    f"{row['unit_id']!r} is not in the universe or screening universe",
                )
            )

    for position, (_, row) in enumerate(targets_frame.iterrows()):
        row_no = position + 2
        if (
            event_whitelist is not None
            and str(row["event_id"]).strip() not in event_whitelist
        ):
            report.issues.append(
                ExposureIssue(
                    row_no, "event_id", f"{row['event_id']!r} is not a curated event"
                )
            )
        for column, enum_cls in (("scope", Scope), ("direction", Direction)):
            value = str(row[column]).strip().lower()
            if value not in {member.value for member in enum_cls}:
                report.issues.append(
                    ExposureIssue(
                        row_no,
                        column,
                        f"{value!r} is not one of "
                        f"{[member.value for member in enum_cls]}",
                    )
                )
        if _blank(row["mandated_min_band"]) and _blank(row["affected_categories"]):
            report.issues.append(
                ExposureIssue(
                    row_no,
                    "mandated_min_band",
                    (
                        "neither a mandated band nor an affected category, so no "
                        "channel can score this target: it is SKIPPED and counted "
                        "by build_exposure_panel, not scored as zero. Eight such "
                        "rows are deliberate -- the record of the retired "
                        "delivered_stock exposure, kept so the gap stays visible"
                    ),
                    fatal=False,
                )
            )

    return report


def read_exposure_inputs(
    attributes_path: Path | None = None, targets_path: Path | None = None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Read the curated exposure CSVs as raw strings.

    Source: hand-curated from company annual reports, portfolio disclosures
        and regulatory filings; policy targets from the announcement documents
        recorded in the event dictionary.
    Licence: the underlying filings are the companies' own; the curation --
        the mapping from disclosure to exposure channel -- is this project's
        and is version controlled.
    Vintage: per row, in the `vintage` column. Each row additionally carries
        `knowable_from`, which is what governs use.
    Publication lag: per row, `knowable_from - as_of_date`. Typically ~120
        days for an annual report and the validator warns above 400.
    """
    attributes = attributes_path or FIRM_ATTRIBUTES_CSV
    targets = targets_path or POLICY_TARGETS_CSV
    for path in (attributes, targets):
        if not path.exists():
            msg = (
                f"exposure input not found at {path}. These are hand-curated, not "
                "generated -- see docs/exposure_construction.md"
            )
            raise FileNotFoundError(msg)
    return (
        pd.read_csv(attributes, dtype=str, keep_default_na=False),
        pd.read_csv(targets, dtype=str, keep_default_na=False),
    )


def parse_exposure_inputs(
    attributes_frame: pd.DataFrame,
    targets_frame: pd.DataFrame,
    *,
    known_units: Iterable[str] | None = None,
    known_events: Iterable[str] | None = None,
    strict: bool = True,
) -> tuple[tuple[FirmAttribute, ...], tuple[PolicyTarget, ...], ExposureReport]:
    """Validate and construct the curated exposure inputs."""
    report = validate_exposure_inputs(
        attributes_frame,
        targets_frame,
        known_units=known_units,
        known_events=known_events,
    )
    if strict and not report.ok:
        raise ExposureValidationError(report)

    attributes = tuple(
        FirmAttribute(
            unit_id=str(row["unit_id"]).strip(),
            attribute=str(row["attribute"]).strip(),
            value=float(str(row["value"]).strip()),
            as_of_date=pd.Timestamp(str(row["as_of_date"]).strip()),
            knowable_from=pd.Timestamp(str(row["knowable_from"]).strip()),
            source_url=str(row["source_url"]).strip(),
            vintage=str(row["vintage"]).strip(),
            note=str(row.get("note", "")).strip(),
            confidence=str(row.get("confidence", "")).strip(),
        )
        for _, row in attributes_frame.iterrows()
    )
    targets = tuple(
        PolicyTarget(
            event_id=str(row["event_id"]).strip(),
            mandated_min_band=str(row["mandated_min_band"]).strip().upper(),
            affected_categories=tuple(
                part.strip()
                for part in str(row["affected_categories"]).split(LIST_SEPARATOR)
                if part.strip()
            ),
            scope=Scope(str(row["scope"]).strip().lower()),
            direction=Direction(str(row["direction"]).strip().lower()),
            mechanism=str(row.get("mechanism", "")).strip(),
            note=str(row.get("note", "")).strip(),
        )
        for _, row in targets_frame.iterrows()
    )
    return attributes, targets, report


# --------------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------------


def unscoreable_targets(
    targets: Sequence[PolicyTarget],
) -> tuple[PolicyTarget, ...]:
    """Targets no channel can score, because they name neither band nor category.

    Exposed so a caller can see the gap before building rather than infer it
    from a short panel. `CLAUDE.md` requires `n` to be stated separately for
    the event dictionary and for the dose-response, and this is the difference.
    """
    return tuple(target for target in targets if not target.is_scoreable)


def score_firm(
    unit_id: str,
    attributes: Mapping[str, FirmAttribute],
    target: PolicyTarget,
    config: ExposureConfig,
) -> ExposureScore:
    """Score one firm against one event.

    Channels are tried in order of specificity. A firm matching no channel
    scores an **explicit zero**, which is a data point rather than a missing
    value: zero-exposure firms are what pin down the event fixed effect and
    therefore what makes the cross-sectional design work at all.
    """
    attempts: list[tuple[str, tuple[float, tuple[str, ...]] | None]] = [
        (
            "residential_stock",
            residential_stock_magnitude(attributes, target, config.bands),
        ),
        (
            "delivered_stock",
            delivered_stock_magnitude(attributes, target, config.bands),
        ),
        ("product_revenue", product_revenue_magnitude(attributes, target)),
        ("domestic_supply", domestic_supply_magnitude(attributes)),
    ]

    for channel, outcome in attempts:
        if outcome is None:
            continue
        magnitude, used = outcome
        sign = config.sign(channel)
        return ExposureScore(
            unit_id=unit_id,
            event_id=target.event_id,
            magnitude=float(magnitude),
            signed=float(magnitude * sign * target.direction.multiplier),
            channel=channel,
            channel_sign=sign,
            inputs_used=used,
        )

    return ExposureScore(
        unit_id=unit_id,
        event_id=target.event_id,
        magnitude=config.default_magnitude,
        signed=config.default_magnitude,
        channel="none",
        channel_sign=0.0,
        note="no exposure channel applies; explicit zero, not missing",
    )


def _winsorise(values: pd.Series, quantiles: tuple[float, float]) -> pd.Series:
    """Clip to the given quantiles. One bad row should not drive a regression."""
    lower, upper = values.quantile(quantiles[0]), values.quantile(quantiles[1])
    return values.clip(lower=lower, upper=upper)


def build_exposure_panel(
    units: Sequence[str],
    attributes: Sequence[FirmAttribute],
    targets: Sequence[PolicyTarget],
    announcement_times: Mapping[str, pd.Timestamp],
    config: ExposureConfig,
) -> pd.DataFrame:
    """Build the firm x event exposure panel.

    Parameters
    ----------
    units
        Every unit in the screening universe. Firms with no attributes appear
        with exposure zero, which is the point.
    attributes, targets
        Curated inputs.
    announcement_times
        Event id to tz-aware UTC announcement timestamp. Drives the
        point-in-time filter.
    config
        Parsed `config/exposure.yaml`.

    Returns
    -------
    pd.DataFrame
        One row per unit x event with `exposure_magnitude`, `exposure_signed`,
        `exposure_continuous` (standardised within event), `exposure_rank`
        (decile within event), the channel, and the count of attributes
        withheld by the point-in-time filter.
    """
    rows: list[dict[str, object]] = []
    skipped = unscoreable_targets(targets)
    scoreable = [target for target in targets if target.is_scoreable]
    if targets and not scoreable:
        msg = (
            "every policy target names neither a mandated band nor an affected "
            "category, so no channel can score any of them and the panel would "
            "be empty. This is a curation failure, not a numerical one"
        )
        raise ValueError(msg)

    for target in scoreable:
        announcement = announcement_times.get(target.event_id)
        if announcement is None:
            msg = (
                f"no announcement timestamp for event {target.event_id!r}; exposure "
                "cannot be made point-in-time without one"
            )
            raise KeyError(msg)

        knowable, withheld = filter_knowable(attributes, announcement)
        latest = latest_by_attribute(knowable)
        withheld_by_unit: dict[str, int] = {}
        for attribute in withheld:
            withheld_by_unit[attribute.unit_id] = (
                withheld_by_unit.get(attribute.unit_id, 0) + 1
            )

        for unit in units:
            unit_attributes = {
                attribute_name: attribute
                for (owner, attribute_name), attribute in latest.items()
                if owner == unit
            }
            score = score_firm(unit, unit_attributes, target, config)
            rows.append(
                {
                    "unit_id": unit,
                    "event_id": target.event_id,
                    "channel": score.channel,
                    "channel_sign": score.channel_sign,
                    "direction": str(target.direction),
                    "exposure_magnitude": score.magnitude,
                    "exposure_signed": score.signed,
                    # Direction-neutral: magnitude x channel_sign, WITHOUT the
                    # event's tighten/loosen multiplier. This is the column the
                    # mandate-versus-repeal falsification test runs on, where
                    # the prediction is opposite-signed betas. On
                    # `exposure_signed` the equivalent prediction is
                    # same-signed, because the direction is already folded in.
                    "exposure_channel_signed": score.magnitude * score.channel_sign,
                    "n_inputs": len(score.inputs_used),
                    "n_withheld_not_knowable": withheld_by_unit.get(unit, 0),
                }
            )

    panel = pd.DataFrame(rows)
    # Recorded on the frame rather than logged away: a skipped target leaves no
    # row at all, so a reader counting events in the panel would otherwise see
    # a silent shortfall and have nothing to attribute it to.
    skipped_ids = tuple(dict.fromkeys(target.event_id for target in skipped))
    if panel.empty:
        panel.attrs["unscoreable_event_ids"] = skipped_ids
        panel.attrs["n_unscoreable_targets"] = len(skipped)
        return panel

    # Standardise and rank WITHIN each event. Pooling first would let one
    # high-dispersion event dominate the coefficient.
    def _standardise(group: pd.DataFrame) -> pd.DataFrame:
        signed = _winsorise(group["exposure_signed"], config.winsorise_quantiles)
        spread = float(signed.std(ddof=1))
        group = group.assign(
            exposure_continuous=(
                (signed - signed.mean()) / spread if spread > 0 else 0.0
            ),
            exposure_rank=(
                signed.rank(method="average", pct=True) * config.rank_buckets
            ).apply(np.ceil)
            / config.rank_buckets,
        )
        return group

    standardised = (
        panel.groupby("event_id", group_keys=False)[list(panel.columns)]
        .apply(_standardise)
        .reset_index(drop=True)
    )
    standardised.attrs["unscoreable_event_ids"] = skipped_ids
    standardised.attrs["n_unscoreable_targets"] = len(skipped)
    return standardised


def exposure_dispersion(panel: pd.DataFrame) -> pd.DataFrame:
    """Per-event dispersion of the exposure measure.

    The dose-response design's power depends directly on this: with no
    cross-sectional variation in exposure there is nothing for beta to be
    identified from, however many firms are in the sample. Reported above the
    estimates, alongside the MDE.
    """
    if panel.empty:
        return pd.DataFrame()
    return (
        panel.groupby("event_id")
        .agg(
            n_firms=("unit_id", "count"),
            n_nonzero=("exposure_magnitude", lambda s: int((s != 0).sum())),
            sd_signed=("exposure_signed", lambda s: float(s.std(ddof=1))),
            min_signed=("exposure_signed", "min"),
            max_signed=("exposure_signed", "max"),
        )
        .reset_index()
    )
