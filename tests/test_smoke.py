"""Smoke test: the package imports.

Real tests arrive with real code. This file exists so `make test` is
green from commit one.
"""

from __future__ import annotations

import policy_event_study


def test_package_imports() -> None:
    assert policy_event_study.__version__
