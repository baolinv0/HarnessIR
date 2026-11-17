"""Build and verify a bounded source bundle for an offline execution computer."""
import argparse
from hashlib import sha256
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import zipfile


BASELINE_SHA = 'd44d40fa209a9978d37ce38efa9a6ef89abe7432'
DIRECTORIES = ('engine/src', 'engine/tests', 'engine/examples/restoration_candidates_v1',
               'harness', 'prompts', 'docs/restoration_candidates_v1')
FILES = ('LICENSE', 'requirements.txt', 'engine/pyproject.toml',
         'engine/requirements-lock.txt', 'engine/requirements-native-image.txt',
         'engine/requirements-native-pe.txt', 'tools/build_candidates_bundle.py')
FORBIDDEN_PARTS = {'.git', '.work', 'runs', '__pycache__', '.pytest_cache', '.venv', 'venv',
                   'credentials', 'secrets', 'checkpoints', 'weights', 'node_modules'}
FORBIDDEN_SUFFIXES = {'.pyc', '.pyo', '.exe', '.dll', '.pyd', '.so', '.pem', '.key', '.p12', '.pfx'}


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode('utf-8')


def _safe_relative(relative):
    value = PurePosixPath(relative)
    if value.is_absolute() or not value.parts or '..' in value.parts or '\\' in relative or ':' in relative:
        raise ValueError('unsafe archive path: ' + relative)
    return value


def _excluded(relative):
    path = _safe_relative(relative)
    name = path.name.lower()
    return (any(part.lower() in FORBIDDEN_PARTS or part.lower().endswith(('.egg-info', '.dist-info')) for part in path.parts)
            or name == '.env' or name.startswith('.env.') or '.local.' in name
            or name in {'runtime.local.json', 'config.local.json', 'credentials.json', 'secrets.json'}
            or path.suffix.lower() in FORBIDDEN_SUFFIXES)


