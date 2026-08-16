"""Placebo tests, pre-trend checks, donor-pool sensitivity, power.

In-space placebos, in-time placebos, leave-one-out donor tests and
pre-treatment fit RMSPE are computed for every reported effect;
`reporting.EventResult` refuses to construct without them.

`power.py` answers the question a null result is meaningless without: how
large an effect could this design actually have detected? It reports the
arithmetic floor on the p-value (`1/(J+1)`), the minimum detectable effect
against the placebo distribution, and the effective independent observation
count once cross-sectional correlation is accounted for.
"""
