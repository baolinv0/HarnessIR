from pathlib import Path
from streamlit.testing.v1 import AppTest
from hir_manual.service import Controller


def test_wizard_renders_current_task(tmp_path, photo, monkeypatch):
    state = Controller(tmp_path).new(photo, "restore")
    monkeypatch.setenv("HIR_ROOT", str(tmp_path))
    source = Path(__file__).resolve().parents[1] / "src/hir_manual/ui.py"
    app = AppTest.from_file(str(source), default_timeout=25).run()
    assert len(app.exception) == 0
    assert any(x.value == "WAIT_DIAGNOSIS" for x in app.metric)
    assert any(state.case_id in x.options[0] for x in app.selectbox)
