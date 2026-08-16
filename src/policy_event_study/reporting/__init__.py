"""Tables and figures. Deterministic given a seed and a data vintage.

`event_study.py` holds the project's one hard reporting rule as code: no point
estimate is rendered without its placebo distribution, and events with high
anticipation risk, a same-day confounder or a recorded leak are reported
separately and never pooled.
"""
