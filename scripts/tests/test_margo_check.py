"""Unit tests of the rc3 rules in scripts/lib/margo_check.py (FM-1839). Run: python3 -m unittest discover -s scripts/tests"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

import margo_check  # noqa: E402


def violations(constraints):
    before = margo_check.failures
    margo_check.check_profile_constraints({"deviceConstraints": constraints}, "p")
    return margo_check.failures - before


class DeviceConstraintsTest(unittest.TestCase):
    def test_valid_capacity(self):
        cap = {"capacityRequirements": {"cpu": {"cores": 0.5, "architectures": ["amd64"]},
                                        "memory": "512Mi", "storage": "5Gi"}}
        self.assertEqual(violations(cap), 0)

    def test_memory_pattern(self):
        self.assertEqual(violations({"capacityRequirements": {"memory": "1Ti"}}), 1)

    def test_unknown_architecture(self):
        self.assertEqual(violations({"capacityRequirements": {"cpu": {"cores": 1, "architectures": ["x86"]}}}), 1)

    def test_in_needs_values(self):
        rule = {"propertySelector": {"matchExpressions": [{"key": "/cpus", "operator": "In"}]}}
        self.assertEqual(violations({"eligibilityRules": [rule]}), 1)

    def test_property_key_must_be_json_pointer(self):
        rule = {"propertySelector": {"matchExpressions": [{"key": "cpus", "operator": "Exists"}]}}
        self.assertEqual(violations({"eligibilityRules": [rule]}), 1)

    def test_contains_all_needs_item_selector(self):
        rule = {"labelSelector": {"matchExpressions": [{"key": "k", "operator": "ContainsAll"}]}}
        self.assertEqual(violations({"eligibilityRules": [rule]}), 1)

    def test_required_resources_is_rc2(self):
        before = margo_check.failures
        margo_check.check_profile_constraints({"requiredResources": {}}, "p")
        self.assertEqual(margo_check.failures - before, 1)


class Rc2ShapeTest(unittest.TestCase):
    def test_copy_for_bart(self):
        doc = {"apiVersion": "v1", "deploymentProfiles": [
            {"type": "helm", "deviceConstraints": {"capacityRequirements": {"memory": "1Gi"}}}]}
        margo_check.to_rc2_shape(doc)
        self.assertEqual(doc["kind"], "ApplicationDescription")
        self.assertEqual(doc["apiVersion"], "margo/v1alpha1")
        self.assertEqual(doc["deploymentProfiles"][0]["requiredResources"], {"memory": "1Gi"})
        self.assertNotIn("deviceConstraints", doc["deploymentProfiles"][0])


if __name__ == "__main__":
    unittest.main()
