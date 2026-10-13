"""v1.5.2 focused regression tests based on four-turn PyTorch diagnosis.

These are OFFLINE fixtures. They do not exercise live OpenAI web_search/Jev.
"""
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from techmedic import database
from techmedic.export_bundle import APP_VERSION, build_diagnostic_bundle, bundle_filename
from techmedic.models import normalize_diagnostic_state
from techmedic.research import _extract_provenance, reconcile_research_source_ids
from techmedic.status import derive_case_status, derive_effective_next_action


def jev(diagnostic=.96, remediation=.85, resolution=.02, action="verify_compatibility"):
    return {"answers": {
        "diagnosis_established": {"noul": diagnostic},
        "remediation_identified": {"noul": remediation},
        "resolution_verified": {"noul": resolution},
        "next_action": {"choice": action},
    }}


class Version152Tests(unittest.TestCase):
    def test_turn2_original_v151_state_remains_diagnosis_established(self):
        state = {
            "status": "remediation_identified",
            "diagnosis": {"summary": "CPU-only PyTorch in active environment", "basis": ["torch 2.14.0+cpu"]},
            "remediation": {"summary": "Replace CPU-only PyTorch build", "requirements": [
                "Identify the affected Python version and executable before selecting an installation command.",
                "Confirm that Windows and the NVIDIA driver detect the GTX 1080.",
                "Select a CUDA-enabled PyTorch build compatible with the Python version.",
            ]},
            "research_request": {"needed": False, "category": "compatibility"},
        }
        self.assertEqual(derive_case_status(state, jev()), "diagnosis_established")

    def test_current_v152_explicit_blockers_override_high_jev_remediation(self):
        state = normalize_diagnostic_state({
            "status": "diagnosis_established",
            "diagnosis": {"summary": "CPU-only package", "basis": ["+cpu", "CUDA None"]},
            "remediation": {"summary": "Install CUDA build", "selection_ready": False,
                            "blocking_requirements": ["Check exact supported Windows wheel"]},
            "research_request": {"needed": True, "category": "compatibility"},
        })
        j = jev(action="recommend_software_repair")
        self.assertEqual(derive_case_status(state, j), "diagnosis_established")
        self.assertEqual(derive_effective_next_action(state, j, "diagnosis_established"), "verify_compatibility")
        self.assertEqual(j["answers"]["next_action"]["choice"], "recommend_software_repair")

    def test_turn3_research_evidence_allows_remediation(self):
        state = normalize_diagnostic_state({
            "status": "remediation_identified",
            "diagnosis": {"summary": "CPU-only package", "basis": ["+cpu", "CUDA None"]},
            "remediation": {"summary": "Use supported CUDA-enabled version", "selection_ready": True,
                            "blocking_requirements": [], "requirements": ["Verify after install"]},
        })
        self.assertEqual(derive_case_status(state, jev(remediation=.86)), "remediation_identified")

    def test_turn4_terminal_verification_still_works(self):
        state = normalize_diagnostic_state({
            "status": "resolution_verified",
            "diagnosis": {"summary": "CPU-only package", "basis": ["+cpu", "CUDA None"]},
            "remediation": {"summary": "CUDA-enabled package installed", "selection_ready": True},
            "resolution_verification": {"verified": True, "evidence": [
                "torch.cuda.is_available() True", "GPU tensor multiply succeeds"]},
        })
        j = jev(resolution=.97, action="verify_resolution")
        self.assertEqual(derive_case_status(state, j), "resolution_verified")
        self.assertEqual(derive_effective_next_action(state, j, "resolution_verified"), "finish_diagnosis")

    def test_v151_10_search_hits_do_not_crowd_out_true_citations(self):
        annotated = [
            {"type": "url_citation", "url": "https://docs.nvidia.com/cuda/archive/12.6.0/cuda-toolkit-release-notes/index.html?utm_source=openai", "title": "CUDA 12.6 Release Notes"},
            {"type": "url_citation", "url": "https://docs.pytorch.org/get-started/locally/", "title": "Start Locally"},
            {"type": "url_citation", "url": "https://github.com/pytorch/pytorch/blob/main/RELEASE.md", "title": "PyTorch compatibility matrix"},
        ]
        raw = {"output": [
            {"type": "web_search_call", "action": {"sources": [
                {"url": f"https://github.com/pytorch/pytorch/issues/{n}"} for n in range(100, 115)
            ]}},
            {"type": "message", "content": [{"type": "output_text", "annotations": annotated}]},
        ]}
        brief = "Official wheel index: [PyTorch CUDA 12.6 packages](https://download.pytorch.org/whl/cu126/torch/)"
        sources, citations = _extract_provenance(raw, brief, limit=10)
        self.assertEqual(len(sources), 10)
        self.assertEqual(len(citations), 4)
        self.assertTrue(all(c["source_id"] for c in citations))
        self.assertEqual(set(c["source_id"] for c in citations), {"R1", "R2", "R3", "R4"})
        self.assertTrue(any("download.pytorch.org/whl/cu126/torch" in s["url"] for s in sources))
        self.assertTrue(all(s["title"] not in {"github.com", "docs.pytorch.org"} for s in sources))
        self.assertTrue(all("utm_source" not in c["url"] for c in citations))

    def test_cited_pages_exceed_source_cap_without_dangling_citations(self):
        raw = {"output": [{"type": "message", "content": [{"annotations": [
            {"type": "url_citation", "url": f"https://docs.example.org/article/{n}", "title": f"Article {n}"}
            for n in range(4)]}]}]}
        sources, citations = _extract_provenance(raw, "", limit=2)
        self.assertEqual(len(sources), 4)  # cited sources win over soft cap
        self.assertEqual(len(citations), 4)
        self.assertEqual([c["source_id"] for c in citations], ["R1", "R2", "R3", "R4"])

    def test_integrated_source_ids_cannot_be_orphaned(self):
        state = {"research_evidence": {"source_ids": ["R1", "R9"]}}
        result = {"sources": [{"id": "R1", "url": "https://docs.example.org"}]}
        self.assertEqual(reconcile_research_source_ids(state, result), ["R9"])
        self.assertEqual(state["research_evidence"]["source_ids"], ["R1"])
        self.assertEqual(result["_techmedic"]["invalid_integrated_source_ids"], ["R9"])

    def test_uncited_search_hit_cannot_be_referenced_as_verified_documentation(self):
        state = {"research_evidence": {"source_ids": ["R1", "R2"]}}
        result = {"sources": [
            {"id": "R1", "url": "https://docs.example.org/page", "cited_in_research": True},
            {"id": "R2", "url": "https://github.com/other/project", "cited_in_research": False},
        ]}
        self.assertEqual(reconcile_research_source_ids(state, result), ["R2"])
        self.assertEqual(state["research_evidence"]["source_ids"], ["R1"])

    def test_case_metadata_auto_populates_without_wiping_known_fields(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / "test.sqlite3"
            database.init_db(path)
            cid = database.create_case(path, "GPU issue")
            database.update_case(path, cid, device_type="GPU", manufacturer="NVIDIA", model="GTX 1080",
                                 operating_system="Windows 11")
            database.update_case(path, cid, manufacturer=" ", operating_system=None)
            database.update_case(path, cid, manufacturer="Other manufacturer")
            case = database.get_case(path, cid)
            self.assertEqual([case[k] for k in ("device_type", "manufacturer", "model", "operating_system")],
                             ["GPU", "NVIDIA", "GTX 1080", "Windows 11"])

    def test_bundle_version_and_manifest(self):
        case = {"id": "c", "title": "Sample", "status": "diagnosis_established"}
        payload = build_diagnostic_bundle(case, [])
        with zipfile.ZipFile(io.BytesIO(payload)) as z:
            manifest = json.loads(z.read("MANIFEST.json"))
        self.assertEqual(APP_VERSION, "1.5.6")
        self.assertEqual(manifest["techmedic_version"], "1.5.6")
        self.assertIn("v1.5.6", bundle_filename(case))


if __name__ == "__main__":
    unittest.main()
