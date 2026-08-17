"""Leak tests. `CLAUDE.md` §2 and §3, asserted rather than assumed.

Everything here carries the `pointintime` marker. Per `pyproject.toml`, these
are never skipped.

The central technique is perturbation: change data the estimator must not have
used, and assert that nothing it produced moves. A leak is precisely the case
where it does. This catches the failure mode a code review misses, because the
leak is usually an indexing accident rather than a visibly wrong line.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from policy_event_study.data.prices import ReturnPanel
from policy_event_study.estimators.base import EventSpec
from policy_event_study.estimators.market_model import MarketModelEstimator
from policy_event_study.estimators.synthetic_control import SyntheticControlEstimator
from policy_event_study.estimators.synthetic_did import SyntheticDiDEstimator
from tests.conftest import make_panel, make_spec

pytestmark = pytest.mark.pointintime

SRC = Path(__file__).resolve().parents[1] / "src"


def perturb_post(panel: ReturnPanel, spec: EventSpec, *, seed: int = 99) -> ReturnPanel:
    """Return a copy with every post-event return replaced by noise."""
    windows = spec.resolve(panel.trading_days)
    rng = np.random.default_rng(seed)
    returns = panel.returns.copy()
    block = returns.loc[windows.post_days]
    returns.loc[windows.post_days] = rng.normal(0.05, 0.05, size=block.shape)
    return ReturnPanel(
        returns=returns,
        market=panel.market,
        provenance=panel.provenance,
        outcome_kind=panel.outcome_kind,
    )


# -- weights and fit must not see the future -------------------------------


def test_sc_weights_are_blind_to_post_event_returns() -> None:
    """Donor weights are fit on the pre-window only (`CLAUDE.md` §3)."""
    panel = make_panel()
    spec = make_spec(panel)
    estimator = SyntheticControlEstimator()

    original = estimator.estimate(panel, spec, "TREATED")
    perturbed = estimator.estimate(perturb_post(panel, spec), spec, "TREATED")

    pd.testing.assert_series_equal(original.weights, perturbed.weights)
    assert original.pre_rmspe == pytest.approx(perturbed.pre_rmspe, rel=1e-12)
    # ...and the effect *does* move, or the perturbation did nothing and the
    # test above would pass vacuously.
    assert original.tau != pytest.approx(perturbed.tau)


def test_sdid_unit_weights_are_blind_to_treated_post_returns() -> None:
    """SDiD reads donor post-periods for the time weights, never the treated unit's."""
    panel = make_panel()
    spec = make_spec(panel)
    estimator = SyntheticDiDEstimator()
    windows = spec.resolve(panel.trading_days)

    returns = panel.returns.copy()
    rng = np.random.default_rng(5)
    returns.loc[windows.post_days, "TREATED"] += rng.normal(
        0.05, 0.02, size=len(windows.post_days)
    )
    perturbed = ReturnPanel(
        returns=returns,
        market=panel.market,
        provenance=panel.provenance,
        outcome_kind=panel.outcome_kind,
    )

    original = estimator.estimate(panel, spec, "TREATED")
    moved = estimator.estimate(perturbed, spec, "TREATED")
    pd.testing.assert_series_equal(original.weights, moved.weights)
    assert original.extras["level_shift"] == pytest.approx(
        moved.extras["level_shift"], rel=1e-10
    )


def test_market_model_coefficients_are_blind_to_post_event_returns() -> None:
    panel = make_panel()
    spec = make_spec(panel)
    estimator = MarketModelEstimator()

    original = estimator.estimate(panel, spec, "TREATED")
    perturbed = estimator.estimate(perturb_post(panel, spec), spec, "TREATED")

    assert original.extras["alpha"] == pytest.approx(
        perturbed.extras["alpha"], rel=1e-12
    )
    assert original.extras["beta"] == pytest.approx(perturbed.extras["beta"], rel=1e-12)


def test_perturbing_the_pre_window_does_move_the_fit() -> None:
    """The control for the tests above: the estimator is not simply inert."""
    panel = make_panel()
    spec = make_spec(panel)
    windows = spec.resolve(panel.trading_days)
    rng = np.random.default_rng(6)

    returns = panel.returns.copy()
    returns.loc[windows.pre_days, "TREATED"] += rng.normal(
        0.0, 0.01, size=len(windows.pre_days)
    )
    perturbed = ReturnPanel(
        returns=returns,
        market=panel.market,
        provenance=panel.provenance,
        outcome_kind=panel.outcome_kind,
    )
    original = SyntheticControlEstimator().estimate(panel, spec, "TREATED")
    moved = SyntheticControlEstimator().estimate(perturbed, spec, "TREATED")
    assert not np.allclose(
        original.weights.to_numpy(),
        moved.weights.reindex(original.weights.index).to_numpy(),
    )


# -- the embargo is real ---------------------------------------------------


def test_embargo_days_are_excluded_from_fitting() -> None:
    """Perturbing the embargo must not move the weights; it must move the effect."""
    panel = make_panel()
    spec = make_spec(panel, gap=15)
    windows = spec.resolve(panel.trading_days)
    rng = np.random.default_rng(8)

    returns = panel.returns.copy()
    returns.loc[windows.gap_days, "TREATED"] += rng.normal(
        0.02, 0.01, size=len(windows.gap_days)
    )
    perturbed = ReturnPanel(
        returns=returns,
        market=panel.market,
        provenance=panel.provenance,
        outcome_kind=panel.outcome_kind,
    )
    estimator = SyntheticControlEstimator()
    original = estimator.estimate(panel, spec, "TREATED")
    moved = estimator.estimate(perturbed, spec, "TREATED")

    pd.testing.assert_series_equal(original.weights, moved.weights)
    assert original.pre_rmspe == pytest.approx(moved.pre_rmspe, rel=1e-12)


