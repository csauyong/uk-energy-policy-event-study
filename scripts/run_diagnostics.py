"""Run the diagnostic battery against the stacked CAR panel.

Run with ``make diagnostics``, after ``make estimate``.

`reporting/dose_response.py` raises `MissingInfluenceError` if a beta reaches
a report without leverage diagnostics beside it. This script produces them,
and it also answers the question the headline regression output does not:

    **How many observations actually identify beta?**

`estimate_dose_response` reports `n_observations` and `n_events`, and both are
honest counts of the rows it fitted. Neither tells you that a row whose
exposure is exactly zero contributes nothing to the exposure gradient beyond
pinning the event fixed effect. When the exposed set is small relative to the
panel, the nominal N and the identifying N diverge by orders of magnitude, and
a reader who sees only the first will badly over-read the result.

So this script counts the identifying rows explicitly and prints them beside
the nominal ones. That comparison is required content in `reports/results.md`.
"""

from __future__ import annotations

import json

import pandas as pd

from policy_event_study.diagnostics.influence import (
    influence_report,
    leverage_report,
)
from policy_event_study.estimators.dose_response import (
    WeightScheme,
    estimate_dose_response,
)
from policy_event_study.paths import REPORTS_DIR

EXPOSURE_COLUMN = "exposure_continuous"
TABLES = REPORTS_DIR / "tables"


def identifying_structure(frame: pd.DataFrame) -> dict[str, object]:
    """Count what actually carries identifying information.

    An event whose firms all score the same exposure contributes a fixed
    effect and nothing else: within that event there is no gradient to fit.
    A row whose exposure is exactly zero is one of the many that pin the
    fixed effect. Neither is useless -- but neither is what the reader means
    when they see "n = 682".
    """
    spread = frame.groupby("event_id")[EXPOSURE_COLUMN].std(ddof=1).fillna(0.0)
    identifying_events = spread.loc[spread > 1e-12].index
    non_zero = frame.loc[frame["exposure_magnitude"].abs() > 0]
    per_event = (
        non_zero.groupby("event_id")["unit_id"].nunique().sort_values(ascending=False)
    )
    return {
        "nominal_rows": len(frame),
        "nominal_events": int(frame["event_id"].nunique()),
        "nominal_clusters": int(frame["cluster_id"].nunique()),
        "nominal_firms": int(frame["unit_id"].nunique()),
        "identifying_events": len(identifying_events),
        "identifying_clusters": int(
            frame.loc[
                frame["event_id"].isin(identifying_events), "cluster_id"
            ].nunique()
        ),
        "non_zero_exposure_rows": len(non_zero),
        "exposed_firms": sorted(non_zero["unit_id"].unique().tolist()),
        "events_with_one_exposed_firm": int((per_event == 1).sum()),
        "events_with_two_or_more_exposed_firms": int((per_event >= 2).sum()),
        "max_exposed_firms_at_any_event": int(per_event.max()) if len(per_event) else 0,
    }


def _exposure_leverage(frame: pd.DataFrame) -> pd.DataFrame:
    """Per-row weight on beta, via Frisch-Waugh-Lovell.

    Regress the exposure column on everything else in the design -- the event
    dummies and the controls -- and keep the residual. OLS on that residual
    alone reproduces beta exactly, and each row's contribution is proportional
    to the square of its residual. Rows whose exposure is fully explained by
    their event dummy contribute nothing, which is precisely what a panel of
    zeros does.
    """
    import numpy as np

    working = frame.dropna(
        subset=[EXPOSURE_COLUMN, "car", "size", "momentum", "pre_event_vol"]
    ).copy()
    dummies = pd.get_dummies(working["event_id"], prefix="event", dtype=float)
    design = pd.concat(
        [working[["size", "momentum", "pre_event_vol"]].astype(float), dummies],
        axis=1,
    ).to_numpy(dtype=float)
    target = working[EXPOSURE_COLUMN].to_numpy(dtype=float)
    coefficients, *_ = np.linalg.lstsq(design, target, rcond=None)
    residual = target - design @ coefficients
    working["weight"] = residual**2
    return working[
        ["unit_id", "event_id", EXPOSURE_COLUMN, "car", "weight"]
    ].sort_values("weight", ascending=False, ignore_index=True)


