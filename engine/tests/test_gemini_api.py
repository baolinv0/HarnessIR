"""API contract tests using fake responses, not real editing acceptance."""
import base64
import io
import json
from pathlib import Path
import pytest
from PIL import Image
from hir_manual import gemini_api as api
from hir_manual.service import Controller
from hir_manual.storage import read_json


def new_case(tmp_path, photo):
    ctl = Controller(tmp_path)
    state = ctl.new(photo, 'conservative restoration', api.configuration('gemini-3-pro-image', 'gemini-2.5-pro'))
    return ctl, ctl.case(state.case_id)


def test_explicit_opt_in_and_default_unchanged(tmp_path, photo):
    ctl, case = new_case(tmp_path, photo)
    cfg = read_json(case.path('case_config.json'))
    assert cfg['external_api_calls'] and cfg['executor'] == 'gemini_api_image'
    assert ctl.inspect(case.case_id).deviated
    normal = ctl.new(photo, 'restore')
    assert read_json(ctl.case(normal.case_id).path('case_config.json'))['executor'] == 'chatgpt_desktop_image'
    with pytest.raises(ValueError):
        ctl.new(photo, 'restore', {'external_api_calls': True})
    bare = api.configuration('gemini-3-pro-image', 'gemini-2.5-pro')
    bare.pop('branch_type')
    isolated = ctl.new(photo, 'restore', bare)
    assert isolated.deviated
    assert read_json(ctl.case(isolated.case_id).path('case_config.json'))['branch_type'] == 'manual_variant'


def test_key_contents_never_in_exception(tmp_path):
    path = tmp_path / 'key.txt'; path.write_text('private invalid\ncredential', encoding='utf-8')
    with pytest.raises(api.APIError) as error: api.read_key(path)
    assert 'private invalid' not in str(error.value) and 'private' not in str(error.value)


def test_executor_only_original_instruction_and_bridge_provenance(tmp_path, photo, fixture_json, monkeypatch):
    ctl, case = new_case(tmp_path, photo)
    diag = fixture_json('diagnosis'); diag['tool_plan'] = []
    ctl.import_json(case.case_id, ctl.current_task(case.case_id).task_id, diag, 'fixture')
    ctl.import_json(case.case_id, ctl.current_task(case.case_id).task_id, fixture_json('composition'), 'fixture')
    req = ctl.current_task(case.case_id); config = read_json(case.path('case_config.json'))
    body, model, assets = api.build_request(case, req, config)
    assert len(assets) == 1 and assets[0]['path'] == 'input/canonical.png'
    assert body['contents'][0]['parts'][0]['text'] == req.context['instruction']
    assert model == 'gemini-3-pro-image' and len(body['contents']) == 1
    buffer = io.BytesIO(); Image.new('RGB', (64, 48), 'orange').save(buffer, format='PNG')
    response = {'modelVersion': 'frozen-test-version', 'candidates': [{'content': {'parts': [
        {'inlineData': {'mimeType': 'image/png', 'data': base64.b64encode(buffer.getvalue()).decode()}}]}}]}
    monkeypatch.setattr(api, 'read_key', lambda *args: 'opaque-testing-key')
    monkeypatch.setattr(api, 'request_json', lambda *args: response)
    receipt = api.run_task(tmp_path, case.case_id)
    assert receipt['generated_images'] == 1 and receipt['next_state'] == 'WAIT_VERIFICATION'
    accepted = read_json(case.path(req.response_file))
    assert accepted['provenance']['writer'] == 'supported_bridge'
    assert accepted['payload']['provider_settings']['model_requested'] == model
    verifier = ctl.current_task(case.case_id)
    verifybody, _, _ = api.build_request(case, verifier, config)
    assert 'instruction' not in verifier.context
    assert req.context['instruction'] not in json.dumps(verifybody)
    assert 'NOT Gemini' in verifybody['contents'][0]['parts'][0]['text']
    assert 'left half is [0,0,0.5,1]' in verifybody['contents'][0]['parts'][0]['text']


