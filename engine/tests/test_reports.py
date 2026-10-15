import json
import zipfile
from hir_manual.service import Controller


def test_report_contains_full_audit(tmp_path, photo):
    ctl = Controller(tmp_path)
    state = ctl.new(photo, "restore")
    ctl.operate(state.case_id, "pause")
    path = ctl.export(state.case_id, tmp_path / "audit.zip")
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        assert "input/canonical.png" in names
        assert "input/original.png" in names
        assert "events.jsonl" in names
        assert "final/report.json" in names
        assert any(n.endswith("prompt.txt") for n in names)
        report = json.loads(z.read("final/report.json"))
        assert report["workflow_completed"] is False
        assert report["restoration_success"] is None
        assert report["manual_operations"] == 1
        assert report["algorithm_gain_supported"] is False
