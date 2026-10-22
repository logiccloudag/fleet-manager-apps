"""Unit tests of scripts/lib/versions.py (FM-1631). Run: python3 -m unittest discover -s scripts/tests"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

import versions  # noqa: E402


class ClassifyTest(unittest.TestCase):
    """The table of FM-1631."""

    def test_patch_bump(self):
        self.assertEqual(versions.classify("2.7.10", "2.7.11"), "patch")

    def test_major_bump_with_two_components(self):
        self.assertEqual(versions.classify("2.7", "3.0"), "major")

    def test_rc_tag_is_ignored(self):
        self.assertEqual(versions.newest("2.7.10", ["2.7.11-rc1", "2.8.0-rc1", "2.7.10"]), "2.7.10")

    def test_equal_versions_are_a_no_op(self):
        self.assertEqual(versions.classify("2.7.10", "2.7.10"), "none")

    def test_minor_bump(self):
        self.assertEqual(versions.classify("0.40.2", "0.41.0"), "minor")

    def test_lower_version_is_no_bump(self):
        self.assertEqual(versions.classify("13.2.7", "13.1.9"), "none")

    def test_prefix_and_suffix_do_not_matter(self):
        self.assertEqual(versions.classify("v3.7.14", "v3.8.0"), "minor")
        self.assertEqual(versions.classify("2.9.1-alpine", "2.9.2-alpine"), "patch")


class NewestTest(unittest.TestCase):
    def test_keeps_the_suffix(self):
        tags = ["2.9.1-alpine", "2.9.2-alpine", "2.9.3", "2.10.0-alpine", "3.0.0-rc1-alpine", "latest", "alpine"]
        self.assertEqual(versions.newest("2.9.1-alpine", tags), "2.10.0-alpine")

    def test_keeps_the_prefix_and_drops_variants(self):
        tags = ["v3.7.9", "v3.7.14", "v3.7.15-nanoserver-ltsc2022", "v3.7.15-windowsservercore-ltsc2025", "3.7.16", "v3.8"]
        self.assertEqual(versions.newest("v3.7.14", tags), "v3.7.14")

    def test_same_number_of_components(self):
        self.assertEqual(versions.newest("4.1.2", ["4.1", "4.2", "4.1.3", "5"]), "4.1.3")

    def test_semver_not_lexical(self):
        self.assertEqual(versions.newest("13.2.7", ["13.2.10", "13.2.9", "13.10.0"]), "13.10.0")

    def test_unstable_markers(self):
        for tag in ["4.2.0-beta.1", "4.2.0-alpha", "4.2.0-nightly", "4.2.0-dev", "4.2.0rc1", "4.2.0-pre"]:
            self.assertEqual(versions.newest("4.1.2", [tag]), "4.1.2", tag)

    def test_same_major_stays_in_the_current_major(self):
        """FM-1731: grafana 13.2.7 gets 13.7.0 while 14.0.1 goes to an issue."""
        tags = ["13.2.7", "13.2.8", "13.7.0", "14.0.0", "14.0.1", "14.1.0-beta.1"]
        self.assertEqual(versions.newest("13.2.7", tags, same_major=True), "13.7.0")
        self.assertEqual(versions.newest("13.2.7", tags), "14.0.1")
        self.assertEqual(versions.newest("v3.7.14", ["v3.7.16", "v4.0.0"], same_major=True), "v3.7.16")
        self.assertEqual(versions.newest("2.9.1-alpine", ["3.0.0-alpine"], same_major=True), "2.9.1-alpine")

    def test_no_candidates(self):
        self.assertEqual(versions.newest("1.0.0", []), "1.0.0")


class HelpersTest(unittest.TestCase):
    def test_retag(self):
        self.assertEqual(versions.retag("13.2.3-distroless", "13.2.4"), "13.2.4-distroless")
        self.assertEqual(versions.retag("v3.7.14", "3.7.15"), "v3.7.15")

    def test_bump(self):
        self.assertEqual(versions.bump("1.1.0", "patch"), "1.1.1")
        self.assertEqual(versions.bump("1.1.3", "minor"), "1.2.0")
        self.assertEqual(versions.bump("0.2.0", "major"), "1.0.0")
        self.assertEqual(versions.bump("0.2.0", "none"), "0.2.0")

    def test_max_bump(self):
        self.assertEqual(versions.max_bump("patch", "none", "minor"), "minor")
        self.assertEqual(versions.max_bump(), "none")

    def test_not_a_version(self):
        with self.assertRaises(ValueError):
            versions.core("latest")
        self.assertIsNone(versions.shape("release-1.0"))


if __name__ == "__main__":
    unittest.main()
