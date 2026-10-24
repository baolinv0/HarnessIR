"""Deterministic restoration contracts; these tests do not run learned models."""
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PIL import Image

from harness.stages.execute import run_execute
from harness.stages.verify import build_verify_system
from run_baseline import _run_one


class FixedEditor:
    def edit(self, images, prompt):
        # A deliberately different native size exposes silent geometry repairs.
        return Image.new("RGB", (80, 60), (30, 50, 70))


class RestorationAuditTests(unittest.TestCase):
    def test_multi_type_verifier_preserves_both_checklists(self):
        system = build_verify_system(["rain", "lowlight"])
        self.assertIn("RAIN.T1", system)
        self.assertIn("LOWLIGHT.T1", system)
        self.assertIn("Mark that item 'na'", system)

    def test_execute_keeps_native_output_before_normalizing(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "lq.png"
            Image.new("RGB", (40, 30), (1, 2, 3)).save(source)
            rec = run_execute(FixedEditor(), source, "Restore.", root / "run")
            self.assertIsNone(rec["error"])
            self.assertIn("raw_path", rec)
            with Image.open(rec["raw_path"]) as raw, Image.open(rec["path"]) as output:
                self.assertEqual(raw.size, (80, 60))
                self.assertEqual(output.size, (40, 30))
            self.assertEqual(rec["raw_sha256"], hashlib.sha256(Path(rec["raw_path"]).read_bytes()).hexdigest())
            self.assertTrue(rec["geometry_normalized"])

    def test_baseline_keeps_same_native_receipt_contract(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "lq.png"
            Image.new("RGB", (40, 30), (1, 2, 3)).save(source)
            rec = _run_one(FixedEditor(), "case", {"lq": str(source)}, root / "run",
                           root / "delivered", square1024=False, resume=False,
                           color_adjust=False)
            self.assertNotIn("error", rec)
            self.assertIn("raw_path", rec)
            with Image.open(rec["raw_path"]) as raw, Image.open(rec["output"]) as output:
                self.assertEqual(raw.size, (80, 60))
                self.assertEqual(output.size, (40, 30))
            self.assertEqual(rec["raw_output_size"], [80, 60])

    def test_archiving_failure_is_explicit_without_discarding_generation(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "lq.png"
            Image.new("RGB", (40, 30)).save(source)
            run = root / "run"
            run.mkdir()
            (run / "raw_outputs").write_text("Not a writable directory")
            rec = run_execute(FixedEditor(), source, "Restore.", run)
            self.assertIsNone(rec["error"])
            self.assertFalse(rec["native_archive_complete"])
            self.assertTrue(rec["archive_error"])
            self.assertTrue(Path(rec["path"]).is_file())

    def test_downstream_write_failure_retains_successful_raw_receipt(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "lq.png"
            Image.new("RGB", (40, 30)).save(source)
            run = root / "run"
            (run / "output.png").mkdir(parents=True)
            rec = run_execute(FixedEditor(), source, "Restore.", run)
            self.assertIsNotNone(rec["error"])
            self.assertIn("raw_path", rec)
            self.assertTrue(Path(rec["raw_path"]).is_file())


if __name__ == "__main__":
    unittest.main()
