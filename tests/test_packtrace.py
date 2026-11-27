import json
import shutil
import tempfile
import unittest
from pathlib import Path
from backend import app as service


class PackTraceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_db = service.DB
        self.original_uploads = service.UPLOADS
        copy = Path(self.temp.name) / "test.db"
        shutil.copy2(self.original_db, copy)
        service.DB = copy
        service.UPLOADS = Path(self.temp.name) / "uploads"
        service.UPLOADS.mkdir()

    def tearDown(self):
        service.DB = self.original_db
        service.UPLOADS = self.original_uploads
        self.temp.cleanup()

    def test_seed_inventory_and_transparent_score(self):
        self.assertEqual(len(service.products()), 3)
        self.assertEqual(len(service.packaging()), 15)
        d = service.dashboard()
        self.assertEqual(d["components"], 15)
        self.assertEqual(len(d["weights"]), 5)
        self.assertAlmostEqual(sum(d["weights"].values()), 1.0)
        self.assertGreaterEqual(d["score"], 0)
        self.assertLessEqual(d["score"], 100)

    def test_unit_normalization_is_not_false_conflict(self):
        c = next(x for x in service.conflicts() if x["id"] == "CON-002")
        self.assertIn("equivalent", c["explanation"])
        result = service.resolve_conflict(c["id"], service.ResolvePayload(value="18.5 g", note="Unit normalized"))
        self.assertEqual(result["conflict"]["status"], "Resolved")
        comp = service.component("PKG-004")
        self.assertAlmostEqual(comp["weight_g"], 18.5)

    def test_resolving_source_conflict_updates_master_and_score(self):
        before = service.dashboard()["score"]
        result = service.resolve_conflict("CON-001", service.ResolvePayload(value="Recycled PET", note="Checked certificate RF-2026-041"))
        self.assertEqual(result["conflict"]["status"], "Resolved")
        self.assertEqual(service.component("PKG-003")["material"], "Recycled PET")
        self.assertGreaterEqual(service.dashboard()["score"], before)

    def test_optimization_uses_current_component_weights(self):
        result = service.simulate(service.SimPayload(component_ids=["PKG-001"], weight_reduction_pct=10, dimension_reduction_pct=5, carbon_factor_kgco2e_per_kg=2.0))
        self.assertEqual(result["before_weight_g"], 420)
        self.assertEqual(result["after_weight_g"], 378)
        self.assertEqual(result["savings_g"], 42)
        self.assertEqual(result["estimated_carbon_kgco2e"], .084)

    def test_spreadsheet_extraction_preserves_cell_addresses(self):
        sample = service.SAMPLES / "ERP packaging BOM.xlsx"
        extracted, _ = service.extract_document(sample, sample.name)
        self.assertTrue(extracted)
        self.assertEqual(extracted[0][0], "packaging_id")
        self.assertTrue(any("cell A2" in x[3] for x in extracted))
        self.assertTrue(any(x[0]=="weight_g" and x[2]=="g" for x in extracted))

    def test_upload_validation_rejects_unsupported_and_oversized_files(self):
        with self.assertRaises(service.HTTPException) as bad_type:
            service.validate_upload("payload.exe")
        self.assertEqual(bad_type.exception.status_code, 400)
        with self.assertRaises(service.HTTPException) as too_large:
            service.validate_upload("evidence.pdf", 12*1024*1024+1)
        self.assertEqual(too_large.exception.status_code, 413)

    def test_report_contains_evidence_and_limitations(self):
        report = service.report_data("PRD-001")
        self.assertEqual(len(report["components"]), 6)
        self.assertTrue(any(x["evidence"] for x in report["components"]))
        first_finding = service.rows("SELECT evidence FROM findings WHERE id=?", ("FND-001",))[0]["evidence"]
        self.assertTrue(service.rows("SELECT id FROM evidence WHERE id=?", (first_finding,)))
        self.assertEqual(report["legal_status"], "Not determined")
        pdf = service.report_pdf("PRD-001")
        self.assertEqual(pdf.media_type, "application/pdf")
        self.assertTrue(pdf.body.startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
