"""Synthetic control, synthetic DiD, and the market-model baseline.

The market-model abnormal-return estimator is a required comparator for every
headline result, not an optional extra: `reporting.run_event` includes it
whether or not the caller asks for it.

All three implement one interface, `base.EventStudyEstimator.estimate(panel,
spec, treated_unit)`. That is what makes the diagnostics estimator-agnostic --
an in-space placebo is the same call with a donor passed as `treated_unit` --
and what lets the baseline receive the same permutation inference as the
fancier estimators, so the comparison is like-for-like.
"""
