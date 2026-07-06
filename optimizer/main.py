"""Compatibility alias for the internal task runner module."""

from __future__ import annotations

import sys

try:
    from . import task_runner as _task_runner
except ImportError:  # pragma: no cover
    import task_runner as _task_runner  # type: ignore

sys.modules[__name__] = _task_runner
