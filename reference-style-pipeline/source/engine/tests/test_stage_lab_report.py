import json
import re
import sys
import types
from pathlib import Path

from PIL import Image

from hre.stage_lab.report import export_report, render_report


def _fixture(tmp_path):
    Image.new("RGB", (8, 6), "navy").save(tmp_path / "A.png")
    Image.new("RGB", (8, 6), "orange").save(tmp_path / "C.png")
    cases = [{"id": "night", "task": "保持内容，借鉴影调", "images": {"A": "A.png"}}]
    runs = [{"id": "r1", "case_id": "night", "stage": "execute", "model_id": "editor",
             "status": "completed", "duration_s": 1.5, "source_runs": ["c1"],
             "output": {"text": "完成", "data": {"tone": "brighter"}, "images": ["C.png"]},
             "metadata": {"synthetic": True}}]
    return cases, runs


def test_report_embeds_images_and_preserves_downloadable_records(tmp_path):
    cases, runs = _fixture(tmp_path)
    html = render_report(cases, runs, tmp_path)
    payload = json.loads(re.search(r'<script id="report-data" type="application/json">(.*?)</script>', html, re.S)[1])
    assert payload["runs"][0]["record"] == runs[0]
    assert payload["runs"][0]["images"][0]["src"].startswith("data:image/png;base64,")
    assert payload["runs"][0]["images"][0]["width"] == 8
    assert payload["cases"][0]["images"][0]["height"] == 6
    assert 'src="http' not in html
    assert 'id="stage-filter"' in html
    assert 'id="text-diff"' in html
    assert "合成演示 · 非模型性能" in html


def test_report_never_embeds_model_text_as_html(tmp_path):
    cases, runs = _fixture(tmp_path)
    malicious = '</script><script>alert("x")</script><img src=x onerror=alert(1)>'
    runs[0]["output"]["text"] = malicious
    cases[0]["task"] = malicious
    html = render_report(cases, runs, tmp_path)
    assert malicious not in html
    assert '\\u003c/script\\u003e' in html
    raw = re.search(r'<script id="report-data" type="application/json">(.*?)</script>', html, re.S)[1]
    assert json.loads(raw)["runs"][0]["record"]["output"]["text"] == malicious
    assert "esc(o.text)" in html


def test_report_handles_empty_and_missing_images(tmp_path):
    html = render_report([], [], tmp_path)
    assert "此筛选条件下没有运行结果" in html
    html = render_report([{"id": "x", "images": {"A": "missing.png"}}], [], tmp_path)
    assert "图像文件不可用" in html


def test_export_report_honors_case_and_stage_filters(tmp_path, monkeypatch):
    cases, runs = _fixture(tmp_path)
    calls = []
    fake = types.ModuleType("hre.stage_lab.core")
    fake.list_cases = lambda root: cases + [{"id": "other", "images": {}}]
    def listing(root, case_id=None, stage=None):
        calls.append((case_id, stage))
        return runs
    fake.list_runs = listing
    monkeypatch.setitem(sys.modules, "hre.stage_lab.core", fake)
    output = export_report(tmp_path, tmp_path / "exports" / "comparison.html", case_id="night", stage="execute")
    assert output.is_file()
    assert calls == [("night", "execute")]
    payload = json.loads(re.search(r'<script id="report-data" type="application/json">(.*?)</script>', output.read_text(), re.S)[1])
    assert [x["record"]["id"] for x in payload["cases"]] == ["night"]


def test_judge_only_report_embeds_external_candidates_with_input_labels(tmp_path):
    from hre.stage_lab.core import add_case, init_lab, run_stage

    root = tmp_path / "lab"
    init_lab(root, models={"judge": {"provider": "demo"}})
    for name, color in (("A", "navy"), ("C", "orange"), ("C2", "green")):
        Image.new("RGB", (8, 6), color).save(tmp_path / f"{name}.png")
    add_case(root, tmp_path / "A.png", tmp_path / "A.png", case_id="direct")
    run_stage(root, "direct", "judge", ["judge"], candidates=[tmp_path / "C.png", tmp_path / "C2.png"])
    output = export_report(root, stage="judge")
    payload = json.loads(re.search(r'<script id="report-data" type="application/json">(.*?)</script>', output.read_text(), re.S)[1])
    view = payload["runs"][0]
    assert view["record"]["output"]["images"] == []
    assert view["record"]["source_runs"] == []
    assert [image["role"] for image in view["images"]] == ["C", "C2"]
    assert all(image["kind"] == "input_candidate" and "判别输入候选" in image["label"] for image in view["images"])
    assert all(image["src"].startswith("data:image/png;base64,") for image in view["images"])
