"""Core comparison logic for file_permission_diff_kit.

The module walks two directory trees and reports entries whose mode or
ownership differ.  Only the standard library is used so the package can run in
locked-down containers.

Design choice: we compare *numeric* mode bits rather than symbolic ones.  The
symbolic representation is lossy (setuid/setgid/sticky bits are easy to drop)
and platform-dependent, so numeric bits are the only representation we can
compare reliably across the trees we care about.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple


@dataclass(frozen=True)
class Entry:
    """A single filesystem entry's permission-relevant metadata.

    ``mode`` is the full ``st_mode`` value as returned by ``os.stat``.  We keep
    the whole value rather than ``st_mode & 0o7777`` so callers can inspect the
    file-type bits if they want; the comparison itself masks to permission bits.
    """

    path: str
    mode: int
    uid: int
    gid: int

    @property
    def permission_bits(self) -> int:
        """Permission and special bits only (no file type)."""
        return self.mode & 0o7777

    @property
    def is_dir(self) -> bool:
        return stat.S_ISDIR(self.mode)


@dataclass(frozen=True)
class Diff:
    """A single difference between the left and right trees.

    ``kind`` is one of ``"mode"``, ``"owner"``, ``"missing_left"`` or
    ``"missing_right"``.  ``left`` and ``right`` hold the entries from each
    side; exactly one of them is ``None`` for the ``missing_*`` kinds.
    """

    path: str
    kind: str
    left: Optional[Entry]
    right: Optional[Entry]

    def describe(self) -> str:
        """Human-readable one-line description of the difference."""
        if self.kind == "missing_left":
            return "%s: missing on left" % self.path
        if self.kind == "missing_right":
            return "%s: missing on right" % self.path
        if self.kind == "mode":
            assert self.left is not None and self.right is not None
            return "%s: mode %04o -> %04o" % (
                self.path,
                self.left.permission_bits,
                self.right.permission_bits,
            )
        if self.kind == "owner":
            assert self.left is not None and self.right is not None
            return "%s: owner %d:%d -> %d:%d" % (
                self.path,
                self.left.uid,
                self.left.gid,
                self.right.uid,
                self.right.gid,
            )
        raise ValueError("unknown diff kind: %r" % (self.kind,))


def _walk(root: str) -> Dict[str, Entry]:
    """Return a mapping of relative path -> Entry for every entry under root.

    Directories are included.  Symlinks are *not* followed: ``os.lstat`` is used
    so a symlink is compared as the link itself, which matches what ``chmod``
    and ``chown`` affect on the link.  The root itself is not included; only its
    contents are, so two trees are compared by their contents rather than by
    the mode of the two roots.
    """
    result: Dict[str, Entry] = {}
    root = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        # Sort for deterministic output; os.walk order is filesystem-dependent.
        dirnames.sort()
        filenames.sort()
        for name in list(dirnames) + list(filenames):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root)
            st = os.lstat(full)
            result[rel] = Entry(
                path=rel,
                mode=st.st_mode,
                uid=st.st_uid,
                gid=st.st_gid,
            )
    return result


def compare_trees(left_root: str, right_root: str) -> List[Diff]:
    """Compare two directory trees and return their permission differences.

    The returned list is sorted by path for deterministic output.  A path that
    exists on only one side produces a ``missing_*`` diff; a path that exists on
    both sides produces a ``mode`` diff, an ``owner`` diff, or both.
    """
    left = _walk(left_root)
    right = _walk(right_root)

    diffs: List[Diff] = []
    all_paths = sorted(set(left) | set(right))
    for path in all_paths:
        l_entry = left.get(path)
        r_entry = right.get(path)
        if l_entry is None:
            diffs.append(Diff(path=path, kind="missing_left", left=None, right=r_entry))
            continue
        if r_entry is None:
            diffs.append(Diff(path=path, kind="missing_right", left=l_entry, right=None))
            continue
        if l_entry.permission_bits != r_entry.permission_bits:
            diffs.append(Diff(path=path, kind="mode", left=l_entry, right=r_entry))
        if (l_entry.uid, l_entry.gid) != (r_entry.uid, r_entry.gid):
            diffs.append(Diff(path=path, kind="owner", left=l_entry, right=r_entry))
    return diffs


def compare(left_root: str, right_root: str) -> List[Diff]:
    """Alias for :func:`compare_trees`, kept for a shorter call site."""
    return compare_trees(left_root, right_root)


def format_diff(diffs: Iterable[Diff]) -> str:
    """Render a list of diffs as newline-terminated text, one diff per line.

    Returns an empty string when there are no differences, which makes it easy
    to assert ``format_diff(diffs) == ""`` in tests and to pipe into a shell
    conditional.
    """
    return "".join(d.describe() + "\n" for d in diffs)
