from __future__ import annotations

from copy import deepcopy
import io
from pathlib import Path
import random

import numpy as np
from PIL import Image, ImageChops

from hre.models import HREError, file_sha256
from hre.storage import atomic_write, read_json, write_json
from .contracts import VERSION, digest, require, seal, text_hash, verify_seal


def pool_contract_sets(bundle, pool_ids):
    require(isinstance(bundle, dict), 'evidence_binding_mismatch', 'Evidence must describe one pool')
    if 'freeze_hash' in bundle:
        verify_seal(bundle)
    entries = bundle.get('candidates', [])
    require(isinstance(entries, list), 'evidence_binding_mismatch', 'Evidence candidates must be a list')
    result = {'passed': set(), 'failed': set(), 'unknown': set(pool_ids)}
    seen = set()
    for entry in entries:
        require(isinstance(entry, dict), 'evidence_binding_mismatch', 'Evidence candidate must be an object')
        cid, gate = entry.get('candidate_id'), entry.get('hard_gate')
        require(isinstance(cid, str) and cid in pool_ids and cid not in seen
                and gate in {'passed', 'failed', 'unknown'},
                'evidence_binding_mismatch', 'Evidence has a foreign, duplicate or invalid candidate gate')
        seen.add(cid)
        if gate != 'unknown':
            result['unknown'].discard(cid)
            result[gate].add(cid)
    return result


def _online_path(root, value):
    require(isinstance(value, (str, Path)), 'artifact_missing', 'An online artifact path is required')
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    require(resolved.is_relative_to(root), 'artifact_path_invalid', 'Online artifact is outside this case')
    relative = resolved.relative_to(root)
    require('offline' not in {part.lower() for part in relative.parts}, 'gt_isolation_violation', 'Online evidence cannot read offline artifacts')
    for ancestor in [path, *path.parents]:
        if ancestor == root.parent:
            break
        require(not ancestor.is_symlink(), 'artifact_path_invalid', 'Online artifacts cannot use symbolic links')
    require(resolved.is_file(), 'artifact_missing', 'Online artifact does not exist')
    return resolved


def _save_png(path, image):
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    atomic_write(path, buffer.getvalue())
    return file_sha256(path)


def _validate_rois(rois, source):
    require(isinstance(rois, list), 'roi_registry_invalid', 'ROI registry must be a list')
    seen = set()
    for roi in rois:
        identifier, box = roi.get('id'), roi.get('box')
        require(isinstance(identifier, str) and identifier not in seen, 'roi_registry_invalid', 'ROI IDs must be unique')
        require(isinstance(box, list) and len(box) == 4 and all(type(value) is int for value in box)
                and 0 <= box[0] < box[2] <= source['width'] and 0 <= box[1] < box[3] <= source['height'],
                'roi_registry_invalid', 'ROI lies outside canonical LQ')
        require(roi.get('canonical_source_sha256', source['canonical_source_sha256']) == source['canonical_source_sha256'],
                'roi_binding_invalid', 'ROI registry belongs to another source')
        seen.add(identifier)


def _check_source(root, source, prepared, plan):
    source_path = _online_path(root, source['path'])
    require(source['sha256'] == source['canonical_source_sha256'] == file_sha256(source_path),
            'source_modified', 'Canonical LQ bytes changed')
    require(plan.get('source_hash') == source['canonical_source_sha256'], 'source_binding_mismatch', 'Plan belongs to another source')
    require(prepared['source']['canonical_source_sha256'] == source['canonical_source_sha256'],
            'source_binding_mismatch', 'Prepared source belongs to another canonical LQ')
    require(prepared['geometry_sha256'] == digest(prepared['geometry']), 'geometry_modified', 'Prepared geometry changed')
    path = _online_path(root, prepared['path'])
    require(prepared['sha256'] == prepared['prepared_source_sha256'] == file_sha256(path),
            'prepared_source_modified', 'Prepared execution input changed')
    geometry = prepared['geometry']
    with Image.open(source_path) as image:
        image.load()
        require(image.mode == 'RGB' and image.size == (source['width'], source['height']),
                'source_format_invalid', 'Canonical LQ format or dimensions changed')
    with Image.open(path) as image:
        image.load()
        require(image.mode == 'RGB' and image.size == (geometry['padded_width'], geometry['padded_height']),
                'prepared_source_modified', 'Prepared input format or dimensions changed')
    return source_path


