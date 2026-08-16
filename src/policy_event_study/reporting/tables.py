"""Markdown table rendering.

Deliberately hand-rolled rather than `DataFrame.to_markdown`, which requires
`tabulate` -- an optional pandas dependency that is not in this project's
dependency set and would be a surprising thing for a report to fail on.
"""

from __future__ import annotations

import pandas as pd


def markdown_table(frame: pd.DataFrame, *, floatfmt: str = "{:.4f}") -> str:
    """Render a frame as a GitHub-flavoured markdown table."""
    if frame.empty:
        return "_(no rows)_"
    formatted = frame.copy()
    for column in formatted.columns:
        if pd.api.types.is_float_dtype(formatted[column]):
            formatted[column] = formatted[column].map(
                lambda value: "—" if pd.isna(value) else floatfmt.format(value)
            )
        else:
            formatted[column] = formatted[column].astype(str)
    header = "| " + " | ".join(str(column) for column in formatted.columns) + " |"
    rule = "|" + "|".join("---" for _ in formatted.columns) + "|"
    body = [
        "| " + " | ".join(row) + " |"
        for row in formatted.itertuples(index=False, name=None)
    ]
    return "\n".join([header, rule, *body])
