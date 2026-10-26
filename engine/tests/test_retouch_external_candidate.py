import base64
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

from PIL import Image

from hre.retouch.contracts import RetouchError
from hre.retouch.server import make_server
from hre.retouch.workflow import Workbench
from test_retouch_workbench import analysis, contract, picture


class ExternalCandidateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.w = Workbench(Path(self.tmp.name))
        self.c = self.prepare()

    def prepare(self, size=(96, 128)):
        c = self.w.create({"source_data": picture(size=size), "reference_data": picture(), "brief": "参考色彩"})
        self.w.import_stage(c["id"], "diagnose", analysis())
        return self.w.import_stage(c["id"], "compose", contract())

    def test_unknown_external_identity_is_unverified_and_counted(self):
        c = self.w.candidate(self.c["id"], picture(), "unknown", note="宿主没有返回后端型号")
        self.assertEqual(c["rounds"][0]["model"], "unknown")
        self.assertEqual(c["rounds"][0]["observation"]["model_identity"], "unverified")
        self.assertEqual(c["calls"]["images"], 1)
        self.assertEqual(c["phase"], "verify")

    def test_unknown_internal_identity_and_other_known_models_remain_rejected(self):
        for model, provenance in (("unknown", "images_api"), ("other-image-model", "manual_import")):
            with self.subTest(model=model), self.assertRaises(RetouchError) as error:
                self.w.candidate(self.c["id"], picture(), model, provenance)
            self.assertEqual(error.exception.code, "model_mismatch")
        self.assertEqual(self.w.get(self.c["id"])["calls"]["images"], 0)

    def test_submitted_prompt_is_saved_without_changing_compiled_contract(self):
        c = self.w.candidate(self.c["id"], picture(), "gpt-image-2", submitted_prompt="Actual externally submitted prompt")
        self.assertEqual(c["rounds"][0]["prompt"], "Actual externally submitted prompt")
        self.assertEqual(c["rounds"][0]["prompt_source"], "external_submitted")
        self.assertEqual(c["prompt"], self.c["prompt"])
        self.assertEqual(c["contract"], self.c["contract"])
        self.assertEqual(c["rounds"][0]["observation"]["model_identity"], "user_declared")

    def test_unspecified_external_prompt_is_not_claimed_as_confirmed(self):
        c = self.w.candidate(self.c["id"], picture(), "gpt-image-2")
        self.assertEqual(c["rounds"][0]["prompt_source"], "case_compiled_unconfirmed")

    def test_explicit_full_frame_mapping_preserves_native_and_exports_geometry_blindly(self):
        c = self.prepare((2296, 3056))
        c = self.w.candidate(c["id"], picture(size=(1087, 1446)), "unknown",
                             submitted_prompt="actual external prompt",
                             external_geometry={"policy": "full_frame_resize", "source_frame_confirmed": True})
        row = c["rounds"][0]
        geometry = row["candidate_geometry"]
        self.assertEqual(geometry["native_size"], [1087, 1446])
        self.assertEqual(geometry["delivered_size"], [2296, 3056])
        self.assertEqual(geometry["policy"], "full_frame_resize")
        self.assertTrue(geometry["source_frame_declaration"])
        self.assertAlmostEqual(geometry["scale_factors"][0], 2296 / 1087)
        native = self.w._dir(c["id"]) / "assets" / Path(row["native_url"]).name
        delivered = self.w._dir(c["id"]) / "assets" / Path(row["candidate_url"]).name
        with Image.open(native) as im:
            self.assertEqual(im.size, (1087, 1446))
        with Image.open(delivered) as im:
            self.assertEqual(im.size, (2296, 3056))
        req = self.w.export(c["id"], "verify")
        self.assertEqual(req["context"]["candidate_geometry"], geometry)
        self.assertNotIn("prompt", req["context"])
        self.assertNotIn("model", req["context"])
        self.assertNotIn("prompt_source", req["context"])

    def test_external_size_requires_declaration_and_near_matching_aspect(self):
        for size, declaration in (((48, 64), None), ((96, 96), {"policy": "full_frame_resize", "source_frame_confirmed": True}),
                                  ((48, 64), {"policy": "full_frame_resize", "source_frame_confirmed": False})):
            with self.subTest(size=size, declaration=declaration), self.assertRaises(RetouchError):
                self.w.candidate(self.c["id"], picture(size=size), "gpt-image-2", external_geometry=declaration)
        self.assertIsNone(self.w.get(self.c["id"])["images"]["candidate"])
        self.assertEqual(self.w.get(self.c["id"])["calls"]["images"], 0)

    def test_external_full_frame_declaration_overrides_matching_prepared_canvas_size(self):
        c = self.prepare((1000, 1001))
        self.assertEqual(c["geometry"]["canvas_size"], [1008, 1008])
        native = Image.new("RGB", (1008, 1008))
        native.paste((255, 0, 0), (1000, 0, 1008, 1008))
        buffer = io.BytesIO()
        native.save(buffer, format="PNG")
        data = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
        result = self.w.candidate(c["id"], data, "unknown", external_geometry={"policy": "full_frame_resize", "source_frame_confirmed": True})
        self.assertEqual(result["rounds"][0]["candidate_geometry"]["policy"], "full_frame_resize")
        delivered = self.w._dir(c["id"]) / "assets" / Path(result["rounds"][0]["candidate_url"]).name
        with Image.open(delivered) as image:
            self.assertGreater(image.getpixel((999, 500))[0], 200)

    def test_http_forwards_external_prompt_and_geometry(self):
        server = make_server(self.w, 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            payload = {"image_data": picture(size=(48, 64)), "model": "unknown", "note": "host native",
                       "submitted_prompt": "actual prompt via HTTP",
                       "external_geometry": {"policy": "full_frame_resize", "source_frame_confirmed": True}}
            request = Request(f"http://127.0.0.1:{server.server_port}/api/cases/{self.c['id']}/candidate",
                              data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
            c = json.load(urlopen(request))
            self.assertEqual(c["rounds"][0]["prompt"], payload["submitted_prompt"])
            self.assertEqual(c["rounds"][0]["candidate_geometry"]["native_size"], [48, 64])
            self.assertEqual(c["rounds"][0]["observation"]["model_identity"], "unverified")
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
