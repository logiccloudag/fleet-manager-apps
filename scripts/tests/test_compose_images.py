"""Unit tests of the compose image rule in scripts/lib/margo_check.py. Run: python3 -m unittest discover -s scripts/tests"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

import margo_check  # noqa: E402


class ComposeImageTest(unittest.TestCase):
    """A compose image is <registry>/<name>:<tag>, never tag@digest: the FLECS
    agent rejects that form with Docker 400 "invalid reference format"."""

    REGISTRY = "ghcr.io/logiccloudag/margo-images"
    REFS = {("influxdb", "2.9.1-alpine", "sha256:" + "a" * 64): "docker.io/library/influxdb"}

    def failed(self, image):
        before = margo_check.failures
        margo_check.check_compose_images("svc", [image], self.REFS, self.REGISTRY)
        return margo_check.failures - before

    def test_tag_only_is_accepted(self):
        self.assertEqual(self.failed(f"{self.REGISTRY}/influxdb:2.9.1-alpine"), 0)

    def test_tag_and_digest_is_rejected(self):
        self.assertEqual(self.failed(f"{self.REGISTRY}/influxdb:2.9.1-alpine@sha256:{'a' * 64}"), 1)

    def test_digest_only_is_rejected(self):
        self.assertEqual(self.failed(f"{self.REGISTRY}/influxdb@sha256:{'a' * 64}"), 1)

    def test_unpinned_tag_is_rejected(self):
        self.assertEqual(self.failed(f"{self.REGISTRY}/influxdb:2.9.0-alpine"), 1)
