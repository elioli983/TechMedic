"""Version/metadata checks for the v1.5.5 maintenance package."""
import io
import json
import unittest
import zipfile
from pathlib import Path

from techmedic.export_bundle import APP_VERSION, build_diagnostic_bundle, bundle_filename

ROOT=Path(__file__).resolve().parent.parent

class MaintenanceReleaseTests(unittest.TestCase):
    def test_release_version_matches_diagnostic_bundle(self):
        self.assertEqual(APP_VERSION, '1.5.6')
        case={'id':'synthetic', 'title':'Synthetic case', 'status':'investigating'}
        blob=build_diagnostic_bundle(case,[])
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            self.assertEqual(json.loads(z.read('MANIFEST.json'))['techmedic_version'],APP_VERSION)
            self.assertEqual(len(z.namelist()),12)
        self.assertIn('v1.5.6',bundle_filename(case))

    def test_source_ui_labels_new_release_without_test_build_banner(self):
        app=(ROOT/'app.py').read_text(encoding='utf-8')
        self.assertIn('TechMedic v1.5.6',app)
        self.assertNotIn('TEST BUILD',app)

    def test_shipped_dotenv_example_has_empty_keys(self):
        lines=(ROOT/'.env.example').read_text(encoding='utf-8').splitlines()
        mapping=dict(line.split('=',1) for line in lines if line and not line.startswith('#') and '=' in line)
        self.assertEqual(mapping.get('OPENAI_API_KEY'), '')
        self.assertEqual(mapping.get('JEV_API_KEY'), '')

    def test_historical_baseline_and_current_release_notes(self):
        self.assertTrue((ROOT/'RELEASE_NOTES_v1.5.4.txt').is_file())
        self.assertTrue((ROOT/'RELEASE_NOTES_v1.5.5.txt').is_file())
        self.assertTrue((ROOT/'UPGRADE_FROM_v1.5.4.txt').is_file())
