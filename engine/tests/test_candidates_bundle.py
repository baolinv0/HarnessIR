from pathlib import Path
import importlib.util
import json
import zipfile

import pytest


def builder():
    path = Path(__file__).parents[2] / 'tools' / 'build_candidates_bundle.py'
    spec = importlib.util.spec_from_file_location('candidate_bundle', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def small_repository(tmp_path):
    root = tmp_path / 'repo'
    for relative, content in {'engine/src/hre/candidates/cli.py': 'print("fixture")\n',
                              'harness/__init__.py': '', 'prompts/compose.txt': 'restore',
                              'LICENSE': 'license', 'engine/pyproject.toml': '[project]\nname="example"\n',
                              'docs/restoration_candidates_v1/RUNBOOK.md': '# Run\n',
                              'engine/src/hre/candidates/runtime.local.json': '{"api_key":"secret"}',
                              'engine/src/hre/candidates/__pycache__/cli.pyc': 'compiled',
                              'engine/src/hre/candidates/.env': 'SECRET=1',
                              'runs/case/input.png': 'private', '.git/config': 'git',
                              '.work/local/python.exe': 'executable'}.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
    return root


def test_bundle_contains_source_and_hashes_but_not_runtime_or_secrets(tmp_path):
    module = builder()
    archive = module.build_bundle(small_repository(tmp_path), tmp_path / 'delivery')
    manifest = module.verify_bundle(archive)
    assert manifest['baseline_sha'] == 'd44d40fa209a9978d37ce38efa9a6ef89abe7432'
    with zipfile.ZipFile(archive) as source:
        names = source.namelist()
        assert 'HarnessIR/engine/src/hre/candidates/cli.py' in names
        assert 'HarnessIR/docs/restoration_candidates_v1/RUNBOOK.md' in names
        assert not any(part in name for name in names for part in ('.git/', '.work/', 'runs/', '__pycache__', '.env', 'runtime.local.json', 'python.exe'))
        for item in manifest['files']:
            assert item['size'] == len(source.read('HarnessIR/' + item['path']))
    assert archive.with_suffix('.zip.sha256').is_file()


def test_verifier_rejects_modified_bytes_and_unlisted_files(tmp_path):
    module = builder()
    archive = module.build_bundle(small_repository(tmp_path), tmp_path / 'delivery')
    tampered = tmp_path / 'tampered.zip'
    with zipfile.ZipFile(archive) as source, zipfile.ZipFile(tampered, 'w') as target:
        for name in source.namelist():
            data = source.read(name)
            target.writestr(name, b'changed' if name.endswith('/cli.py') else data)
    with pytest.raises(ValueError, match='hash|size'):
        module.verify_bundle(tampered)
    with zipfile.ZipFile(archive, 'a') as target:
        target.writestr('HarnessIR/../../escape', 'no')
    with pytest.raises(ValueError, match='unsafe|unlisted'):
        module.verify_bundle(archive)


def test_bundle_optional_wheel_and_repeated_build_are_verifiable(tmp_path):
    module = builder()
    root = small_repository(tmp_path)
    wheel = tmp_path / 'example-1.0-py3-none-any.whl'
    with zipfile.ZipFile(wheel, 'w') as target:
        target.writestr('hre/candidates/cli.py', (root / 'engine/src/hre/candidates/cli.py').read_bytes())
        target.writestr('example-1.0.dist-info/WHEEL', 'Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n')
        target.writestr('example-1.0.dist-info/METADATA', 'Metadata-Version: 2.1\nName: example\nVersion: 1.0\n')
        target.writestr('example-1.0.dist-info/RECORD', '')
    first = module.build_bundle(root, tmp_path / 'delivery', wheel)
    second = module.build_bundle(root, tmp_path / 'delivery', wheel)
    assert first == second
    manifest = module.verify_bundle(first)
    assert any(x['path'] == 'wheels/' + wheel.name for x in manifest['files'])


def test_bundle_rejects_stale_wheel_source(tmp_path):
    module = builder()
    root = small_repository(tmp_path)
    wheel = tmp_path / 'example-1.0-py3-none-any.whl'
    with zipfile.ZipFile(wheel, 'w') as target:
        target.writestr('hre/candidates/cli.py', 'print("old source")\n')
        target.writestr('example-1.0.dist-info/WHEEL', 'Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n')
        target.writestr('example-1.0.dist-info/METADATA', 'Name: example\nVersion: 1.0\n')
        target.writestr('example-1.0.dist-info/RECORD', '')
    with pytest.raises(ValueError, match='wheel.*source|source.*wheel'):
        module.build_bundle(root, tmp_path / 'delivery', wheel)


def test_bundle_rejects_symlinked_source(tmp_path):
    module = builder()
    root = small_repository(tmp_path)
    source = root / 'engine/src/link.py'
    try:
        source.symlink_to(root / 'LICENSE')
    except OSError:
        pytest.skip('Host does not permit creating symlinks')
    with pytest.raises(ValueError, match='symlink'):
        module.build_bundle(root, tmp_path / 'delivery')


def test_real_examples_parse_but_unconfigured_deployment_blocks():
    from hre.candidates.bridge import preflight
    from hre.candidates.contracts import parse_config, parse_task
    root = Path(__file__).parents[1] / 'examples' / 'restoration_candidates_v1'
    config = parse_config(json.loads((root / 'runtime.real.example.json').read_text('utf-8')))
    task = parse_task(json.loads((root / 'task.example.json').read_text('utf-8')))
    assert config['mode'] == 'real'
    assert config['editor']['model_id'] == 'Qwen/Qwen-Image-2.1'
    assert 'compiler' not in config and 'fixture' not in json.loads((root / 'runtime.real.example.json').read_text('utf-8'))
    assert task['scale'] == 4
    assert preflight(config)['status'] == 'blocked'
