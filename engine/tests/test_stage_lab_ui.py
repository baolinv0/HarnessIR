"""Exercise the real UI controls and stored artifacts, using synthetic providers."""
from pathlib import Path

from PIL import Image
import pytest

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest

from hre.stage_lab.core import add_case, init_lab, list_runs


def _control(elements, label):
    return next(element for element in elements if element.label == label)


def test_ui_runs_all_stages_and_crosses_upstream_outputs_with_models(tmp_path, monkeypatch):
    root = tmp_path / "lab"
    init_lab(root, models={name: {"provider": "demo", "model": name} for name in ("demo-a", "demo-b")})
    Image.new("RGB", (12, 8), "navy").save(tmp_path / "a.png")
    Image.new("RGB", (12, 8), "orange").save(tmp_path / "b.png")
    add_case(root, tmp_path / "a.png", tmp_path / "b.png", case_id="sample")
    monkeypatch.setenv("HRE_LAB_ROOT", str(root))
    app = AppTest.from_file(Path(__file__).parents[1] / "src/hre/stage_lab/ui.py", default_timeout=20).run()
    assert not app.exception

    for stage, count in (("diagnose", 2), ("plan", 4), ("compile", 2), ("execute", 2), ("judge", 4)):
        _control(app.radio, "测试阶段").set_value(stage).run()
        if stage in {"plan", "judge"}:
            previous = "diagnose" if stage == "plan" else "execute"
            sources = [run["id"] for run in list_runs(root, stage=previous)]
            _control(app.multiselect, "上游结果（可留空，直接提供输入）").set_value(sources).run()
        _control(app.button, "运行本阶段并对比").click().run()
        assert not app.exception
        assert not app.error
        runs = list_runs(root, stage=stage)
        assert len(runs) == count
        assert all(run["status"] == "completed" for run in runs)
        if stage != "diagnose":
            assert all(len(run["source_runs"]) == 1 for run in runs)
        if stage == "judge":
            captions = [image.caption for element in app.get("image") for image in element.proto.imgs]
            assert sum("判别输入候选" in caption for caption in captions) == 4

    assert (root / "comparison.html").is_file()
    _control(app.radio, "判别方式").set_value("action").run()
    _control(app.text_area, "待检查的 Action").set_value("提高衣服暗部可见度，保留逆光关系").run()
    _control(app.button, "运行本阶段并对比").click().run()
    assert not app.exception
    action_judges = [run for run in list_runs(root, stage="judge")
                    if run["request"]["context"].get("judge_mode") == "action"]
    assert len(action_judges) == 4
    assert all(run["request"]["context"]["action"] == "提高衣服暗部可见度，保留逆光关系" for run in action_judges)


def test_ui_keeps_failed_model_visible_next_to_success_and_exports_bundle(tmp_path, monkeypatch):
    root = tmp_path / "lab"
    init_lab(root, models={"working": {"provider": "demo"}, "unavailable": {"provider": "manual"}})
    Image.new("RGB", (8, 8), "navy").save(tmp_path / "a.png")
    add_case(root, tmp_path / "a.png", tmp_path / "a.png", case_id="sample")
    monkeypatch.setenv("HRE_LAB_ROOT", str(root))
    app = AppTest.from_file(Path(__file__).parents[1] / "src/hre/stage_lab/ui.py", default_timeout=20).run()
    _control(app.button, "运行本阶段并对比").click().run()
    assert not app.exception
    runs = list_runs(root, stage="diagnose")
    assert {run["model_id"]: run["status"] for run in runs} == {"working": "completed", "unavailable": "error"}
    _control(app.button, "导出本阶段请求").click().run()
    assert not app.exception
    assert len(list((root / "exports").glob("*/request.json"))) == 2
    downloads = app.get("download_button")
    assert sum(item.proto.label.startswith("下载请求") and item.proto.url.endswith(".zip") for item in downloads) == 2
