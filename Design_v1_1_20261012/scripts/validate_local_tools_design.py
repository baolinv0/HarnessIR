"""Validate v1.1 design contracts and synthetic fixtures; never run models."""
import copy
import hashlib
import json
from pathlib import Path
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[1]

def load(relative):
    return json.loads((ROOT / relative).read_text(encoding='utf-8'))

def key(contract):
    data = json.dumps(contract, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')
    return hashlib.sha256(data).hexdigest()

def main():
    schemas = [json.loads(p.read_text()) for p in (ROOT / 'schemas').glob('*.schema.json')]
    registry = Registry().with_resources((s['$id'], Resource.from_contents(s)) for s in schemas)
    by_name = {s['$id'].split('/')[-1]: s for s in schemas}
    def validate(name, data):
        return Draft202012Validator(by_name[name], registry=registry).is_valid(data)

    bad = []
    ocr = load('examples/local_tools/t1_ocr.json')
    x = copy.deepcopy(ocr); x['data']['items'][0]['polygon_norm'] = [[.1,.1],[.3,.1]]
    bad.append(x)
    x = copy.deepcopy(ocr); x['data']['items'][0]['recognition_confidence'] = 1.5
    bad.append(x)
    face = load('examples/local_tools/t2_face.json')
    x = copy.deepcopy(face); del x['data']['faces'][0]['landmarks5_norm']; bad.append(x)
    x = copy.deepcopy(face); x['data']['faces'][0]['landmarks5_norm'] = [[.1,.2]]; bad.append(x)
    depth = load('examples/local_tools/t3_depth.json')
    x = copy.deepcopy(depth); x['data']['dtype'] = 'uint8'; bad.append(x)
    x = copy.deepcopy(depth); x['data']['representation'] = 'metric_metres'; bad.append(x)
    x = copy.deepcopy(depth); x['data']['larger_is'] = 'unknown'; bad.append(x)
    seg = load('examples/local_tools/t4_segmentation.json')
    x = copy.deepcopy(seg); x['data']['unknown_id'] = 1; bad.append(x)
    x = copy.deepcopy(seg); x['data']['native_masks'][0]['mask_path'] = '../outside.png'; bad.append(x)
    x = copy.deepcopy(seg); x['backend']['environment_lock_sha256'] = 'unlocked'; bad.append(x)
    for x in bad:
        assert not validate('evidence_local.schema.json', x), 'Bad local fixture unexpectedly accepted'

    contract = load('examples/local_tools/cache_contract.json')
    expected = key(contract)
    assert load('examples/local_tools/tool_job.json')['cache_key'] == expected
    assert load('examples/local_tools/t1_ocr.json')['cache_key'] == expected
    assert load('examples/local_tools/evidence_binding.json')['cache_key'] == expected
    assert key(copy.deepcopy(contract)) == expected
    different = []
    for field, value in [('canonical_sha256','d'*64),('model_bundle_sha256','e'*64),
                         ('adapter_version','adapter-v2'),('prompt_set_sha256','f'*64),
                         ('roi_policy_id','hardcase-roi-v1')]:
        x = copy.deepcopy(contract); x[field] = value; different.append(x)
    for field, value in [('device','cuda:0'),('precision','fp16'),
                         ('framework_version','1'),('environment_lock_sha256','f'*64)]:
        x = copy.deepcopy(contract); x['backend'][field] = value; different.append(x)
    x = copy.deepcopy(contract); x['parameters']['input_size'] = 1280; different.append(x)
    for x in different:
        assert key(x) != expected, 'Changed contract retained old key'

    # Schema cannot prove spatial ordering; explicitly check fixture geometry and label association.
    for f in [ocr, face, seg]:
        data = f['data']
        items = data.get('items', data.get('faces', data.get('native_masks', [])))
        views = {v['id'] for v in f['views']}
        for item in items:
            x0,y0,x1,y1 = item['bbox_norm']
            assert x0 < x1 and y0 < y1
            assert item['view_id'] in views
            if 'label' in item:
                assert data['label_names'][item['prompt_index']] == item['label']
    cpu = load('preprocessing/configs/cpu_probe.json')
    gpu = load('preprocessing/configs/gpu_full.json')
    assert cpu['max_active_workers'] == 1 and cpu['batch_size'] == 1
    assert cpu['cpu_threads'] == 2 and cpu['keep_worker_alive'] is False
    assert cpu['tools']['T3_DEPTH']['encoder'] == 'vits'
    assert gpu['tools']['T3_DEPTH']['encoder'] == 'vitb'
    assert cpu['tools']['T4_SEGMENTATION']['model'] != gpu['tools']['T4_SEGMENTATION']['model']
    assert cpu['formal_eligible'] is False and gpu['formal_eligible'] is True
    registry_example = load('preprocessing/configs/model_registry.example.json')
    assert all(t['ready'] is False for t in registry_example['tools'].values())
    print(json.dumps({'status':'PASS','checks':{
        'local_invalid_fixture_rejections':len(bad),
        'cache_key_binding_checks':4,
        'cache_invalidation_checks':len(different),
        'synthetic_geometry_and_label_checks':3,
        'cpu_gpu_profile_and_registry_checks':'PASS'},
        'not_tested':['model deployment','real inference','hardware resource budgets',
                      'Worker/Scheduler implementation','Windows install','GPU migration']},
        ensure_ascii=False,indent=2))

if __name__ == '__main__':
    main()