def _check_candidate(root, spec, artifact, source, prepared, mode):
    require(artifact.get('status') == 'completed', 'candidate_not_completed', 'Candidate has no completed generation')
    require(spec['source_hash'] == source['canonical_source_sha256'], 'source_binding_mismatch', 'Candidate source differs from the plan')
    require(spec['prompt_hash'] == text_hash(spec['full_prompt']), 'prompt_modified', 'Plan Prompt changed')
    manifest_path = _online_path(root, artifact.get('manifest_path'))
    manifest = read_json(manifest_path)
    manifest_hash = manifest.get('execution_manifest_sha256')
    require(manifest_hash == artifact.get('manifest_sha256')
            and manifest_hash == digest({key: value for key, value in manifest.items() if key != 'execution_manifest_sha256'}),
            'execution_manifest_mismatch', 'Frozen execution manifest changed')
    require(manifest.get('spec') == spec and manifest.get('prepared') == prepared,
            'execution_manifest_mismatch', 'Manifest differs from the frozen plan or prepared source')
    request = manifest['request']
    require(request.get('seed') == spec['seed'] and request.get('brief') == spec['full_prompt']
            and request.get('inputs') == [{'role': 'source', 'path': prepared['path'],
                                         'sha256': prepared['prepared_source_sha256'],
                                         'width': prepared['geometry']['padded_width'], 'height': prepared['geometry']['padded_height'], 'mode': 'RGB'}],
            'execution_manifest_mismatch', 'Request does not retain the frozen seed, Prompt and only LQ input')
    receipt = artifact.get('receipt')
    require(isinstance(receipt, dict), 'receipt_missing', 'Completed candidate requires a bound receipt')
    expected = {'canonical_source_sha256': source['canonical_source_sha256'],
                'prepared_source_sha256': prepared['prepared_source_sha256'], 'geometry_sha256': prepared['geometry_sha256'],
                'condition_text_sha256': spec['prompt_hash'], 'execution_manifest_sha256': manifest_hash,
                'seed': spec['seed'], 'editor_config_sha256': digest(manifest['editor']),
                'execution_request_sha256': digest(request)}
    require(all(receipt.get(key) == value for key, value in expected.items()), 'receipt_binding_mismatch', 'Receipt source, seed or execution binding differs')
    require(receipt.get('fixture_only') == (mode == 'fixture'), 'receipt_mode_mismatch', 'Fixture and real receipts cannot be mixed')
    native_path = _online_path(root, artifact.get('native_image'))
    output_path = _online_path(root, artifact.get('delivered_image'))
    require(file_sha256(native_path) == artifact.get('native_sha256') == receipt.get('native_sha256'),
            'native_output_modified', 'Native image bytes differ from the receipt')
    require(file_sha256(output_path) == artifact.get('sha256') == receipt.get('delivered_sha256'),
            'delivered_output_modified', 'Delivered image bytes differ from the receipt')
    geometry = prepared['geometry']
    with Image.open(native_path) as native, Image.open(output_path) as output:
        native.load()
        output.load()
        require(native.mode in {'RGB', 'RGBA'} and output.mode == 'RGB', 'output_format_invalid', 'Outputs must be eight-bit RGB or opaque native RGBA')
        if native.mode == 'RGBA':
            require(native.getchannel('A').getextrema() == (255, 255), 'output_alpha_invalid', 'Native alpha must be opaque')
        require(native.size == (geometry['canvas_width'], geometry['canvas_height']),
                'native_geometry_invalid', 'Native dimensions do not match the declared canvas')
        expected_size = (source['width'] * geometry['scale'], source['height'] * geometry['scale'])
        require(output.size == expected_size and (artifact.get('width'), artifact.get('height')) == expected_size,
                'delivered_geometry_invalid', 'Delivered dimensions do not match task scale')
        crop = native.convert('RGB').crop(tuple(geometry['crop']))
        require(crop.size == expected_size and ImageChops.difference(crop, output).getbbox() is None,
                'delivery_mapping_invalid', 'Delivered pixels are not the exact declared native crop')
    return output_path


