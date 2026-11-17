import pytest
from PIL import Image

from hre.models import HREError


def prepared_case(tmp_path, mode="sr_x4"):
    from hre.candidates.bridge import canonicalize_source, prepare_source, build_execution
    from hre.candidates.contracts import candidate_spec
    path = tmp_path / "lq.png"
    Image.new("RGB", (257, 193), (20, 40, 80)).save(path)
    source = canonicalize_source(path, tmp_path / "source")
    prepared = prepare_source(source, {"task_mode": mode, "scale": 4 if mode == "sr_x4" else 1}, tmp_path / "prepared")
    spec = candidate_spec("C0", "baseline", 0, 0, "Restore visible content", source["sha256"])
    return source, prepared, build_execution(spec, prepared, {})


@pytest.mark.parametrize("mode,native,delivered", [("sr_x4", (1056, 800), (1028, 772)), ("restoration_x1", (288, 224), (257, 193))])
def test_geometry_odd_sizes_and_fixture_crop(tmp_path, mode, native, delivered):
    from hre.candidates.bridge import execute_image
    from hre.candidates.journal import Journal
    source, prepared, manifest = prepared_case(tmp_path, mode)
    assert manifest["request"]["canvas"] == {"width": native[0], "height": native[1]}
    assert prepared["prepared_source_sha256"] != source["canonical_source_sha256"]
    result = execute_image(manifest, tmp_path, Journal(tmp_path, {"image_generation": 1}), {"mode": "fixture", "fixture": {}})
    assert Image.open(result["native_image"]).size == native
    assert Image.open(result["delivered_image"]).size == delivered
    assert result["receipt"]["fixture_only"] is True


@pytest.mark.parametrize("field", ["seed", "settings", "source"])
def test_manifest_mutation_rejected_before_submission(tmp_path, field):
    from hre.candidates.bridge import execute_image
    from hre.candidates.journal import Journal
    _, _, manifest = prepared_case(tmp_path)
    if field == "seed":
        manifest["request"]["seed"] += 1
    elif field == "settings":
        manifest["editor"]["settings"]["num_inference_steps"] += 1
    else:
        Image.new("RGB", (264, 200), "red").save(manifest["prepared"]["path"])
    journal = Journal(tmp_path, {"image_generation": 1})
    with pytest.raises(HREError):
        execute_image(manifest, tmp_path, journal, {"mode": "fixture", "fixture": {}})
    assert not journal.snapshot()["operations"]


def test_wrong_native_size_is_not_resized(tmp_path):
    from hre.candidates.bridge import execute_image
    from hre.candidates.journal import Journal
    _, _, manifest = prepared_case(tmp_path)
    with pytest.raises(HREError, match="native_geometry"):
        execute_image(manifest, tmp_path, Journal(tmp_path, {"image_generation": 1}), {"mode": "fixture", "fixture": {"image_behaviors": {"C0": "wrong_size"}}})


def test_transparent_source_is_explicitly_rejected(tmp_path):
    from hre.candidates.bridge import canonicalize_source
    path = tmp_path / "alpha.png"
    Image.new("RGBA", (20, 20), (1, 2, 3, 0)).save(path)
    with pytest.raises(HREError, match="alpha"):
        canonicalize_source(path, tmp_path / "source")


def test_deployment_manifest_mutation_rejected_before_generation(tmp_path):
    from hre.candidates.bridge import build_execution, execute_image
    from hre.candidates.journal import Journal
    from hre.storage import write_json
    source, prepared, manifest = prepared_case(tmp_path)
    deployment = tmp_path / 'deployment.json'
    write_json(deployment, {'identity': 'first'})
    manifest = build_execution(manifest['spec'], prepared, {'deployment_manifest': str(deployment)})
    write_json(deployment, {'identity': 'changed'})
    journal = Journal(tmp_path, {'image_generation': 1})
    with pytest.raises(HREError, match='execution_manifest_mismatch'):
        execute_image(manifest, tmp_path, journal, {'mode': 'fixture', 'fixture': {}})
    assert not journal.snapshot()['operations']


def test_real_preflight_is_blocked_without_deployments():
    from hre.candidates.bridge import preflight
    result = preflight({'mode': 'real', 'stages': {}, 'editor': {}})
    assert result['status'] == 'blocked'
    assert result['fixture_only'] is False


def test_real_adapter_passes_frozen_prompt_seed_and_source_without_rewriting(tmp_path, monkeypatch):
    from hre.candidates.bridge import build_execution, execute_image
    from hre.candidates.journal import Journal
    from hre.models import file_sha256
    from hre.storage import write_json
    import hre.v3.dispatch as dispatch
    import hre.v3.common as common
    _, prepared, original = prepared_case(tmp_path)
    deployment = tmp_path / 'deployment.json'
    write_json(deployment, {'test': 'bound checkpoint'})
    manifest = build_execution(original['spec'], prepared, {'deployment_manifest': str(deployment)})
    monkeypatch.setattr(common, 'model_identity', lambda *args: {'test': 'local model not loaded'})
    calls = []
    def generate(request, condition, editor, output_dir):
        calls.append((request, condition, editor))
        output_dir.mkdir(parents=True)
        path = output_dir / 'native_000.png'
        Image.new('RGBA', (request['canvas']['width'], request['canvas']['height']), (10, 20, 30, 255)).save(path)
        return {'outputs': [{'path': str(path), 'sha256': file_sha256(path)}], 'observation': {'actual_generation_count': 1}}
    monkeypatch.setattr(dispatch, 'generate', generate)
    journal = Journal(tmp_path, {'image_generation': 1})
    first = execute_image(manifest, tmp_path, journal, {'mode': 'real', 'editor': manifest['editor']})
    again = execute_image(manifest, tmp_path, journal, {'mode': 'real', 'editor': manifest['editor']})
    assert len(calls) == 1
    assert calls[0][0]['seed'] == original['spec']['seed']
    assert calls[0][0]['inputs'][0]['path'] == prepared['path']
    assert calls[0][1]['text'] == original['spec']['full_prompt']
    assert first['sha256'] == again['sha256']
    assert first['receipt']['fixture_only'] is False


def test_offline_source_manifest_binds_harness_and_templates(tmp_path):
    from hre.candidates.bridge import preflight
    from hre.models import file_sha256
    from hre.storage import write_json
    paths = ['harness/stages/diagnosis.py', 'harness/stages/compose.py', 'harness/stages/tools.py', 'harness/stages/visuals.py',
             'prompts/diagnosis.txt', 'prompts/compose.txt', 'prompts/compose_blocks.txt']
    files = {}
    for relative in paths:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('original')
        files[relative] = file_sha256(path)
    write_json(tmp_path / 'SOURCE_IDENTITY.json', {'baseline_sha': 'a' * 40, 'source_files': files})
    config = {'mode': 'real', 'harness_source_root': str(tmp_path), 'harness_sha': 'a' * 40, 'stages': {}, 'editor': {}}
    assert next(c for c in preflight(config)['checks'] if c['check'] == 'harness_source_identity')['passed'] is True
    (tmp_path / paths[0]).write_text('modified')
    assert next(c for c in preflight(config)['checks'] if c['check'] == 'harness_source_identity')['passed'] is False
