"""Universe configuration and price panels.

Same contract as Project A: typed signatures, source URL + licence + vintage
in every docstring, UTC timestamps.

`universe.py`
    Parses `config/universe.yaml` and *enforces* the constraints written in
    its `notes:` block -- clock alignment, interference exclusions, donor-pool
    size, the ban on price levels as a matching variable.
`prices.py`
    Daily equity returns. Network access (`fetch_prices`) is separated from
    panel construction (`build_panel`) so every point-in-time decision --
    corporate-action adjustment, cross-market clock alignment, liquidity
    screening, calendar intersection -- is pure and testable offline.
"""
