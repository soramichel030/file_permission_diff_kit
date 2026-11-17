"""Public API for file_permission_diff_kit.

Exports the small surface used to compare file modes and ownership between two
directory trees.  Keeping the package name and the exported names stable is the
whole point of this module; everything else lives in :mod:`core`.
"""

from .core import (
    Entry,
    Diff,
    compare,
    compare_trees,
    format_diff,
)

__all__ = [
    "Entry",
    "Diff",
    "compare",
    "compare_trees",
    "format_diff",
]
