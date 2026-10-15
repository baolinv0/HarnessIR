"""Freeze GPU contracts locally using received deployment metadata, not results."""
import argparse
import json
import shutil
import sys
import uuid
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'engine/src'))
from hir_manual.storage import read_json,write_json,sha256_file
from hir_manual.tool_registry import load_profile,make_contract,TOOL_IDS,bundle_hash,GPU_PROFILE_IDS,PROFILE_FILES
from hir_manual.cache import make_cache_key


def freeze(root,dataset,registry_path,profile_path):
    root,dataset=Path(root).resolve(),Path(dataset).resolve()
    registry=read_json(registry_path)
    profile=read_json(profile_path)
    if registry.get('automatic_download') is not False or profile.get('evidence_profile_id') not in GPU_PROFILE_IDS:
        raise ValueError('Expected actual frozen offline GPU registry/profile')
    from hir_manual.tool_models import EvidenceProfile
    frozen=EvidenceProfile.model_validate(profile)
    # load_profile normally expands the fixed prompt_set from its official file.
    ref=load_profile(frozen.evidence_profile_id,root)
    for tool,parameters in frozen.tools.items():
        if parameters.get('prompt_set_id'):
            parameters['prompt_set']=ref.tools[tool]['prompt_set']
    manifest=read_json(dataset/'manifest.json')
    bundle_id='export_'+uuid.uuid4().hex
    ledger=root/'runtime/offline_exports'/bundle_id
    ledger.mkdir(parents=True,exist_ok=False)
    index={'protocol_version':'1.1','bundle_kind':'missing_jobs','bundle_id':bundle_id,
           'profile':frozen.model_dump(),'entries':[],'unresolved':[], 'manifest_images':len(manifest['images']),
           'source_dataset_manifest_sha256':sha256_file(dataset/'manifest.json'),
           'frozen_registry_sha256':sha256_file(registry_path),'frozen_profile_sha256':sha256_file(profile_path)}
    for row in manifest['images']:
        source=dataset/row['canonical_path']
        original=dataset/row['original_path']
        if sha256_file(source)!=row['canonical_sha256'] or sha256_file(original)!=row['original_sha256']:
            raise ValueError('Prepared source changed')
        relative='inputs/'+row['canonical_sha256']+'.png'
        destination=ledger/relative
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,destination)
        for tool in TOOL_IDS:
            try:
                entry=registry['tools'][tool]
                if bundle_hash(entry['components']) != entry['model_bundle_sha256']:
                    raise ValueError('Actual component bundle metadata mismatch')
                if not entry['backend']['device'].startswith('cuda'):
                    raise ValueError('GPU backend required, no CPU reuse')
                contract=make_contract(row['canonical_sha256'],tool,frozen,entry,canonicalizer_version=row['canonicalizer_version'])
            except (ValueError,KeyError,TypeError) as error:
                index['unresolved'].append({'image_id':row['image_id'],'tool_id':tool,'reason':str(error)})
                continue
            index['entries'].append({'image_id':row['image_id'],'tool_id':tool,'cache_key':make_cache_key(contract),
                                     'contract':contract,'input_path':relative,'canonical_sha256':row['canonical_sha256'],'original_sha256':row['original_sha256']})
    write_json(ledger/'expected.json',index)
    write_json(ledger/'bundle.json',index)
    # These are execution metadata, not executable local SDK installations.
    write_json(root/'preprocessing/registry'/f'{frozen.evidence_profile_id}.json',registry)
    write_json(root/'preprocessing/configs'/PROFILE_FILES[frozen.evidence_profile_id],profile)
    binding_name = 'export_binding.json' if frozen.evidence_profile_id == 'gpu_full_v1' else f'export_binding_{frozen.evidence_profile_id}.json'
    write_json(root/'runtime/offline_monitor'/binding_name,{'bundle_id':bundle_id,'ledger':str(ledger/'expected.json'),
                'entries':len(index['entries']),'unresolved':len(index['unresolved']),'registry_metadata_only':True})
    return index


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=ROOT);p.add_argument('--dataset',type=Path,required=True)
    p.add_argument('--registry',type=Path,required=True);p.add_argument('--profile',type=Path,required=True)
    a=p.parse_args();v=freeze(a.root,a.dataset,a.registry,a.profile)
    print(json.dumps({'bundle_id':v['bundle_id'],'entries':len(v['entries']),'unresolved':len(v['unresolved'])}))