def _crop_refs(image, rois, directory, alias, scale):
    result = []
    for roi in rois:
        box = tuple(value * scale for value in roi['box'])
        path = directory / (alias + '_' + roi['id'] + '.png')
        sha = _save_png(path, image.crop(box))
        result.append({'region_id': roi['id'], 'path': str(path), 'sha256': sha,
                       'ref_id': alias + '_' + roi['id'], 'box_lq': list(roi['box']),
                       'box_transmitted': list(box)})
    return result


def _matches(selector, rois):
    if selector in ('__full__', 'whole', 'full_frame'):
        return ['__full__']
    if isinstance(selector, str):
        if selector == 'all':
            return [roi['id'] for roi in rois]
        if selector.startswith('all_'):
            domain = selector[4:]
            if domain in {'face', 'people', 'persons'}:
                domain = 'person'
            return [roi['id'] for roi in rois if roi['semantic_type'] == domain]
        return [roi['id'] for roi in rois if roi['id'] == selector]
    if isinstance(selector, list):
        return [roi['id'] for roi in rois if roi['id'] in selector]
    if isinstance(selector, dict):
        require(set(selector) <= {'semantic_type', 'region_ids', 'ids'}, 'region_selector_invalid', 'Unknown region selector field')
        return [roi['id'] for roi in rois if ('semantic_type' not in selector or roi['semantic_type'] == selector['semantic_type'])
                and ('region_ids' not in selector or roi['id'] in selector['region_ids'])
                and ('ids' not in selector or roi['id'] in selector['ids'])]
    raise HREError('region_selector_invalid', 'Unsupported critical attribute selector')


def _critical_instances(task, rois):
    instances = []
    for attribute_id, attribute in [('__restoration__', 'restoration'), ('__artifacts__', 'artifacts')]:
        instances.append({'check_id': attribute_id + ':__full__', 'attribute_id': attribute_id,
                          'region_id': '__full__', 'attribute': attribute, 'required_for_acceptance': True,
                          'verification_requirement': 'visible_consistency', 'allow_unverifiable': False, 'available': True})
    seen = set()
    for attribute in task.get('critical_attributes', []):
        identifier = attribute['attribute_id']
        require(identifier not in seen and identifier not in {'__restoration__', '__artifacts__'},
                'attribute_duplicate', 'Critical attribute IDs must be unique and cannot replace whole-image checks')
        seen.add(identifier)
        regions = _matches(attribute['region_selector'], rois)
        required = attribute['required_for_acceptance']
        for region_id in regions or ['__missing__']:
            available = region_id != '__missing__'
            instances.append({'check_id': identifier + ':' + region_id, 'attribute_id': identifier,
                              'region_id': region_id, 'attribute': attribute['attribute'],
                              'required_for_acceptance': required, 'verification_requirement': attribute['verification_requirement'],
                              'allow_unverifiable': bool(attribute.get('allow_unverifiable', False)),
                              'available': available, 'reason': None if available else 'required_roi_missing'})
    return instances