def test_unknown_submission_not_repeated(tmp_path, photo, monkeypatch):
    ctl, case = new_case(tmp_path, photo); calls = []
    monkeypatch.setattr(api, 'read_key', lambda *args: 'opaque-testing-key')
    def failure(*args):
        calls.append(1); raise api.APIError('Gemini network failure or timeout; outcome may be unknown')
    monkeypatch.setattr(api, 'request_json', failure)
    with pytest.raises(api.APIError): api.run_task(tmp_path, case.case_id)
    with pytest.raises(ValueError, match='resubmission'): api.run_task(tmp_path, case.case_id)
    assert len(calls) == 1
    req = ctl.current_task(case.case_id)
    receipt = read_json(case.path(f'tasks/{req.task_id}/api/receipt.json'))
    assert receipt['status'] == 'unknown' and 'opaque-testing-key' not in json.dumps(receipt)


def test_changed_asset_rejected_before_network(tmp_path, photo, monkeypatch):
    ctl, case = new_case(tmp_path, photo); req = ctl.current_task(case.case_id)
    Image.new('RGB', (64, 48), 'red').save(case.path('input/canonical.png'))
    with pytest.raises(ValueError, match='changed'):
        api.build_request(case, req, read_json(case.path('case_config.json')))


def test_wrong_route_and_extra_executor_assets_rejected(tmp_path, photo, fixture_json):
    ctl, case = new_case(tmp_path, photo)
    diag = fixture_json('diagnosis'); diag['tool_plan'] = []
    ctl.import_json(case.case_id, ctl.current_task(case.case_id).task_id, diag, 'fixture')
    ctl.import_json(case.case_id, ctl.current_task(case.case_id).task_id, fixture_json('composition'), 'fixture')
    req = ctl.current_task(case.case_id); req.allowed_assets.append(req.allowed_assets[0])
    with pytest.raises(ValueError, match='only the original'):
        api.build_request(case, req, read_json(case.path('case_config.json')))
    cfg = api.configuration('gemini-3-pro-image', 'gemini-2.5-pro'); cfg['gemini_api']['endpoint'] = 'https://elsewhere.invalid'
    with pytest.raises(ValueError): api.validate_configuration(cfg)


def test_explicit_text_retry_retains_unknown_call_and_longer_budget(tmp_path, photo, fixture_json, monkeypatch):
    ctl, case = new_case(tmp_path, photo); calls = []
    monkeypatch.setattr(api, 'read_key', lambda *args: 'opaque-testing-key')
    def failure(*args):
        calls.append(args[-1]); raise api.APIError('Gemini network failure or timeout; outcome may be unknown')
    monkeypatch.setattr(api, 'request_json', failure)
    with pytest.raises(api.APIError): api.run_task(tmp_path, case.case_id)
    first = read_json(case.path(f'tasks/{ctl.current_task(case.case_id).task_id}/api/receipt.json'))
    payload = fixture_json('diagnosis'); payload['tool_plan'] = []
    def success(*args):
        calls.append(args[-1]); return {'modelVersion': 'offline-fixture', 'candidates': [{'content': {'parts': [{'text': json.dumps(payload)}]}}]}
    monkeypatch.setattr(api, 'request_json', success)
    result = api.run_task(tmp_path, case.case_id, retry_text_after_timeout=True)
    assert result['explicit_text_retry'] and result['timeout_seconds'] == 600
    assert result['prior_unknown_call_id'] == first['stateless_call_id']
    archive = case.path(f"tasks/{first['task_id']}/api/attempts/{first['stateless_call_id']}.json")
    assert read_json(archive) == first and len(calls) == 2


def test_text_retry_flag_cannot_regenerate_images(tmp_path, photo, fixture_json, monkeypatch):
    ctl, case = new_case(tmp_path, photo)
    payload = fixture_json('diagnosis'); payload['tool_plan'] = []
    ctl.import_json(case.case_id, ctl.current_task(case.case_id).task_id, payload, 'fixture')
    ctl.import_json(case.case_id, ctl.current_task(case.case_id).task_id, fixture_json('composition'), 'fixture')
    monkeypatch.setattr(api, 'read_key', lambda *args: 'opaque-testing-key')
    def failure(*args): raise api.APIError('Gemini network failure or timeout; outcome may be unknown')
    monkeypatch.setattr(api, 'request_json', failure)
    with pytest.raises(api.APIError): api.run_task(tmp_path, case.case_id)
    with pytest.raises(ValueError, match='resubmission'):
        api.run_task(tmp_path, case.case_id, retry_text_after_timeout=True)
