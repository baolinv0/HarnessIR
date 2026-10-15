from pathlib import Path
from PIL import Image
from test_hre_reference_v2 import spec


def test_v2_panel_shows_unprobed_mask_without_enabling_control(tmp_path,monkeypatch):
    from hre.reference_contracts import create_reference_case
    from streamlit.testing.v1 import AppTest
    a=tmp_path/'A.png';b=tmp_path/'B.png'
    Image.new('RGB',(16,12),(40,40,40)).save(a);Image.new('RGB',(20,14),(80,80,80)).save(b)
    create_reference_case(a,b,spec(),tmp_path/'cases/case/rev1',spec_root=tmp_path)
    monkeypatch.setenv('HRE_DATA_ROOT',str(tmp_path/'cases'))
    app=AppTest.from_file(str(Path(__file__).parents[1]/'src/hre/ui.py')).run()
    assert not app.exception
    assert any('Mask capability: untested' in str(v.value) for v in app.markdown)
    assert not any('enable mask' in c.label.lower() for c in app.checkbox)