def _measurements(source_image, candidate_image, candidate, source, prepared, rois):
    result = []
    scale = prepared['geometry']['scale']
    regions = [('__full__', source_image, candidate_image)]
    for roi in rois:
        regions.append((roi['id'], source_image.crop(tuple(roi['box'])),
                        candidate_image.crop(tuple(value * scale for value in roi['box']))))
    for region_id, lq_image, output_image in regions:
        pixels = np.asarray(output_image, dtype=np.float32) / 255
        luminance = pixels @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
        dx = np.abs(np.diff(luminance, axis=1)).mean() if luminance.shape[1] > 1 else 0
        dy = np.abs(np.diff(luminance, axis=0)).mean() if luminance.shape[0] > 1 else 0
        downsampled = output_image.resize(lq_image.size, Image.Resampling.BICUBIC)
        difference = np.asarray(downsampled, dtype=np.float32) - np.asarray(lq_image, dtype=np.float32)
        values = [('clipping_ratio', float(np.mean(np.any((pixels <= 0) | (pixels >= 1), axis=-1))), None),
                  ('edge_energy', float((dx + dy) / 2), 'Sharpness evidence is not a content or naturalness verdict'),
                  ('lr_consistency', float(np.mean(np.abs(difference)) / 255), 'proxy: declared bicubic downsample; true degradation may be unknown')]
        for method, value, limitation in values:
            result.append({'candidate_id': candidate['alias'], 'source_sha256': source['canonical_source_sha256'],
                           'candidate_sha256': candidate['image_sha256'], 'roi_id': region_id,
                           'geometry_sha256': prepared['geometry_sha256'], 'method_id': method,
                           'method_version': 'candidates_v1', 'value': value, 'status': 'measured',
                           'limitations': [limitation] if limitation else []})
        for method in ('ocr', 'face_landmarks'):
            result.append({'candidate_id': candidate['alias'], 'source_sha256': source['canonical_source_sha256'],
                           'candidate_sha256': candidate['image_sha256'], 'roi_id': region_id,
                           'geometry_sha256': prepared['geometry_sha256'], 'method_id': method,
                           'method_version': 'not_deployed', 'value': None, 'status': 'missing',
                           'limitations': ['No post-generation measurement adapter configured; not evidence of absence']})
    return result


