import io
import json
import unittest
import zipfile

from techmedic.export_bundle import build_diagnostic_bundle, build_screen_output, bundle_filename


class ExportBundleTests(unittest.TestCase):
    def _case(self):
        return {
            "id": "case-1",
            "title": "PyTorch does not see GPU",
            "status": "diagnosis_established",
            "created_at": "2026-10-08T20:00:00+00:00",
            "updated_at": "2026-10-08T20:05:00+00:00",
            "device_type": "GPU",
            "manufacturer": "NVIDIA",
            "model": "GTX 1080",
            "operating_system": "Windows",
        }

    def _turns(self):
        return [{
            "id": 7,
            "case_id": "case-1",
            "user_text": "torch is CPU-only",
            "diagnostic_state": {"status": "diagnosis_established", "diagnosis": {"summary": "CPU-only build"}},
            "jev_result": {
                "answers": {
                    "fault_domain": {"choice": "application", "confidence": 0.9},
                    "evidence_sufficient": {"noul": 0.8},
                    "diagnosis_established": {"noul": 0.9},
                    "remediation_identified": {"noul": 0.2},
                    "resolution_verified": {"noul": 0.02},
                    "hardware_failure_likely": {"noul": 0.05},
                    "professional_service_needed": {"noul": 0.02},
                    "urgency": {"score": 0.2},
                    "next_action": {"choice": "verify_compatibility", "confidence": 0.8},
                },
                "_techmedic": {
                    "effective_next_action": "verify_compatibility",
                    "llm_response_time_ms": 1000,
                    "jev_response_time_ms": 200,
                    "total_ai_processing_time_ms": 1200,
                },
            },
            "research": {"performed": False, "skipped_reason": "not needed"},
            "safety": {"blocked": False, "warnings": []},
            "assistant_text": "Diagnosis established. Verify compatibility next.",
            "created_at": "2026-10-08T20:05:00+00:00",
        }]

    def test_bundle_contains_review_files(self):
        data = build_diagnostic_bundle(self._case(), self._turns())
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = set(zf.namelist())
            expected = {
                "00_COMBINED_REPORT.md",
                "01_SCREEN_OUTPUT.md",
                "02_LATEST_LLM_STRUCTURED_STATE.json",
                "03_LATEST_JEV_DECISION_RESULT.json",
                "04_LATEST_CONTROLLED_RESEARCH.json",
                "05_LATEST_SAFETY_SCREEN.json",
                "06_LATEST_TIMING_TELEMETRY.json",
                "07_CASE_HISTORY.md",
                "08_CASE_METADATA.json",
                "09_ALL_TURNS_RAW.json",
                "MANIFEST.json",
                "README.txt",
            }
            self.assertTrue(expected.issubset(names))
            llm = json.loads(zf.read("02_LATEST_LLM_STRUCTURED_STATE.json"))
            self.assertEqual(llm["diagnosis"]["summary"], "CPU-only build")
            jev = json.loads(zf.read("03_LATEST_JEV_DECISION_RESULT.json"))
            self.assertEqual(jev["answers"]["next_action"]["choice"], "verify_compatibility")
            raw = json.loads(zf.read("09_ALL_TURNS_RAW.json"))
            self.assertEqual(len(raw), 1)
            self.assertNotIn("OPENAI_API_KEY", zf.read("README.txt").decode("utf-8"))

    def test_screen_output_has_visible_summary_and_conversation(self):
        text = build_screen_output(self._case(), self._turns())
        self.assertIn("Status: Diagnosis Established", text)
        self.assertIn("TechMedic next action", text)
        self.assertIn("torch is CPU-only", text)
        self.assertIn("Diagnosis established. Verify compatibility next.", text)

    def test_bundle_filename_is_safe(self):
        name = bundle_filename({"title": "TV / dark screen: test?"})
        self.assertTrue(name.endswith("_diagnostic_bundle.zip"))
        self.assertNotIn("/", name)
        self.assertNotIn("?", name)


if __name__ == "__main__":
    unittest.main()
