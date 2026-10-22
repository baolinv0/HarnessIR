"""Native condition handoff inside the existing Controller journal.

Compilation is an explicit pause, not another workflow or a model API call.
"""
from copy import deepcopy
from pathlib import Path
import json
import shutil
from .models import file_sha256, sha256_bytes
from .storage import CaseStore, read_json, write_json
from .paths import safe_path
from .masks import require
from .evidence import _immutable


def _source(root, state, accepted=None):
    from .workflow import Controller
    from .prompts import render_stage, template_source
    from .reference_contracts import reference_targets
    config=read_json(root/'config.json');policy=config['reference_v2']['model_aware']
    controller=Controller(root)
    if state['profile_id']=='direct_ref':
        source=f"direct_prompt_{state['case_id']}_rev_{state['case_revision']}"
        bindings=[dict(label=label,asset_id=a['asset_id'],canonical_sha256=a['sha256']) for label,a in zip(['A','B'],state['inputs'])]
        rendered=render_stage('direct_ref',dict(image_bindings=bindings),case_root=root)
        brief=json.loads(rendered)['edit_prompt'];intent=None
        proof=dict(task_id=source,edit_prompt=brief,prompt_version='direct_ref_v1',
                   prompt_sha256=sha256_bytes(brief.encode()),config_sha256=state['config_sha256'],
                   template_source=template_source(root,'direct_ref'),rendered_prompt_sha256=sha256_bytes(rendered.encode()))
        source_proof=dict(kind='direct',manifest=proof)
    else:
        entry=accepted or controller._latest('compose')
        source=entry['task_id'];composition=entry['response']['payload'];brief=composition['edit_prompt']
        intent=reference_targets(root,controller._latest('diagnose')['response']['payload'],composition,state['inputs'])
        intent['protected_content']=deepcopy(composition['protected_content'])
        intent['reference_limitations']=deepcopy(composition['reference_limitations'])
        intent['roi_pairs']=deepcopy(config['reference_v2']['roi_pairs'])
        intent['region_relations']=deepcopy(composition.get('region_relations',[]))
        intent['region_relations_status']='annotated' if intent['region_relations'] else 'not_annotated'
        from .reference_evaluator import region_mask,display_attributes,_rgb8
        a,b=(_rgb8(asset,root) for asset in state['inputs']);statistics=[]
        for pair in intent['roi_pairs']:
            ma=region_mask(a.shape,pair['prediction'],root);mb=region_mask(b.shape,pair['reference'],root)
            valid=pair['comparability']=='comparable' and ma.any() and mb.any()
            statistics.append(dict(roi_pair_id=pair['roi_pair_id'],status='measured' if valid else 'not_assessable',
                                   A=display_attributes(a[ma]) if valid else None,B=display_attributes(b[mb]) if valid else None))
        intent['reference_statistics']=statistics
        source_proof=dict(kind='compose',task_id=source,response_sha256=entry['response_sha256'],
                          response_path=entry['response_path'])
    if policy['strategy']=='native':intent=None
    return source,brief,intent,source_proof


def _expected(root,state,accepted=None):
    from .model_aware import build_condition_request
    config=read_json(root/'config.json')
    require('model_aware' in config.get('reference_v2',{}),'condition_not_enabled','This case has no frozen model-aware configuration')
    source,brief,intent,source_proof=_source(root,state,accepted)
    request=build_condition_request(config['reference_v2']['model_aware'],brief=brief,intent=intent,
                                    input_assets=state['inputs'],case_id=state['case_id'],source_id=source)
    binding=dict(case_id=state['case_id'],case_revision=state['case_revision'],config_sha256=state['config_sha256'],
                 source_id=source,source_proof=source_proof,request=request)
    return 'compiled_'+source,binding


def prepare_condition_request(root,state,accepted=None):
    root=Path(root);source,binding=_expected(root,state,accepted)
    directory=safe_path(root,'tasks/'+source)
    _immutable(directory/'source.json',binding)
    return binding['request']


def _frozen_request(root,state):
    source,expected=_expected(root,state)
    path=safe_path(root,f'tasks/{source}/source.json',must_exist=True)
    binding=read_json(path)
    require(binding==expected,'condition_source_mismatch','Compiler source differs from the accepted brief, inputs or configuration')
    return source,binding


def export_condition_request(root,out):
    root=Path(root);state=CaseStore(root).load()
    require(state['workflow_state']=='PAUSED' and state['pause_reason']=='condition_compilation_required'
            and state['pending_task'] is None,'condition_not_waiting','Case is not waiting for condition compilation')
    source,binding=_frozen_request(root,state);out=Path(out)
    require(not out.exists(),'export_exists','Choose a new compiler export directory')
    out.mkdir(parents=True)
    write_json(out/'condition_request.json',binding['request'])
    write_json(out/'source_binding.json',binding)
    for label,asset in zip(['A','B'],state['inputs']):
        shutil.copyfile(safe_path(root,asset['path'],must_exist=True),out/(label+'.png'))
    return out


def freeze_compiled_condition(root,state,result):
    from .model_aware import validate_compiled_condition
    root=Path(root);source,binding=_frozen_request(root,state)
    validated=validate_compiled_condition(binding['request'],result)
    manifest=dict(schema_version='compiled_condition_source_v1',binding=binding,result=validated)
    _immutable(safe_path(root,f'tasks/{source}/manifest.json'),manifest)
    return source,validated


def compiled_condition(root,request):
    """Revalidate the native payload against its accepted source at every handoff."""
    from .model_aware import validate_compiled_condition
    root=Path(root);state=CaseStore(root).load();source,binding=_frozen_request(root,state)
    require(request['payload']['prompt_source_task_id']==source,'condition_source_mismatch','Execute references another compiled source')
    path=safe_path(root,f'tasks/{source}/manifest.json',must_exist=True);manifest=read_json(path)
    require(manifest.get('schema_version')=='compiled_condition_source_v1' and manifest.get('binding')==binding,
            'condition_source_mismatch','Compiled source binding changed')
    result=validate_compiled_condition(binding['request'],manifest['result'])
    require(result['edit_prompt']==request['payload']['edit_prompt'],'condition_source_mismatch','Execute changed the accepted native condition')
    return result
