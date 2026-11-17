from collections import defaultdict
from copy import deepcopy
from hashlib import sha256
import json
import random

from .contracts import digest, require, seal


def preregister(dataset: dict, protocol: dict, split: str) -> dict:
    require(split in {'pilot', 'held_out'}, 'split_invalid', 'Use pilot or held_out')
    cases = deepcopy(dataset.get('cases', []))
    require(isinstance(cases, list), 'dataset_invalid', 'cases must be a list')
    ids = [c.get('case_id') for c in cases]
    require(all(isinstance(x, str) and x for x in ids) and len(set(ids)) == len(ids), 'dataset_invalid', 'Unique case IDs required')
    scenes = {}
    for case in cases:
        require(isinstance(case.get('scene_id'), str) and case['scene_id'], 'scene_id_missing', 'Scene source identity required')
        old = scenes.setdefault(case['scene_id'], case.get('split'))
        require(old == case.get('split'), 'scene_split_leak', 'A scene cannot cross data splits')
        require(not case.get('e1_output_refs') and not case.get('judge_output') and not case.get('oracle_labels'), 'preregistration_late', 'Register from LQ metadata before E1 outputs')
    e2 = protocol.get('e2', {})
    seeds = e2.get('evaluation_seeds', [])
    require(len(seeds) == 2 and len(set(seeds)) == 2 and all(type(s) is int and 0 <= s < 2**63 for s in seeds), 'evaluation_seed_invalid', 'Two distinct nonnegative evaluation seeds required')
    require(not set(seeds) & set(protocol.get('e1', {}).get('seed_schedule', [])), 'evaluation_seed_overlap', 'E1 and E2 seeds must differ')
    sampling_seed = e2.get('sampling_seed', 20261117)
    require(type(sampling_seed) is int, 'sampling_seed_invalid', 'Integer sampling seed required')
    quotas = e2.get(split, {}).get('scene_quotas', {})
    require(isinstance(quotas, dict) and all(type(n) is int and n >= 0 for n in quotas.values()), 'quota_invalid', 'Nonnegative class quotas required')
    selected, strata_record, shortfalls = [], [], {}
    for scene_class, quota in sorted(quotas.items()):
        strata = defaultdict(list)
        for case in cases:
            if case.get('split') != split or case.get('scene_class') != scene_class:
                continue
            label = json.dumps({'information': case.get('information_levels', case.get('information_level', 'not_applicable')), 'size': case.get('roi_size_bins', case.get('size_bin', 'not_applicable'))}, sort_keys=True, separators=(',', ':'))
            strata[label].append(case)
        labels = sorted(strata)
        class_seed = int(sha256(f'{sampling_seed}\n{scene_class}'.encode()).hexdigest(), 16)
        random.Random(class_seed).shuffle(labels)
        for label in labels:
            strata[label].sort(key=lambda c: (sha256(f'{sampling_seed}\n{c["case_id"]}'.encode()).hexdigest(), c['case_id'].encode()))
            strata_record.append({'scene_class': scene_class, 'label': label, 'ordered_case_ids': [c['case_id'] for c in strata[label]]})
        class_selected = []
        while len(class_selected) < quota:
            progressed = False
            for label in labels:
                if strata[label] and len(class_selected) < quota:
                    class_selected.append(strata[label].pop(0))
                    progressed = True
            if not progressed:
                break
        selected.extend(class_selected)
        if len(class_selected) < quota:
            shortfalls[scene_class] = quota - len(class_selected)
    return seal({'schema_version': 'hre_candidates_v1', 'record_type': 'e2_preregistration', 'split': split,
                 'dataset_sha256': digest(dataset), 'protocol_sha256': digest(protocol), 'sampling_seed': sampling_seed,
                 'evaluation_seeds': seeds, 'case_ids': [c['case_id'] for c in selected], 'cases': selected,
                 'strata': strata_record, 'shortfalls': shortfalls, 'selection_algorithm': 'seeded_strata_round_robin_sha256_v1',
                 'slot_metric_rule': 'separate_slot_axis_effective_strategy_no_posthoc_best', 'max_image_calls': 8 * len(selected)})