def test_tau_is_measured_from_the_eve_of_the_event_not_the_estimation_window() -> None:
    """Embargo-period drift belongs in the pre-trend test, not in the effect."""
    panel = make_panel()
    spec = make_spec(panel, gap=15)
    windows = spec.resolve(panel.trading_days)
    assert windows.baseline_day == windows.gap_days[-1]
    assert windows.baseline_day < windows.t0

    estimate = SyntheticControlEstimator().estimate(panel, spec, "TREATED")
    expected = float(
        estimate.gap.loc[windows.post_days[-1]] - estimate.gap.loc[windows.baseline_day]
    )
    assert estimate.tau == pytest.approx(expected, rel=1e-12)


# -- placebos inherit the discipline --------------------------------------


def test_in_time_placebo_windows_end_before_the_real_event() -> None:
    from policy_event_study.diagnostics.placebo_time import feasible_offsets

    panel = make_panel()
    spec = make_spec(panel)
    days = panel.trading_days
    for offset in feasible_offsets(spec, days, buffer=10):
        fake = spec.shifted(offset, days, label="x")
        windows = fake.resolve(days)
        assert windows.post_days[-1] < spec.t0


def test_leave_one_out_never_reintroduces_the_treated_unit() -> None:
    from policy_event_study.diagnostics.leave_one_out import leave_one_donor_out

    panel = make_panel()
    spec = make_spec(panel)
    result = leave_one_donor_out(SyntheticControlEstimator(), panel, spec, "TREATED")
    assert "TREATED" not in result.taus.index


# -- repository-level guards ----------------------------------------------


def test_no_random_or_kfold_splits_anywhere_in_src() -> None:
    """`CLAUDE.md` §3: no KFold, no ShuffleSplit, no shuffled train/test split.

    A grep rather than a review, because this is the kind of thing that
    arrives later in a notebook-to-module migration and is easy to miss.
    """
    banned = ("KFold", "ShuffleSplit", "shuffle=True", "train_test_split")
    offenders: list[str] = []
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in banned:
            # Skip the line in this file's own docstring if it ever lands here.
            if token in text:
                offenders.append(f"{path.relative_to(SRC)}: {token}")
    assert not offenders, f"random/k-fold splitting found: {offenders}"


def test_no_currency_conversion_of_returns_in_src() -> None:
    """`config/universe.yaml` `notes.fx`: donor returns stay in local currency.

    The only sanctioned FX is the liquidity screen. Assert the rate map is
    referenced in exactly one place, so a future edit that reaches for it in
    the return path shows up here.
    """
    users = [
        path.relative_to(SRC)
        for path in SRC.rglob("*.py")
        if "fx_screen_rates_to_gbp" in path.read_text(encoding="utf-8")
    ]
    assert {str(path) for path in users} == {
        "policy_event_study/data/universe.py",
        "policy_event_study/data/prices.py",
    }


def test_no_feed_data_is_tracked_in_git() -> None:
    """`make data-check`, as a test so it runs in the normal suite too.

    The invariant is not a file whitelist -- that went stale as soon as
    curation produced more artefacts than it started with. It is that **no
    output of a network loader** is committed. Price frames, gov.uk sweep
    dumps and the Commons Library briefing cache are all regenerable from
    `src/` plus a date, and `CLAUDE.md` is explicit that reproducibility comes
    from the loader rather than from checked-in bytes.

    Hand curation is the opposite case and is committed deliberately: the
    a-priori inventory, the leak-search resolutions, the exposure worksheet
    and the event dictionary cannot be regenerated by any loader, and "which
    events were in the study, and when did that change" must be answerable
    from git history.
    """
    root = SRC.parent
    result = subprocess.run(
        ["git", "ls-files", "data/"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:  # not a git checkout; nothing to assert
        pytest.skip("not a git repository")

    tracked = [
        line
        for line in result.stdout.splitlines()
        if line and not line.endswith(".gitkeep")
    ]

    # Anything a loader pulls from a feed, by directory or by filename shape.
    feed_prefixes = ("data/raw/", "data/interim/", "data/processed/")
    feed_patterns = ("govuk_sweep_", "govuk_shortlist_", "briefing_cache/")

    offenders = [
        path
        for path in tracked
        if path.startswith(feed_prefixes)
        or any(pattern in path for pattern in feed_patterns)
    ]
    assert not offenders, f"network-loader output is tracked: {offenders}"


def test_curated_inputs_are_tracked_not_ignored() -> None:
    """The converse: hand curation must NOT be gitignored.

    A curated file silently excluded from version control is worse than a
    tracked feed dump. The feed dump wastes space; the curated file loses the
    audit trail that makes the event list defensible, and nothing would fail
    to warn you.
    """
    root = SRC.parent
    required = [
        "data/events/uk_energy_policy_events.csv",
        "data/events/inventory_apriori_2026-08-16.yaml",
        "data/events/date_resolutions_2026-08-16.yaml",
        "data/events/shortlist_manual.yaml",
        "data/exposure/firm_attributes.csv",
        "data/exposure/policy_targets.csv",
    ]
    present = [path for path in required if (root / path).exists()]
    result = subprocess.run(
        ["git", "ls-files", "data/"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip("not a git repository")
    tracked = set(result.stdout.splitlines())
    untracked = [path for path in present if path not in tracked]
    assert not untracked, f"curated input is not tracked: {untracked}"