def main() -> int:
    """Print the identification structure, then the influence battery."""
    frame = pd.read_csv(TABLES / "car_panel.csv")
    n_clusters = int(frame["cluster_id"].nunique())
    scheme = WeightScheme.WEBB if n_clusters < 12 else WeightScheme.RADEMACHER

    structure = identifying_structure(frame)
    print("=== what actually identifies beta ===")
    for key, value in structure.items():
        print(f"  {key:38s} {value}")

    print("\n=== leverage ===")
    leverage = leverage_report(frame, exposure_column=EXPOSURE_COLUMN)
    print(
        f"  effective firms          {leverage.effective_firms:.2f} of "
        f"{leverage.nominal_firms:.0f} nominal"
    )
    print(f"  leverage share, top 1%   {leverage.leverage_share_top_1pct:.3f}")
    print(f"  leverage share, top 5%   {leverage.leverage_share_top_5pct:.3f}")
    print(f"  max Cook's distance      {leverage.max_cooks:,.1f}")
    print(f"  rows above the threshold {leverage.n_cooks_above_threshold}")

    # The hat value above is leverage on the WHOLE design, and every row loads
    # on its event dummy, so it is dominated by the fixed effects and looks
    # reassuringly even. Leverage on BETA specifically is what matters, and by
    # Frisch-Waugh-Lovell it is proportional to the squared residual of the
    # exposure column after the other regressors are partialled out. That is
    # the number that says how few rows the gradient rests on.
    print("\n=== leverage on beta specifically (Frisch-Waugh-Lovell) ===")
    beta_leverage = _exposure_leverage(frame)
    total = float(beta_leverage["weight"].sum())
    top = beta_leverage.head(10)
    print(
        f"  top 10 rows carry {top['weight'].sum() / total:.1%} of the weight on beta"
    )
    print(top.to_string(index=False))
    effective_rows = (
        float(total**2 / (beta_leverage["weight"] ** 2).sum())
        if total > 0
        else float("nan")
    )
    print(
        f"\n  effective identifying rows {effective_rows:.1f} of {len(frame)} nominal"
    )
    structure["effective_identifying_rows"] = round(effective_rows, 2)
    structure["top10_share_of_beta_weight"] = round(
        float(top["weight"].sum() / total), 4
    )

    print("\n=== influence battery: the drop path ===")
    report = influence_report(frame, scheme=scheme, exposure_column=EXPOSURE_COLUMN)
    print(f"  baseline beta {report.baseline_beta:+.6f}  p {report.baseline_p:.3f}")
    for step in report.drop_path:
        beta = "not identified" if step.beta != step.beta else f"{step.beta:+.6f}"
        print(
            f"  drop {step.k}: {', '.join(step.dropped_units):32s} "
            f"beta {beta:>16s}   n {step.n_observations}"
        )
    print(
        f"  winsorised beta {report.winsorised_beta:+.6f}  p {report.winsorised_p:.3f}"
    )
    print(
        f"  continuous {report.continuous_beta:+.6f} vs rank "
        f"{report.rank_beta:+.6f}  (rank correlation {report.rank_correlation:.3f})"
    )
    for note in report.notes:
        print(f"  NOTE: {note}")

    print("\n=== leave-one-event-out ===")
    baseline = estimate_dose_response(
        frame, scheme=scheme, exposure_column=EXPOSURE_COLUMN, randomisation_draws=1
    )
    rows = []
    for event_id in sorted(frame["event_id"].unique()):
        reduced = frame.loc[frame["event_id"] != event_id]
        try:
            fit = estimate_dose_response(
                reduced,
                scheme=scheme,
                exposure_column=EXPOSURE_COLUMN,
                randomisation_draws=1,
                bootstrap_draws=200,
            )
        except ValueError as exc:
            rows.append(
                {
                    "dropped": event_id,
                    "beta": float("nan"),
                    "shift_vs_baseline": float("nan"),
                    "note": str(exc)[:60],
                }
            )
            continue
        rows.append(
            {
                "dropped": event_id,
                "beta": fit.beta,
                "shift_vs_baseline": fit.beta - baseline.beta,
                "note": "",
            }
        )
    loo = pd.DataFrame(rows).sort_values("shift_vs_baseline", key=abs, ascending=False)
    print(loo.to_string(index=False))

    TABLES.mkdir(parents=True, exist_ok=True)
    loo.to_csv(TABLES / "leave_one_event_out.csv", index=False)
    (TABLES / "identification.json").write_text(
        json.dumps(structure, indent=2), encoding="utf-8"
    )
    print(f"\nwritten to {TABLES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