def _git(root, *args):
    try:
        return subprocess.run(['git', '-C', str(root), *args], capture_output=True, check=False, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None


def _identity(root):
    head = _git(root, 'rev-parse', 'HEAD')
    if head is None or head.returncode:
        return {'available': False, 'commit': None, 'dirty': None, 'baseline_fidelity_verified': False}
    status = _git(root, 'status', '--porcelain=v1', '--untracked-files=normal')
    base = _git(root, 'cat-file', '-e', BASELINE_SHA + '^{commit}')
    diff = _git(root, 'diff', '--quiet', BASELINE_SHA, '--', 'harness', 'prompts')
    return {'available': True, 'commit': head.stdout.decode('ascii').strip(),
            'dirty': bool(status and status.stdout),
            'baseline_fidelity_verified': bool(base and base.returncode == 0 and diff and diff.returncode == 0)}


def _source_files(root):
    selected = {}
    for relative in DIRECTORIES:
        directory = root / relative
        if directory.is_symlink():
            raise ValueError('symlink in source selection: ' + relative)
        if not directory.exists():
            continue
        for path in sorted(directory.rglob('*')):
            relative_path = path.relative_to(root).as_posix()
            if path.is_symlink():
                raise ValueError('symlink in source selection: ' + relative_path)
            if path.is_file() and not _excluded(relative_path):
                selected[relative_path] = path.read_bytes()
    for relative in FILES:
        path = root / relative
        if path.is_symlink():
            raise ValueError('symlink in source selection: ' + relative)
        if path.is_file():
            selected[relative] = path.read_bytes()
    if 'engine/pyproject.toml' not in selected or not any(p.startswith('engine/src/hre/candidates/') for p in selected):
        raise ValueError('Repository does not contain the candidate source and package definition')
    return selected


def build_bundle(repository, out, wheel=None):
    root, out = Path(repository).resolve(), Path(out).resolve()
    selected = _source_files(root)
    git_identity = _identity(root)
    source_identity = {'baseline_sha': BASELINE_SHA,
                       'baseline_fidelity_verified': git_identity['baseline_fidelity_verified'],
                       'source_files': {name: sha256(data).hexdigest() for name, data in selected.items()
                                        if name.startswith(('harness/', 'prompts/'))}}
    selected['SOURCE_IDENTITY.json'] = _json_bytes(source_identity)
    if wheel is not None:
        wheel = Path(wheel)
        if wheel.is_symlink() or not wheel.is_file() or wheel.suffix != '.whl' or not zipfile.is_zipfile(wheel):
            raise ValueError('Supply a real nonsymlink wheel file')
        _verify_wheel_source(wheel.read_bytes(), selected)
        selected['wheels/' + wheel.name] = wheel.read_bytes()
    manifest = {'schema_version': 'hre_candidates_offline_bundle_v1', 'baseline_sha': BASELINE_SHA,
                'current_git': git_identity, 'model_execution_verified': False,
                'dependency_wheels_included': False,
                'files': [{'path': name, 'size': len(data), 'sha256': sha256(data).hexdigest()}
                          for name, data in sorted(selected.items())]}
    manifest_bytes = _json_bytes(manifest)
    identity = sha256(manifest_bytes).hexdigest()
    out.mkdir(parents=True, exist_ok=True)
    archive = out / ('restoration-candidates-' + identity[:16] + '.zip')
    if archive.exists():
        if verify_bundle(archive) != manifest:
            raise ValueError('Existing archive does not match this source snapshot')
        return archive
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as target:
        for name, data in sorted({**selected, 'MANIFEST.json': manifest_bytes}.items()):
            info = zipfile.ZipInfo('HarnessIR/' + name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            target.writestr(info, data)
    verify_bundle(archive)
    archive.with_suffix('.zip.sha256').write_text(sha256(archive.read_bytes()).hexdigest() + '  ' + archive.name + '\n', encoding='ascii')
    return archive


def _verify_wheel_source(wheel_bytes, selected):
    expected = {name.removeprefix('engine/src/'): data for name, data in selected.items() if name.startswith('engine/src/hre/')}
    with zipfile.ZipFile(io.BytesIO(wheel_bytes)) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError('Duplicate wheel members')
        for name in names:
            _safe_relative(name)
        metadata = [name for name in names if name.endswith('.dist-info/WHEEL')]
        if len(metadata) != 1 or not archive.read(metadata[0]).decode('utf-8').lower().count('root-is-purelib: true'):
            raise ValueError('Supply a pure Python engine wheel')
        if set(expected) != {name for name in names if name.startswith('hre/')}:
            raise ValueError('wheel/source package file lists differ')
        for name, data in expected.items():
            if archive.read(name) != data:
                raise ValueError('wheel/source content mismatch: ' + name)


def verify_bundle(archive):
    with zipfile.ZipFile(archive) as source:
        names = source.namelist()
        if len(names) != len(set(names)):
            raise ValueError('Duplicate archive entries')
        for name in names:
            path = _safe_relative(name)
            if path.parts[0] != 'HarnessIR' or _excluded(name):
                raise ValueError('unsafe archive member: ' + name)
            if source.getinfo(name).external_attr >> 16 & 0o170000 == 0o120000:
                raise ValueError('unsafe symlink archive member: ' + name)
        manifest = json.loads(source.read('HarnessIR/MANIFEST.json'))
        if manifest.get('schema_version') != 'hre_candidates_offline_bundle_v1':
            raise ValueError('Unknown bundle manifest')
        records = manifest.get('files', [])
        expected = {'HarnessIR/' + item['path'] for item in records} | {'HarnessIR/MANIFEST.json'}
        if len(records) != len({item['path'] for item in records}) or set(names) != expected:
            raise ValueError('Archive contains missing or unlisted files')
        for item in records:
            _safe_relative(item['path'])
            data = source.read('HarnessIR/' + item['path'])
            if len(data) != item['size'] or sha256(data).hexdigest() != item['sha256']:
                raise ValueError('File size or hash mismatch: ' + item['path'])
        identity = json.loads(source.read('HarnessIR/SOURCE_IDENTITY.json'))
        if identity.get('baseline_sha') != manifest.get('baseline_sha'):
            raise ValueError('Source baseline identity mismatch')
        mapped = {item['path']: item['sha256'] for item in records if item['path'].startswith(('harness/', 'prompts/'))}
        if identity.get('source_files') != mapped:
            raise ValueError('Source identity file map mismatch')
        selected = {item['path']: source.read('HarnessIR/' + item['path']) for item in records if item['path'].startswith('engine/src/hre/')}
        for item in records:
            if item['path'].startswith('wheels/'):
                _verify_wheel_source(source.read('HarnessIR/' + item['path']), selected)
        return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--out', type=Path)
    parser.add_argument('--wheel', type=Path)
    parser.add_argument('--verify', type=Path)
    args = parser.parse_args(argv)
    if args.verify:
        manifest = verify_bundle(args.verify)
        print(json.dumps({'verified': str(args.verify), 'files': len(manifest['files']), 'baseline_sha': manifest['baseline_sha']}))
    else:
        parser.error('--out is required when building') if args.out is None else None
        print(build_bundle(args.repository, args.out, args.wheel))


if __name__ == '__main__':
    main()
