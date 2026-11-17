import os
import stat
import tempfile
import unittest

from file_permission_diff_kit import (
    Diff,
    Entry,
    compare,
    compare_trees,
    format_diff,
)


class TreeTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.left = os.path.join(self.tmp.name, "left")
        self.right = os.path.join(self.tmp.name, "right")
        os.makedirs(self.left)
        os.makedirs(self.right)

    def make(self, side, relpath, mode, uid=None, gid=None):
        root = self.left if side == "left" else self.right
        full = os.path.join(root, relpath)
        parent = os.path.dirname(full)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)
        with open(full, "w") as fh:
            fh.write("x")
        os.chmod(full, mode)
        if uid is not None or gid is not None:
            st = os.lstat(full)
            os.chown(full, uid if uid is not None else st.st_uid,
                     gid if gid is not None else st.st_gid)
        return full

    def make_dir(self, side, relpath, mode):
        root = self.left if side == "left" else self.right
        full = os.path.join(root, relpath)
        os.makedirs(full)
        os.chmod(full, mode)
        return full


class WalkAndCompareTests(TreeTestCase):
    def test_identical_trees_produce_no_diffs(self):
        self.make("left", "a.txt", 0o644)
        self.make("right", "a.txt", 0o644)
        self.make("left", "sub/b.txt", 0o600)
        self.make("right", "sub/b.txt", 0o600)
        self.assertEqual(compare_trees(self.left, self.right), [])
        self.assertEqual(format_diff(compare_trees(self.left, self.right)), "")

    def test_mode_difference_is_reported(self):
        self.make("left", "a.txt", 0o644)
        self.make("right", "a.txt", 0o600)
        diffs = compare(self.left, self.right)
        self.assertEqual(len(diffs), 1)
        d = diffs[0]
        self.assertIsInstance(d, Diff)
        self.assertEqual(d.kind, "mode")
        self.assertEqual(d.path, "a.txt")
        self.assertEqual(d.left.permission_bits, 0o644)
        self.assertEqual(d.right.permission_bits, 0o600)
        self.assertEqual(d.describe(), "a.txt: mode 0644 -> 0600")

    def test_special_bits_are_compared(self):
        # setuid bit must survive the mask; symbolic modes often drop it.
        self.make("left", "a.txt", 0o4755)
        self.make("right", "a.txt", 0o0755)
        diffs = compare(self.left, self.right)
        self.assertEqual([d.kind for d in diffs], ["mode"])
        self.assertEqual(diffs[0].left.permission_bits, 0o4755)

    def test_missing_on_left_and_right(self):
        self.make("left", "only_left.txt", 0o644)
        self.make("right", "only_right.txt", 0o644)
        diffs = compare(self.left, self.right)
        kinds = sorted(d.kind for d in diffs)
        self.assertEqual(kinds, ["missing_left", "missing_right"])
        by_path = {d.path: d for d in diffs}
        self.assertEqual(by_path["only_left.txt"].kind, "missing_right")
        self.assertEqual(by_path["only_right.txt"].kind, "missing_left")

    def test_directory_mode_difference(self):
        self.make_dir("left", "d", 0o755)
        self.make_dir("right", "d", 0o700)
        diffs = compare(self.left, self.right)
        self.assertEqual(len(diffs), 1)
        self.assertEqual(diffs[0].path, "d")
        self.assertEqual(diffs[0].kind, "mode")
        self.assertTrue(diffs[0].left.is_dir)

    def test_diffs_sorted_by_path(self):
        self.make("left", "z.txt", 0o644)
        self.make("right", "z.txt", 0o600)
        self.make("left", "a.txt", 0o644)
        self.make("right", "a.txt", 0o600)
        diffs = compare(self.left, self.right)
        self.assertEqual([d.path for d in diffs], ["a.txt", "z.txt"])

    def test_format_diff_multiple_lines(self):
        self.make("left", "a.txt", 0o644)
        self.make("right", "a.txt", 0o600)
        self.make("left", "b.txt", 0o644)
        text = format_diff(compare(self.left, self.right))
        self.assertEqual(text, "a.txt: mode 0644 -> 0600\nb.txt: missing on right\n")

    def test_root_mode_is_ignored(self):
        # We compare contents, not the mode of the roots themselves.
        os.chmod(self.left, 0o755)
        os.chmod(self.right, 0o700)
        self.make("left", "a.txt", 0o644)
        self.make("right", "a.txt", 0o644)
        self.assertEqual(compare(self.left, self.right), [])


class EntryTests(unittest.TestCase):
    def test_permission_bits_masks_file_type(self):
        # st_mode for a regular file with 0644 permission bits.
        e = Entry(path="x", mode=stat.S_IFREG | 0o644, uid=1, gid=2)
        self.assertEqual(e.permission_bits, 0o644)
        self.assertFalse(e.is_dir)

    def test_is_dir_true_for_directory_mode(self):
        e = Entry(path="d", mode=stat.S_IFDIR | 0o755, uid=1, gid=2)
        self.assertTrue(e.is_dir)
        self.assertEqual(e.permission_bits, 0o755)

    def test_describe_owner(self):
        left = Entry(path="x", mode=stat.S_IFREG | 0o644, uid=1000, gid=1000)
        right = Entry(path="x", mode=stat.S_IFREG | 0o644, uid=1001, gid=1001)
        d = Diff(path="x", kind="owner", left=left, right=right)
        self.assertEqual(d.describe(), "x: owner 1000:1000 -> 1001:1001")

    def test_describe_unknown_kind_raises(self):
        d = Diff(path="x", kind="bogus", left=None, right=None)
        with self.assertRaises(ValueError):
            d.describe()


class OwnershipTests(TreeTestCase):
    def setUp(self):
        super().setUp()
        if os.geteuid() != 0:
            self.skipTest("chown to arbitrary uid/gid requires root privileges")

    def test_owner_difference_is_reported(self):
        self.make("left", "a.txt", 0o644, uid=1234, gid=1234)
        self.make("right", "a.txt", 0o644, uid=1235, gid=1234)
        diffs = compare(self.left, self.right)
        self.assertEqual(len(diffs), 1)
        self.assertEqual(diffs[0].kind, "owner")
        self.assertEqual(diffs[0].describe(), "a.txt: owner 1234:1234 -> 1235:1234")

    def test_mode_and_owner_difference_produce_two_diffs(self):
        self.make("left", "a.txt", 0o644, uid=1234, gid=1234)
        self.make("right", "a.txt", 0o600, uid=1235, gid=1234)
        diffs = compare(self.left, self.right)
        kinds = sorted(d.kind for d in diffs)
        self.assertEqual(kinds, ["mode", "owner"])
        self.assertEqual([d.path for d in diffs], ["a.txt", "a.txt"])


if __name__ == "__main__":
    unittest.main()