def collect_evidence(root, task, plan, artifacts, source, prepared, config, *, output_root=None):
    root = Path(root).resolve()
    destination = Path(output_root).resolve() if output_root is not None else root
    require(destination.is_relative_to(root) and 'offline' not in {part.lower() for part in destination.relative_to(root).parts},
            'evidence_output_invalid', 'Evidence output must remain in the online case directory')
    verify_seal(plan)
    rois = deepcopy(plan.get('roi_registry', []))
    _validate_rois(rois, source)
    require(prepared['geometry']['scale'] == task['scale'], 'geometry_binding_mismatch', 'Evidence scale differs from the task')
    specs = plan['candidate_specs']
    require(len({spec['candidate_id'] for spec in specs}) == len(specs), 'candidate_duplicate', 'Plan candidate IDs must be unique')
    require(isinstance(artifacts, list) and len({item['candidate_id'] for item in artifacts}) == len(artifacts),
            'candidate_duplicate', 'Artifact candidate IDs must be unique')
    indexed_artifacts = {item['candidate_id']: item for item in artifacts}
    require(set(indexed_artifacts) <= {spec['candidate_id'] for spec in specs}, 'candidate_binding_mismatch', 'Unplanned artifact in candidate pool')
    source_failure = None
    try:
        source_path = _check_source(root, source, prepared, plan)
    except (HREError, OSError, KeyError, ValueError) as error:
        source_failure = {'code': getattr(error, 'code', 'source_invalid'), 'message': str(error)}
        source_path = None
    order = list(specs)
    random.Random(int(digest({'source': source['canonical_source_sha256'], 'candidate_ids': [item['candidate_id'] for item in specs]})[:16], 16)).shuffle(order)
    aliases = {f'A{index + 1:02d}': spec['candidate_id'] for index, spec in enumerate(order)}
    alias_by_id = {identifier: alias for alias, identifier in aliases.items()}
    directory = destination / 'evidence' / 'anonymous_images'
    directory.mkdir(parents=True, exist_ok=True)
    source_ref = {'path': None, 'sha256': source['canonical_source_sha256'], 'width': source['width'], 'height': source['height'],
                  'ref_id': 'source_full', 'roi_images': [], 'canonical_source_sha256': source['canonical_source_sha256']}
    source_image = None
    if source_path:
        source_image = Image.open(source_path).convert('RGB')
        anonymous_source = directory / 'source.png'
        source_ref['sha256'] = _save_png(anonymous_source, source_image)
        source_ref['path'] = str(anonymous_source)
        source_ref['roi_images'] = _crop_refs(source_image, rois, directory, 'source', 1)
    candidates, measurements = [], []
    for spec in order:
        candidate_id, alias = spec['candidate_id'], alias_by_id[spec['candidate_id']]
        artifact = indexed_artifacts.get(candidate_id, {'candidate_id': candidate_id, 'status': 'missing'})
        entry = {'candidate_id': candidate_id, 'slot_id': spec['slot_id'], 'alias': alias, 'image_path': None,
                 'image_sha256': None, 'ref_id': alias + '_full', 'hard_gate': 'unknown', 'hard_gate_reasons': [], 'roi_images': []}
        try:
            require(source_failure is None, 'source_binding_invalid', 'Shared source or prepared input failed verification')
            output_path = _check_candidate(root, spec, artifact, source, prepared, config['mode'])
            with Image.open(output_path) as loaded:
                image = loaded.convert('RGB')
            anonymous_path = directory / (alias + '.png')
            entry['image_sha256'] = _save_png(anonymous_path, image)
            entry['image_path'] = str(anonymous_path)
            entry['roi_images'] = _crop_refs(image, rois, directory, alias, task['scale'])
            entry['hard_gate'] = 'passed'
            entry['delivered_sha256'] = artifact['sha256']
            try:
                measurements.extend(_measurements(source_image, image, entry, source, prepared, rois))
                change = ImageChops.difference(image, source_image.resize(image.size, Image.Resampling.BICUBIC))
                _save_png(destination / 'evidence' / 'change_maps' / (alias + '.png'), change)
            except (OSError, ValueError, TypeError, HREError) as measurement_error:
                measurements.append({'candidate_id': alias, 'source_sha256': source['canonical_source_sha256'],
                                     'candidate_sha256': entry['image_sha256'], 'roi_id': '__full__',
                                     'geometry_sha256': prepared['geometry_sha256'], 'method_id': 'soft_evidence',
                                     'method_version': 'candidates_v1', 'value': None, 'status': 'failed',
                                     'limitations': [str(measurement_error)]})
        except (HREError, OSError, ValueError, KeyError, TypeError) as error:
            entry['hard_gate'] = 'unknown' if artifact.get('status') == 'unknown' else 'failed'
            entry['hard_gate_reasons'].append({'code': getattr(error, 'code', 'artifact_invalid'), 'message': str(error)})
            if source_failure:
                entry['hard_gate_reasons'].append(source_failure)
        candidates.append(entry)
    baseline = next((spec['candidate_id'] for spec in specs if spec['slot_id'] == 'C0'), None)
    pool_hash = digest({'source': source['canonical_source_sha256'], 'geometry': prepared['geometry_sha256'],
                        'rois': rois, 'slots': [{'candidate_id': spec['candidate_id'], 'prompt_hash': spec['prompt_hash'], 'seed': spec['seed']}
                                              for spec in specs],
                        'outputs': [{'candidate_id': item['candidate_id'], 'image_sha256': item['image_sha256'], 'hard_gate': item['hard_gate']}
                                    for item in candidates]})
    bundle = seal({'schema_version': VERSION, 'source': source_ref, 'candidates': candidates, 'roi_registry': rois,
                   'measurements': measurements, 'anonymous_measurements': deepcopy(measurements),
                   'critical_instances': _critical_instances(task, rois), 'aliases': aliases, 'baseline_id': baseline,
                   'pool_hash': pool_hash, 'geometry_sha256': prepared['geometry_sha256'],
                   'fixture_only': config['mode'] == 'fixture', 'source_failure': source_failure})
    write_json(destination / 'evidence' / 'aliases.json', {'aliases': aliases, 'pool_hash': pool_hash})
    write_json(destination / 'evidence' / 'bundle.json', bundle)
    return bundle
