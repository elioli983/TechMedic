import unittest

from techmedic.presentation import friendly_action, friendly_status


class PresentationTests(unittest.TestCase):
    def test_action_labels_are_human_readable(self):
        self.assertEqual(friendly_action("run_diagnostic_test"), "Run diagnostic test")
        self.assertEqual(friendly_action("verify_compatibility"), "Verify compatibility")
        self.assertEqual(friendly_action("collect_system_information"), "Collect system information")

    def test_status_labels_match_v14_lifecycle(self):
        self.assertEqual(friendly_status("diagnosis_established"), "Diagnosis Established")
        self.assertEqual(friendly_status("remediation_identified"), "Remediation Identified")
        self.assertEqual(friendly_status("resolution_verified"), "Resolution Verified")
        self.assertEqual(friendly_status("escalate"), "Escalate (legacy status)")


if __name__ == "__main__":
    unittest.main()
