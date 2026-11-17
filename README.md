# file_permission_diff_kit

Compare file modes and ownership between two directory trees and report the
differences.

```python
from file_permission_diff_kit import compare_trees, format_diff

diffs = compare_trees("/srv/app-a", "/srv/app-b")
print(format_diff(diffs))
```

`compare_trees` (also exported as `compare`) walks both trees, skips the roots
themselves, and returns a sorted list of `Diff` objects.  Each `Diff` has a
`path`, a `kind` (`"mode"`, `"owner"`, `"missing_left"`, `"missing_right"`),
and `left`/`right` `Entry` objects.  `format_diff` turns the list into one
newline-terminated line per difference, or `""` when the trees match.

## Why this exists

The problem is that `diff -r` and `rsync -n` tell you about content, not about
the permission bits and numeric owner/group that actually decide whether a
deployment works.  The trade-off made here is that we compare *numeric* bits
(`st_mode & 0o7777`) and numeric `uid`/`gid` rather than symbolic names: names
resolve differently across machines and containers, and symbolic mode strings
quietly drop the setuid/setgid/sticky bits that matter most.  Numeric values
always compare.

## The awkward edge

The root directories themselves are not compared.  If you `chmod 700` the left
root and `chmod 755` the right root, `compare_trees` reports no difference.  We
chose this because the two roots are usually mount points or checkout paths
whose own modes are incidental; comparing them would produce noise on every
run.  If you need the roots compared, stat them yourself.

Symlinks are compared as links (`os.lstat`), not followed, so a symlink's own
mode and ownership are what get reported.  Ownership differences are only
visible when the process can read them; in an unprivileged container every
file may report the same `uid`/`gid`, and then only mode differences appear.
