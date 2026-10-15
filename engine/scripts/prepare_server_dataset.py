"""Freeze only indexed LQ inputs for an explicit GPU transfer. No GT input."""
import argparse
import csv
import json
from pathlib import Path
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'engine/src'))
from hir_manual.cases import create_case
from hir_manual.storage import CasePaths, read_json, write_json, sha256_file, now
from hir_manual.tool_registry import CANONICALIZER_VERSION

PILOT = ['HC_RAIM_Phase1_011', 'commons_002', 'lolv2_00690', 'HC_ReWiTe_260_tele', 'spaq_00002']


def prepare(root, out):
    root, out = Path(root).resolve(), Path(out).resolve()
    data = root/'Data'
    rows = list(csv.DictReader((data/'filelists/sample_index.csv').open(encoding='utf-8-sig', newline='')))
    approved = {Path(x.strip()).resolve() for x in (data/'filelists/file_list_all.txt').read_text(encoding='utf-8-sig').splitlines() if x.strip()}
    if len(rows) != len(approved) or len({r['sample_id'] for r in rows}) != len(rows):
        raise ValueError('LQ index/list disagree or contain duplicate image IDs')
    out.mkdir(parents=True, exist_ok=True)
    path = out/'manifest.json'
    previous = read_json(path) if path.is_file() else {'images': [], 'rejected': []}
    if previous.get('canonicalizer_version', CANONICALIZER_VERSION) != CANONICALIZER_VERSION:
        raise ValueError('Existing dataset has different canonicalizer; use a new output')
    lookup = {r['image_id']: r for r in previous['images']}
    manifest = {'protocol_version':'1.1', 'dataset_kind':'original_lq_only', 'prepared_at':now(),
                'canonicalizer_version':CANONICALIZER_VERSION, 'source_count':len(rows), 'images':[], 'rejected':[],
                'pilot_ids':PILOT, 'source_manifest_sha256':sha256_file(data/'filelists/sample_index.csv'),
                'filelist_sha256':sha256_file(data/'filelists/file_list_all.txt')}
    for index, row in enumerate(rows, 1):
        original = (data/row['input_path']).resolve()
        if original not in approved or not original.is_relative_to(data) or not original.is_file():
            raise ValueError('Unapproved/missing input: '+row['sample_id'])
        digest = sha256_file(original)
        if digest != row['input_sha256']:
            raise ValueError('Original SHA changed: '+row['sample_id'])
        old = lookup.get(row['sample_id'])
        if old and old['original_sha256'] == digest and sha256_file(out/old['canonical_path']) == old['canonical_sha256'] and sha256_file(out/old['original_path']) == digest:
            record = old
        else:
            try:
                state = create_case(out/'source_store', original, 'Offline GPU source preparation; no restoration output',
                                    {'auto_local_tools':False, 'evidence_profile_id':'gpu_full_v1', 'branch_type':'offline_source_preparation'})
            except ValueError as error:
                manifest['rejected'].append({'image_id':row['sample_id'], 'original_sha256':digest,
                                             'source_path':row['input_path'], 'status':'unsupported_input', 'reason':str(error)})
                write_json(path, manifest)
                print(json.dumps({'index':index,'image_id':row['sample_id'],'status':'unsupported_input','reason':str(error)}),flush=True)
                continue
            case = CasePaths(state.case_id, out/'source_store')
            meta = read_json(case.path('input/metadata.json'))
            record = {'image_id':row['sample_id'], 'sample_id':row['sample_id'],
                      'canonical_path':case.path('input/canonical.png').relative_to(out).as_posix(),
                      'original_path':case.path(meta['original_path']).relative_to(out).as_posix(),
                      'metadata_path':case.path('input/metadata.json').relative_to(out).as_posix(),
                      'source_path':row['input_path'], 'original_sha256':digest,
                      'canonical_sha256':meta['canonical_sha256'], 'canonicalizer_version':meta['canonicalizer_version'],
                      'width':meta['width'], 'height':meta['height'], 'operations':meta['operations'],
                      'input_path':case.path('input/canonical.png').relative_to(out).as_posix()}
        manifest['images'].append(record)
        write_json(path, manifest)
        print(json.dumps({'index':index,'image_id':record['image_id'],'status':'prepared','size':[record['width'],record['height']]}),flush=True)
    manifest['prepared_count'] = len(manifest['images'])
    manifest['complete_source_accounting'] = len(manifest['images'])+len(manifest['rejected']) == len(rows)
    if not set(PILOT) <= {r['image_id'] for r in manifest['images']}:
        raise ValueError('Pilot is incomplete; no inference export permitted')
    write_json(path, manifest)
    return manifest


def package(out):
    out = Path(out).resolve()
    manifest = read_json(out/'manifest.json')
    target = out.parent/(out.name+'.tar')
    temp = target.with_suffix('.tar.tmp')
    # PNG/JPEG are already compressed. A plain tar avoids costly CPU recompression.
    with tarfile.open(temp, 'w') as archive:
        archive.add(out/'manifest.json', arcname='dataset/manifest.json')
        for row in manifest['images']:
            for key in ('canonical_path', 'original_path', 'metadata_path'):
                file = (out/row[key]).resolve()
                if not file.is_relative_to(out):
                    raise ValueError('Unsafe prepared path')
                archive.add(file, arcname='dataset/'+row[key])
    temp.replace(target)
    write_json(target.with_suffix('.receipt.json'), {'path':str(target),'sha256':sha256_file(target),'bytes':target.stat().st_size,'prepared_images':len(manifest['images'])})
    return target


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=ROOT)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--package', action='store_true')
    args = p.parse_args()
    result = prepare(args.root, args.out)
    print(json.dumps({'source_count':result['source_count'], 'prepared_count':len(result['images']), 'rejected':result['rejected']},ensure_ascii=False))
    if args.package:
        print(package(args.out))
