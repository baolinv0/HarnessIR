"""Validate the design package, not the unimplemented Controller or user device."""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import re
import sys

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from jinja2 import Environment, FileSystemLoader, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]

def load(path: Path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f'duplicate JSON key: {key}')
            result[key] = value
        return result
    def bad_constant(value):
        raise ValueError(f'nonfinite JSON constant: {value}')
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=pairs,
                      parse_constant=bad_constant)

def main() -> int:
    counts = {}
    if 'date-time' not in FormatChecker.checkers:
        raise RuntimeError('date-time checker unavailable; install scripts/requirements-validation.txt')
    # All JSON must be well formed, including configs and source locks.
    json_paths = sorted(ROOT.rglob('*.json'))
    for path in json_paths:
        load(path)
    counts['json_files_parsed'] = len(json_paths)

    schema_paths = sorted((ROOT / 'schemas').glob('*.schema.json'))
    schemas = {p.name: load(p) for p in schema_paths}
    registry = Registry().with_resources(
        (s['$id'], Resource.from_contents(s)) for s in schemas.values())
    for s in schemas.values():
        Draft202012Validator.check_schema(s)
    counts['schemas_checked'] = len(schemas)
    def validator(name):
        return Draft202012Validator(schemas[name], registry=registry,
                                   format_checker=FormatChecker())

    mapping = load(ROOT / 'examples/schema_map.json')
    for filename, schema_name in mapping.items():
        validator(schema_name).validate(load(ROOT / 'examples' / filename))
    counts['valid_fixture_checks'] = len(mapping)

    bad_examples = []
    v = load(ROOT / 'examples/verification.json')
    a = copy.deepcopy(v); a['needs_redo'] = 'false'; bad_examples.append(('verification.schema.json', a))
    a = copy.deepcopy(v); a['scores']['fidelity'] = 11; bad_examples.append(('verification.schema.json', a))
    a = copy.deepcopy(v); del a['checklist']['C3']; bad_examples.append(('verification.schema.json', a))
    a = copy.deepcopy(v); a['success'] = True; bad_examples.append(('verification.schema.json', a))
    r = load(ROOT / 'examples/request.json')
    a = copy.deepcopy(r); a['role'] = 'unknown'; bad_examples.append(('request.schema.json', a))
    a = copy.deepcopy(r); a['prompt_file'] = '../escape.txt'; bad_examples.append(('request.schema.json', a))
    a = copy.deepcopy(r); a['prompt_file'] = 'C:/wrong.txt'; bad_examples.append(('request.schema.json', a))
    a = copy.deepcopy(r); a['input_sha256'] = 'x' * 64; bad_examples.append(('request.schema.json', a))
    response = load(ROOT / 'examples/response.json')
    a = copy.deepcopy(response); a['status'] = 'error'; bad_examples.append(('response.schema.json', a))
    a = copy.deepcopy(response); a['provenance']['completed_at'] = 'no date'; bad_examples.append(('response.schema.json', a))
    for schema_name, data in bad_examples:
        if validator(schema_name).is_valid(data):
            raise AssertionError(f'bad fixture unexpectedly accepted: {schema_name}')
    counts['invalid_fixture_rejections'] = len(bad_examples)

    env = Environment(loader=FileSystemLoader(str(ROOT / 'prompts')),
                      undefined=StrictUndefined, autoescape=False)
    context = load(ROOT / 'examples/template_context.json')
    rendered = ROOT / 'examples/rendered'
    rendered.mkdir(exist_ok=True)
    schema_for = {'diagnose':'diagnosis', 'compose':'composition',
                  'refine':'composition', 'verify':'verification',
                  'format_repair':'verification'}
    template_paths = sorted((ROOT / 'prompts').glob('*.j2'))
    for path in template_paths:
        values = dict(context)
        if path.stem in schema_for:
            values['payload_schema_json'] = json.dumps(
                schemas[schema_for[path.stem] + '.schema.json'], ensure_ascii=False, indent=2)
        text = env.get_template(path.name).render(values)
        if '{{' in text or '{%' in text:
            raise AssertionError(f'unrendered variable: {path.name}')
        (rendered / (path.stem + '.txt')).write_text(text, encoding='utf-8')
        if path.stem == 'execute' and text.strip() != context['instruction']:
            raise AssertionError('Execute prompt contains something other than instruction')
        if path.stem == 'verify' and context['instruction'] in text:
            raise AssertionError('Verifier leaked editor instruction')
    counts['prompt_templates_rendered'] = len(template_paths)

    # Verify the pinned MIT source byte-for-byte via Git blob hashes and SHA256.
    lock = load(ROOT / 'reference/source_lock.json')
    for item in lock['files']:
        data = (ROOT / item['local_path']).read_bytes()
        if hashlib.sha256(data).hexdigest() != item['sha256']:
            raise AssertionError(f'source SHA256 mismatch: {item["local_path"]}')
        gitsha = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        if gitsha != item['git_blob_sha']:
            raise AssertionError(f'source Git blob mismatch: {item["local_path"]}')
    counts['official_source_files_verified'] = len(lock['files'])

    # Relative Markdown file links in authored docs must resolve.
    checked_links = 0
    for path in [ROOT / 'START_HERE.md', *(ROOT / 'docs').glob('*.md')]:
        for target in re.findall(r'\[[^\]]+\]\(([^)]+)\)', path.read_text(encoding='utf-8')):
            if '://' in target or target.startswith('#'):
                continue
            p = (path.parent / target.split('#')[0]).resolve()
            if not p.exists():
                raise AssertionError(f'broken link in {path.name}: {target}')
            checked_links += 1
    counts['authored_relative_links_verified'] = checked_links
    manifest_path = ROOT / 'PACKAGE_MANIFEST.json'
    if manifest_path.exists():
        manifest = load(manifest_path)
        for item in manifest['files']:
            p = ROOT / item['path']
            if hashlib.sha256(p.read_bytes()).hexdigest() != item['sha256']:
                raise AssertionError(f'package checksum mismatch: {item["path"]}')
        counts['package_manifest_files_verified'] = len(manifest['files'])
    print(json.dumps({'status':'PASS','checks':counts,
                      'not_tested':['Windows installation','user local filesystem',
                                    'ChatGPT image editing','Controller runtime',
                                    'real photograph experiment']}, ensure_ascii=False, indent=2))
    return 0

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f'FAIL: {exc}', file=sys.stderr)
        raise SystemExit(1)
