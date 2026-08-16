r"""The mandate-versus-repeal falsification test, made executable.

Anchoring exposure sign to policy *direction* rather than to the individual
event buys a falsification test for free. It has been a design property
described in prose; this module runs it.

The prediction
--------------
On the **direction-neutral** exposure measure -- ``exposure_channel_signed``,
which is ``magnitude x channel_sign`` without the tighten/loosen multiplier --
a mandate and its repeal must move exposed firms in **opposite** directions.
An insulation manufacturer gains when a standard is tightened and loses when
it is repealed. So:

.. math:: \operatorname{sign}(\beta_{\text{tighten}})
          \neq \operatorname{sign}(\beta_{\text{loosen}})

Equivalently, on ``exposure_signed`` -- where the direction multiplier is
already folded in -- the two subsamples should give the **same** sign. Both
framings are computed; they are the same test and agreement between them is a
consistency check on the panel construction rather than evidence.

What a failure means
--------------------
**If the signs agree on the direction-neutral measure, the exposure
construction is measuring something other than policy exposure**, and the
report must say so plainly rather than reporting the pooled beta as though the
check had passed. The most likely culprits, in order:

* exposure proxies for a persistent firm characteristic -- small-cap
  building-products names are riskier in every state of the world, so they
  earn a return premium on any date, mandate or repeal;
* the direction coding is wrong for one or more events;
* the events are not what they claim: a "repeal" that mostly signalled
  continued subsidy elsewhere is not the mirror image of a mandate.

This is a **pre-registered falsification check, not a subgroup analysis.** It
is specified before estimation, both subsamples are reported whatever they
show, and a pass is not evidence for the pooled result -- it is only the
absence of one specific disconfirmation.

Power
-----
Splitting the sample halves the events on each side and, since the MDE scales
with the event count rather than the cross-section, roughly multiplies each
subsample's minimum detectable effect by :math:`\sqrt 2`. With single-digit
event counts a *failure to find opposite signs* is therefore weak evidence,
and :class:`SignConsistencyResult` carries each side's own p-value floor so an
underpowered pass cannot be read as a strong one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd

from policy_event_study.estimators.dose_response import (
    DEFAULT_CONTROLS,
    WeightScheme,
    bootstrap_p_floor,
    estimate_dose_response,
)
from policy_event_study.events.schema import PolicyDirection

#: The direction-neutral exposure column the test runs on.
NEUTRAL_EXPOSURE: Final[str] = "exposure_channel_signed"


@dataclass(frozen=True)
class SignConsistencyResult:
    """Betas on the tightening and loosening subsamples, and the verdict."""

    beta_tighten: float
    beta_loosen: float
    p_tighten: float
    p_loosen: float
    p_floor_tighten: float
    p_floor_loosen: float
    n_events_tighten: int
    n_events_loosen: int
    n_obs_tighten: int
    n_obs_loosen: int
    exposure_column: str
    weight_scheme: WeightScheme

    @property
    def signs_oppose(self) -> bool:
        """True when the two betas have opposite signs, as predicted."""
        if not (np.isfinite(self.beta_tighten) and np.isfinite(self.beta_loosen)):
            return False
        if self.beta_tighten == 0 or self.beta_loosen == 0:
            return False
        return bool(np.sign(self.beta_tighten) != np.sign(self.beta_loosen))

    @property
    def both_sides_detectable(self) -> bool:
        """True when each subsample can reach 5% at all."""
        return bool(self.p_floor_tighten <= 0.05 and self.p_floor_loosen <= 0.05)

    @property
    def underpowered(self) -> bool:
        """True when either side is too thin to make a failure informative."""
        return (
            self.n_events_tighten < 2
            or self.n_events_loosen < 2
            or not self.both_sides_detectable
        )

    @property
    def passes(self) -> bool:
        """Whether the falsification check passes.

        A pass requires opposite signs. It is *not* evidence for the pooled
        beta -- only the absence of one specific disconfirmation.
        """
        return self.signs_oppose

    def verdict(self) -> str:
        """Plain-language reading, for the report."""
        if self.n_events_tighten == 0 or self.n_events_loosen == 0:
            missing = "loosening" if self.n_events_loosen == 0 else "tightening"
            return (
                f"NOT RUN: the curated events contain no {missing} announcements, "
                "so the falsification test cannot be evaluated. The pooled beta "
                "must be read without it, and that limitation stated."
            )
        if self.underpowered:
            return (
                f"UNDERPOWERED: {self.n_events_tighten} tightening and "
                f"{self.n_events_loosen} loosening event(s). Splitting the sample "
                "leaves each side unable to reach 5%, so a failure to find "
                "opposite signs is weak evidence either way. Report the betas, "
                "not the verdict."
            )
        if self.passes:
            return (
                f"PASSES: beta is {self.beta_tighten:+.4f} on tightening events "
                f"and {self.beta_loosen:+.4f} on loosening events. Opposite "
                "signs, as the exposure construction predicts. This is the "
                "absence of a specific disconfirmation, not evidence for the "
                "pooled estimate."
            )
        return (
            f"FAILS: beta is {self.beta_tighten:+.4f} on tightening events and "
            f"{self.beta_loosen:+.4f} on loosening events -- the same sign, where "
            "the construction predicts opposite. The exposure measure is "
            "capturing something other than policy exposure: most likely a "
            "persistent firm characteristic that earns a premium on any date, a "
            "mis-coded direction, or events that are not mirror images. The "
            "pooled beta must not be reported as though this check had passed."
        )

    def summary(self) -> pd.Series:
        """One-line summary for a report table."""
        return pd.Series(
            {
                "beta_tighten": self.beta_tighten,
                "beta_loosen": self.beta_loosen,
                "p_tighten": self.p_tighten,
                "p_loosen": self.p_loosen,
                "p_floor_tighten": self.p_floor_tighten,
                "p_floor_loosen": self.p_floor_loosen,
                "n_events_tighten": self.n_events_tighten,
                "n_events_loosen": self.n_events_loosen,
                "signs_oppose": self.signs_oppose,
                "underpowered": self.underpowered,
                "passes": self.passes,
            }
        )


def sign_consistency(
    frame: pd.DataFrame,
    *,
    scheme: WeightScheme,
    exposure_column: str = NEUTRAL_EXPOSURE,
    controls: Sequence[str] = DEFAULT_CONTROLS,
    seed: int = 20260815,
    bootstrap_draws: int = 1000,
) -> SignConsistencyResult:
    """Estimate beta separately on tightening and loosening events.

    Parameters
    ----------
    frame
        Firm x event panel with a `direction` column carrying
        :class:`~policy_event_study.events.schema.PolicyDirection` values.
    exposure_column
        Defaults to the **direction-neutral** measure, where the prediction is
        opposite signs. Pass `exposure_signed` to run the equivalent
        same-sign framing.
    scheme
        Bootstrap weight scheme; required, no default. `WEBB` is the right
        choice here in particular, because splitting the sample halves the
        cluster count on each side and Rademacher's floor rises steeply.

    Raises
    ------
    ValueError
        If `direction` is absent. It is a required event-dictionary column
        precisely so this test cannot be skipped by omission.
    """
    if "direction" not in frame.columns:
        msg = (
            "frame has no `direction` column. It is a required column of the "
            "event dictionary so that the mandate-versus-repeal falsification "
            "test cannot be skipped by omitting it"
        )
        raise ValueError(msg)

    sides: dict[PolicyDirection, tuple[float, float, float, int, int]] = {}
    for direction in PolicyDirection:
        subset = frame[frame["direction"].astype(str) == str(direction)]
        n_events = int(subset["event_id"].nunique()) if len(subset) else 0
        if n_events == 0:
            sides[direction] = (float("nan"), float("nan"), 1.0, 0, 0)
            continue
        try:
            result = estimate_dose_response(
                subset,
                scheme=scheme,
                exposure_column=exposure_column,
                controls=controls,
                seed=seed,
                bootstrap_draws=bootstrap_draws,
                randomisation_draws=1,
            )
        except ValueError:
            # No within-event variation on this side: not estimable, and that
            # is a reportable state rather than an error to swallow silently.
            sides[direction] = (
                float("nan"),
                float("nan"),
                bootstrap_p_floor(scheme, n_events, bootstrap_draws),
                n_events,
                len(subset),
            )
            continue
        sides[direction] = (
            result.beta,
            result.p_wild_bootstrap,
            result.p_floor_bootstrap,
            n_events,
            result.n_observations,
        )

    tighten = sides[PolicyDirection.TIGHTEN]
    loosen = sides[PolicyDirection.LOOSEN]
    return SignConsistencyResult(
        beta_tighten=tighten[0],
        beta_loosen=loosen[0],
        p_tighten=tighten[1],
        p_loosen=loosen[1],
        p_floor_tighten=tighten[2],
        p_floor_loosen=loosen[2],
        n_events_tighten=tighten[3],
        n_events_loosen=loosen[3],
        n_obs_tighten=tighten[4],
        n_obs_loosen=loosen[4],
        exposure_column=exposure_column,
        weight_scheme=scheme,
    )
