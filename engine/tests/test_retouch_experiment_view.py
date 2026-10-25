import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen

from hre.retouch.server import make_server
from hre.retouch.workflow import Workbench


class ExperimentViewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.workbench = Workbench(root / "retouch")
        self.exp = root / "retouch_experiments" / "sample"
        (self.exp / "assets").mkdir(parents=True)
        (self.exp / "manifest.json").write_text(json.dumps({"id": "sample", "title": "real experiment", "status": "running", "calls_submitted": 2, "conditions": []}), encoding="utf-8")
        (self.exp / "assets/real.png").write_bytes(b"\x89PNG\r\nreal image fixture")
        self.server = make_server(self.workbench, 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def test_list_and_read_actual_manifest_without_fabricating_evaluation(self):
        with urlopen(self.base + "/api/experiments") as response:
            listed = json.load(response)
        self.assertEqual(listed["experiments"][0]["id"], "sample")
        with urlopen(self.base + "/api/experiments/sample") as response:
            record = json.load(response)
        self.assertEqual(record["calls_submitted"], 2)
        self.assertIsNone(record.get("evaluation"))

    def test_asset_bytes_and_viewer(self):
        with urlopen(self.base + "/api/experiments/sample/assets/real.png") as response:
            self.assertEqual(response.read(), b"\x89PNG\r\nreal image fixture")
        with urlopen(self.base + "/experiments") as response:
            self.assertIn("实验".encode(), response.read())

    def test_missing_and_traversal_requests_do_not_expose_other_files(self):
        for path in ("/api/experiments/missing", "/api/experiments/../state", "/api/experiments/sample/assets/manifest.json", "/api/experiments/sample/assets/../manifest.json"):
            with self.subTest(path=path), self.assertRaises(HTTPError) as error:
                urlopen(self.base + path)
            self.assertIn(error.exception.code, (400, 404))
            error.exception.close()


if __name__ == "__main__":
    unittest.main()
