import pytest
import copy
from hre.evidence import EvidenceService,make_cache_key,register_cache_bundle
from test_hre_stats import asset


def state(tmp_path):
    a=asset(tmp_path,'A'); b=asset(tmp_path,'B'); b['role']='reference'
    return dict(case_id='case1',case_revision=0,config_sha256='c'*64,profile_id='direct_ref',inputs=[a,b],evidence_plan=[])


def test_empty_direct_snapshot_and_required_wait(tmp_path):
    s=state(tmp_path); out=EvidenceService(tmp_path).resolve(s)
    assert out['snapshot']['diagnosis_task_id'] is None and out['snapshot']['evidence']==[]
    s['evidence_plan']=[dict(plan_item_id='ocr',tool_id='T1_OCR',roles=['prediction'],roi_pair_ids=[],required=True,status='pending',evidence_id=None)]
    r=EvidenceService(tmp_path).resolve(s); assert r['snapshot'] is None and r['missing']==['ocr']
    s['evidence_plan'][0]['required']=False
    r=EvidenceService(tmp_path).resolve(s); assert r['snapshot']['unavailable'][0]['status']=='unavailable'


def test_only_planned_and_cache_cross_case(tmp_path):
    one=tmp_path/'one';one.mkdir(); s=state(one)
    s['evidence_plan']=[dict(plan_item_id='stats',tool_id='STATS',roles=['prediction'],roi_pair_ids=[],required=True,status='pending',evidence_id=None)]
    svc=EvidenceService(one); r=svc.resolve(s)
    bundle=tmp_path/'bundle'; svc.export_bundle(r['snapshot'],bundle)
    cache=tmp_path/'cache';register_cache_bundle(bundle,cache)
    two=tmp_path/'two';two.mkdir(); t=state(two);t['case_id']='case2';t['inputs'][0]['asset_id']='different';t['evidence_plan']=copy.deepcopy(s['evidence_plan']);t['evidence_plan'][0]['plan_item_id']='next'
    other=EvidenceService(two,cache).resolve(t)
    from hre.storage import read_json
    rec=read_json(two/other['snapshot']['evidence'][0]['path'])
    assert rec['case_id']=='case2' and rec['binding']['inputs'][0]['asset_id']=='different'
    assert rec['payload']['regions'][0]['source_asset_id']=='different'
    assert len(other['snapshot']['evidence'])==1
    assert other['snapshot']['evidence'][0]['sha256']!=r['snapshot']['evidence'][0]['sha256']
    contract=rec['cache_contract'];new=copy.deepcopy(contract);new['model']['weights_sha256']='1'*64
    assert make_cache_key(contract)!=make_cache_key(new)


def test_frozen_records_and_snapshot_reject_changes(tmp_path):
    import pytest
    from hre.storage import read_json,write_json
    s=state(tmp_path);s['evidence_plan']=[dict(plan_item_id='s',tool_id='STATS',roles=['prediction'],roi_pair_ids=[],required=True,status='pending',evidence_id=None)]
    svc=EvidenceService(tmp_path);r=svc.resolve(s)
    s['evidence_plan']=r['plan'];s['evidence_snapshot']=r['snapshot_ref']
    p=tmp_path/r['snapshot']['evidence'][0]['path'];record=read_json(p)
    record['payload']['regions'][0]['metrics']['mean_luma']=.123;write_json(p,record)
    with pytest.raises(Exception,match='frozen evidence'):svc.resolve(s)


def test_cache_contract_varies_on_roles_parameters_and_profiles(tmp_path):
    s=state(tmp_path);svc=EvidenceService(tmp_path)
    item=dict(plan_item_id='s',tool_id='STATS',roles=['prediction'],roi_pair_ids=[],required=True,status='pending',evidence_id=None)
    a=svc._contract(s,item,[s['inputs'][0]])
    for path,value in [('tool_version','other'),('canonicalizer_version','other'),('preprocess_sha256','f'*64),('roi_manifest_sha256','a'*64),('prompt_set_sha256','b'*64)]:
        b=copy.deepcopy(a);b[path]=value;assert make_cache_key(a)!=make_cache_key(b)
    for field,value in [('profile_id','other'),('device','gpu'),('precision','float32'),('environment_sha256','e'*64)]:
        b=copy.deepcopy(a);b['backend'][field]=value;assert make_cache_key(a)!=make_cache_key(b)
    b=copy.deepcopy(a);b['inputs'][0]['role']='reference';assert make_cache_key(a)!=make_cache_key(b)
    b=copy.deepcopy(a);b['parameters']['threshold']=.7;assert make_cache_key(a)!=make_cache_key(b)


def test_agent_diagnosis_binding_and_direct_null(tmp_path):
    import pytest
    s=state(tmp_path);s['profile_id']='agent_single'
    with pytest.raises(Exception,match='diagnosis'):EvidenceService(tmp_path).resolve(s)
    s['diagnosis_task_id']='diagnosed';s['pending_task']={'stage':'diagnose','task_id':'wrong'}
    with pytest.raises(Exception,match='diagnosis'):EvidenceService(tmp_path).resolve(s)
    s['profile_id']='direct_ref';assert EvidenceService(tmp_path).resolve(s)['snapshot']['diagnosis_task_id'] is None
    # Real protocol artifacts are required even for a transaction-local diagnosis.
    from test_hre_protocol import make_case,diagnosis,current_request
    from hre.protocol import TaskWriter
    from hre.workflow import Controller
    from hre.storage import read_json
    from hre.models import file_sha256
    (tmp_path/'real').mkdir()
    root=make_case(tmp_path/'real','agent_single',1);controller=Controller(root);controller.start();request=current_request(root)
    done=TaskWriter(root).commit_submission(request,diagnosis());manifest=read_json(done)
    view=controller.state()|dict(diagnosis_task_id=request['task_id'],_accepted_diagnosis=dict(task_id=request['task_id'],response_path=manifest['response_file'],response_sha256=manifest['response_sha256']))
    result=EvidenceService(root).resolve(view);assert result['snapshot']['diagnosis_task_id']==request['task_id']



def offline_bundle(root,tool,*,array=None):
    from hre.storage import write_json
    from hre.models import file_sha256,now
    from hre.evidence import validate_record
    import numpy as np
    root.mkdir();s=state(root)
    # Explicitly synthetic, hash-bound recorded worker provenance; no inference is claimed.
    write_json(root/'config.json',dict(tool_profile={tool:dict(tool_version='synthetic_fixture_v1',preprocess_version='synthetic_fixture_v1',model=dict(name='synthetic_recorded_fixture',revision='fixture_v1',weights_sha256=__import__('hashlib').sha256(b'synthetic fixture bytes; not real model weights').hexdigest(),components=[]),preprocess={'mode':'identity_synthetic_fixture'},backend=dict(implementation='synthetic_fixture',version='fixture_v1',device='cpu',precision='float32',profile_id='direct_ref',environment_sha256=__import__('hashlib').sha256(b'synthetic test environment').hexdigest()))}))
    svc=EvidenceService(root)
    item=dict(plan_item_id='offline',tool_id=tool,roles=['prediction'],roi_pair_ids=[],required=True,status='pending',evidence_id=None)
    contract=svc._contract(s,item,[s['inputs'][0]])
    payload=dict(coordinate_frames=[dict(asset_id='A',space='canonical_norm',source_to_tool=[[1,0,0],[0,1,0],[0,0,1]])],detections=[],data={})
    artifacts=[]
    if tool in ('T3_DEPTH','T4_SEGMENTATION'):
        p=root/'raw.npy';np.save(p,array,allow_pickle=False)
        artifacts=[dict(asset_id='raw',path=p.name,sha256=file_sha256(p),role='evidence',width=2,height=2,color_space=None,evidence_format=dict(kind='array',dtype=str(array.dtype),value_range=[float(array.min()),float(array.max())],coordinate_asset_id='A'))]
        payload['data']=dict(depth_asset_id='raw',depth_kind='relative_depth',display_asset_id=None) if tool=='T3_DEPTH' else dict(mask_asset_id='raw',class_registry=[dict(class_id=0,label='background'),dict(class_id=1,label='foreground')],display_asset_id=None)
    record=dict(schema_version='ref_enhance_v1',evidence_id='off',case_id='case1',case_revision=0,tool_id=tool,status='ok',binding=dict(inputs=[{k:s['inputs'][0][k] for k in ('asset_id','role','sha256','width','height')}|dict(candidate_id=None)],plan_item_id='offline',roi_pair_ids=[]),cache_key_sha256=make_cache_key(contract),cache_contract=contract,produced_at=now(),producer='offline',payload=payload,assets=artifacts,error=None)
    validate_record(root,record,s['inputs']);write_json(root/'record.json',record)
    write_json(root/'evidence_bundle.json',dict(schema_version='ref_enhance_v1',inputs=s['inputs'],records=[dict(path='record.json',sha256=file_sha256(root/'record.json'))]))
    return s,item,record


def test_all_four_import_and_depth_cross_case_remapping(tmp_path):
    import numpy as np
    from hre.storage import read_json
    from hre.evidence import validate_record
    for tool in ['T1_OCR','T2_FACE','T3_DEPTH','T4_SEGMENTATION']:
        source=tmp_path/tool
        array=np.array([[0,1],[1,0]],dtype=np.float32 if tool=='T3_DEPTH' else np.uint8)
        s,item,rec=offline_bundle(source,tool,array=array)
        cache=tmp_path/'cache';register_cache_bundle(source,cache)
        dest=tmp_path/(tool+'_new');dest.mkdir();(dest/'config.json').write_bytes((source/'config.json').read_bytes());t=state(dest);t['case_id']='other';t['inputs'][0]['asset_id']='newA';t['evidence_plan']=[item|dict(plan_item_id='newplan')]
        r=EvidenceService(dest,cache).resolve(t);record=read_json(dest/r['snapshot']['evidence'][0]['path'])
        validate_record(dest,record,t['inputs'])
        assert record['payload']['coordinate_frames'][0]['asset_id']=='newA'
        assert record['payload']['detections']==[]
        if tool in ('T3_DEPTH','T4_SEGMENTATION'):
            assert record['assets'][0]['evidence_format']['coordinate_asset_id']=='newA'
            assert record['payload']['data']['depth_asset_id' if tool=='T3_DEPTH' else 'mask_asset_id']==record['assets'][0]['asset_id']
        # Unplanned T records remain absent when the plan is empty.
        t['evidence_plan']=[];assert EvidenceService(dest,cache).resolve(t)['snapshot']['evidence']==[]


def test_bad_arrays_labels_and_bundle_paths_rejected(tmp_path):
    import pytest
    import numpy as np
    from hre.evidence import validate_record
    from hre.storage import write_json
    s,item,rec=offline_bundle(tmp_path/'bundle','T4_SEGMENTATION',array=np.array([[0,1],[1,0]],dtype=np.uint8))
    rec['payload']['data']['class_registry']=[dict(class_id=0,label='onlyzero')]
    with pytest.raises(Exception,match='labels'):validate_record(tmp_path/'bundle',rec,s['inputs'])
    manifest=dict(schema_version='ref_enhance_v1',inputs=s['inputs'],records=[dict(path='../outside',sha256='a'*64)])
    write_json(tmp_path/'bundle'/'evidence_bundle.json',manifest)
    with pytest.raises(Exception):register_cache_bundle(tmp_path/'bundle',tmp_path/'cache')
    manifest['records'][0]['path']='link.json';(tmp_path/'bundle'/'link.json').symlink_to(tmp_path/'bundle'/'record.json');write_json(tmp_path/'bundle'/'evidence_bundle.json',manifest)
    with pytest.raises(Exception,match='Symlink'):register_cache_bundle(tmp_path/'bundle',tmp_path/'cache')


def test_builtin_roi_stats_and_export_jobs(tmp_path):
    from hre.storage import write_json,read_json
    s=state(tmp_path)
    pair=dict(roi_pair_id='left',prediction=[0,0,.5,1],reference=[.5,0,1,1],coordinate_system='canonical_norm',comparability='comparable',reason='same material')
    write_json(tmp_path/'config.json',dict(roi_manifest=[pair],tool_profile={}))
    s['evidence_plan']=[dict(plan_item_id='s',tool_id='STATS',roles=['prediction','reference'],roi_pair_ids=['left'],required=True,status='pending',evidence_id=None)]
    svc=EvidenceService(tmp_path);jobs=svc.export_missing_jobs(s,tmp_path/'jobs');exported=read_json(jobs)
    r=svc.resolve(s);rec=read_json(tmp_path/r['snapshot']['evidence'][0]['path'])
    assert [x['sample_count'] for x in rec['payload']['regions']]==[2,2]
    assert len(rec['assets'])==2
    assert exported['jobs'][0]['cache_key_sha256']==rec['cache_key_sha256']
    assert read_json(svc.export_missing_jobs(s,tmp_path/'complete_jobs'))['jobs']==[]
    before=copy.deepcopy(s);bundle=svc.precompute_bundle(s,s['evidence_plan'],tmp_path/'export');assert s==before
    assert register_cache_bundle(bundle,tmp_path/'cache')['count']==1


def test_cache_integrity_and_role_miss(tmp_path):
    import pytest
    from hre.storage import read_json,write_json
    s,item,rec=offline_bundle(tmp_path/'source','T1_OCR')
    cache=tmp_path/'cache';register_cache_bundle(tmp_path/'source',cache)
    target=tmp_path/'target';target.mkdir();(target/'config.json').write_bytes((tmp_path/'source'/'config.json').read_bytes());t=state(target);t['evidence_plan']=[item|dict(roles=['reference'])]
    assert EvidenceService(target,cache).resolve(t)['missing']==['offline']
    t['evidence_plan']=[item]
    entry=cache/rec['cache_key_sha256']/'record.json';record=read_json(entry);record['payload']['data']['modified']=True;write_json(entry,record)
    with pytest.raises(Exception,match='cache record'):EvidenceService(target,cache).resolve(t)


def test_unknown_model_rejected_and_manual_annotation_hash_bound(tmp_path):
    import pytest
    from hre.evidence import validate_record
    from hre.models import canonical_json,sha256_bytes
    s,item,rec=offline_bundle(tmp_path/'worker','T1_OCR')
    original=copy.deepcopy(rec)
    rec['cache_contract']['model']['revision']='unknown';rec['cache_key_sha256']=make_cache_key(rec['cache_contract'])
    with pytest.raises(Exception,match='provenance'):validate_record(tmp_path/'worker',rec,s['inputs'])
    rec=copy.deepcopy(original);c=rec['cache_contract'];c['model'].update(name='manual_annotation',revision='annotations_v1',weights_sha256=None)
    c['backend']['implementation']='manual_annotation';c['parameters']={'annotation_sha256':__import__('hre.evidence',fromlist=['annotation_hash']).annotation_hash(rec['payload'],rec['binding']['inputs'],rec['assets']),'annotation_version':'annotations_v1'}
    rec['cache_key_sha256']=make_cache_key(c);validate_record(tmp_path/'worker',rec,s['inputs'])
    c['parameters']['annotation_sha256']='0'*64;rec['cache_key_sha256']=make_cache_key(c)
    with pytest.raises(Exception,match='annotation'):validate_record(tmp_path/'worker',rec,s['inputs'])


def test_candidate_cache_binds_new_candidate_and_role_isolation(tmp_path):
    from hre.storage import read_json
    one=tmp_path/'one';one.mkdir();s=state(one)
    c=asset(one,'C');c['role']='candidate';c['candidate_binding']=dict(case_id=s['case_id'],case_revision=0,task_id='edit1',round=0,generation_id='gen1',prediction_sha256=s['inputs'][0]['sha256'],reference_sha256=s['inputs'][1]['sha256'])
    s.update(candidate_id='candidate1',candidate_asset=c,evidence_scope='verification')
    item=dict(plan_item_id='candidate_stats',tool_id='STATS',roles=['candidate'],roi_pair_ids=[],required=True,status='pending',evidence_id=None)
    s['evidence_plan']=[item];svc=EvidenceService(one);result=svc.resolve(s);assert result['snapshot']['candidate_id']=='candidate1'
    bundle=svc.export_bundle(result['snapshot'],tmp_path/'bundle');cache=tmp_path/'cache';register_cache_bundle(bundle,cache)
    two=tmp_path/'two';two.mkdir();t=state(two);t['case_id']='newcase';d=asset(two,'newC');d['role']='candidate';d['candidate_binding']=c['candidate_binding']|dict(case_id='newcase',task_id='edit2',generation_id='gen2')
    t.update(candidate_id='candidate2',candidate_asset=d,evidence_scope='verification',evidence_plan=[item|dict(plan_item_id='other')])
    r=EvidenceService(two,cache).resolve(t);record=read_json(two/r['snapshot']['evidence'][0]['path'])
    assert record['binding']['inputs'][0]['candidate_id']=='candidate2' and record['binding']['inputs'][0]['asset_id']=='newC'
    assert record['payload']['regions'][0]['source_asset_id']=='newC'
    assert r['snapshot']['candidate_id']=='candidate2'


@pytest.mark.parametrize('tool',['T3_DEPTH','T4_SEGMENTATION'])
def test_review_raw_arrays_require_source_and_native_geometry(tmp_path,tool):
    import numpy as np
    from hre.evidence import validate_record
    from hre.models import file_sha256
    s,item,record=offline_bundle(tmp_path/'worker',tool,array=np.zeros((2,2),dtype=np.float32 if tool=='T3_DEPTH' else np.uint8))
    record['assets'][0]['evidence_format']['coordinate_asset_id']=None
    with pytest.raises(Exception,match='coordinate'):validate_record(tmp_path/'worker',record,s['inputs'])
    record['assets'][0]['evidence_format']['coordinate_asset_id']='A'
    np.save(tmp_path/'worker'/'raw.npy',np.zeros((1,1),dtype=np.float32 if tool=='T3_DEPTH' else np.uint8),allow_pickle=False)
    record['assets'][0].update(width=1,height=1,sha256=file_sha256(tmp_path/'worker'/'raw.npy'))
    with pytest.raises(Exception,match='geometry'):validate_record(tmp_path/'worker',record,s['inputs'])


def test_review_cache_commit_crash_not_visible(tmp_path,monkeypatch):
    from hre import storage
    s,item,record=offline_bundle(tmp_path/'worker','T1_OCR');cache=tmp_path/'cache'
    original=storage.atomic_write
    def crash(path,data):
        if path.name=='inputs.json':raise OSError('simulated cache crash')
        return original(path,data)
    monkeypatch.setattr(storage,'atomic_write',crash)
    with pytest.raises(OSError):register_cache_bundle(tmp_path/'worker',cache)
    assert not (cache/record['cache_key_sha256']).exists()
    monkeypatch.setattr(storage,'atomic_write',original)
    assert register_cache_bundle(tmp_path/'worker',cache)['count']==1


def test_review_unavailable_never_poison_cache_and_later_success_preserves_old_snapshot(tmp_path):
    from hre.storage import read_json
    s,item,success=offline_bundle(tmp_path/'worker','T1_OCR');s['evidence_plan']=[item|dict(required=False)]
    svc=EvidenceService(tmp_path/'worker');old=svc.resolve(s);old_bytes=(tmp_path/'worker'/old['snapshot_ref']['path']).read_bytes()
    missing_bundle=svc.export_bundle(old['snapshot'],tmp_path/'missing');cache=tmp_path/'cache'
    assert register_cache_bundle(missing_bundle,cache)['count']==0
    assert register_cache_bundle(tmp_path/'worker',cache)['count']==1
    later=EvidenceService(tmp_path/'worker',cache).resolve(s)
    assert later['plan'][0]['status']=='ok'
    assert (tmp_path/'worker'/old['snapshot_ref']['path']).read_bytes()==old_bytes
    old_record=read_json(tmp_path/'worker'/old['snapshot']['evidence'][0]['path']);assert old_record['status']=='unavailable'


def test_review_historical_mask_mutation_blocks_empty_precompute(tmp_path):
    from hre.storage import write_json,read_json
    s=state(tmp_path);pair=dict(roi_pair_id='all',prediction=[0,0,1,1],reference=[0,0,1,1],coordinate_system='canonical_norm',comparability='comparable',reason='test')
    write_json(tmp_path/'config.json',dict(roi_manifest=[pair],tool_profile={}))
    s['evidence_plan']=[dict(plan_item_id='mask',tool_id='STATS',roles=['prediction'],roi_pair_ids=['all'],required=True,status='pending',evidence_id=None)]
    svc=EvidenceService(tmp_path);result=svc.resolve(s);record=read_json(tmp_path/result['snapshot']['evidence'][0]['path'])
    (tmp_path/record['assets'][0]['path']).write_bytes(b'mutated mask')
    with pytest.raises(Exception):svc.precompute(s|dict(evidence_snapshot=result['snapshot_ref']),[])


def test_review_manual_annotation_cross_case(tmp_path):
    from hre.models import canonical_json,sha256_bytes,file_sha256
    from hre.storage import write_json,read_json
    s,item,record=offline_bundle(tmp_path/'worker','T1_OCR');contract=record['cache_contract']
    contract['model'].update(name='manual_annotation',revision='annotations_v1',weights_sha256=None)
    contract['backend']['implementation']='manual_annotation';contract['parameters']={'annotation_sha256':__import__('hre.evidence',fromlist=['annotation_hash']).annotation_hash(record['payload'],record['binding']['inputs'],record['assets']),'annotation_version':'annotations_v1'}
    record['cache_key_sha256']=make_cache_key(contract)
    write_json(tmp_path/'worker'/'record.json',record)
    manifest=read_json(tmp_path/'worker'/'evidence_bundle.json');manifest['records'][0]['sha256']=file_sha256(tmp_path/'worker'/'record.json');write_json(tmp_path/'worker'/'evidence_bundle.json',manifest)
    cfg=read_json(tmp_path/'worker'/'config.json');profile=cfg['tool_profile']['T1_OCR'];profile.update(model=contract['model'],backend=contract['backend'],parameters=contract['parameters']);write_json(tmp_path/'worker'/'config.json',cfg)
    cache=tmp_path/'cache';register_cache_bundle(tmp_path/'worker',cache)
    target=tmp_path/'target';target.mkdir();t=state(target);t['case_id']='other';t['inputs'][0]['asset_id']='renamedA';t['evidence_plan']=[item];write_json(target/'config.json',cfg)
    result=EvidenceService(target,cache).resolve(t)
    actual=read_json(target/result['snapshot']['evidence'][0]['path']);assert actual['payload']['coordinate_frames'][0]['asset_id']=='renamedA'
    assert actual['cache_key_sha256']==record['cache_key_sha256']


@pytest.mark.parametrize('tool',['T3_DEPTH','T4_SEGMENTATION'])
def test_review_frozen_native_resize_and_visualization_geometry(tmp_path,tool):
    import numpy as np
    from hre.evidence import validate_record
    from hre.models import file_sha256
    s,item,record=offline_bundle(tmp_path/'worker',tool,array=np.zeros((2,2),dtype=np.float32 if tool=='T3_DEPTH' else np.uint8))
    matrix=[[.5,0,0],[0,.5,0],[0,0,1]]
    np.save(tmp_path/'worker'/'raw.npy',np.zeros((1,1),dtype=np.float32 if tool=='T3_DEPTH' else np.uint8),allow_pickle=False)
    record['assets'][0].update(width=1,height=1,sha256=file_sha256(tmp_path/'worker'/'raw.npy'))
    record['payload']['coordinate_frames'][0]['source_to_tool']=matrix
    with pytest.raises(Exception,match='geometry'):validate_record(tmp_path/'worker',record,s['inputs'])
    record['cache_contract']['parameters']['tool_geometry']={'prediction':{'width':1,'height':1,'source_to_tool':matrix}};record['cache_key_sha256']=make_cache_key(record['cache_contract'])
    validate_record(tmp_path/'worker',record,s['inputs'])
    view=asset(tmp_path/'worker','display');view['role']='evidence';view['evidence_format']=dict(kind='visualization',dtype='uint8',value_range=[0,255],coordinate_asset_id='A')
    record['assets'].append(view);record['payload']['data']['display_asset_id']='display'
    with pytest.raises(Exception,match='geometry'):validate_record(tmp_path/'worker',record,s['inputs'])
    record['cache_contract']['parameters']['tool_geometry']['prediction']['source_to_tool']=[[.5,0,.1],[0,.5,0],[0,0,1]]
    record['payload']['coordinate_frames'][0]['source_to_tool']=[[.5,0,.1],[0,.5,0],[0,0,1]];record['cache_key_sha256']=make_cache_key(record['cache_contract']);record['payload']['data']['display_asset_id']=None;record['assets'].pop()
    with pytest.raises(Exception,match='full declared'):validate_record(tmp_path/'worker',record,s['inputs'])


def test_review_reader_sees_miss_until_cache_directory_commit(tmp_path,monkeypatch):
    import threading
    from hre import storage
    s,item,record=offline_bundle(tmp_path/'worker','T1_OCR');cache=tmp_path/'cache'
    target=tmp_path/'target';target.mkdir();t=state(target);t['evidence_plan']=[item];(target/'config.json').write_bytes((tmp_path/'worker'/'config.json').read_bytes())
    staged=threading.Event();resume=threading.Event();errors=[];original=storage.atomic_write
    def blocked(path,data):
        if path.name=='inputs.json':staged.set();assert resume.wait(5)
        return original(path,data)
    monkeypatch.setattr(storage,'atomic_write',blocked)
    def register():
        try:register_cache_bundle(tmp_path/'worker',cache)
        except BaseException as exc:errors.append(exc)
    thread=threading.Thread(target=register);thread.start()
    try:
        assert staged.wait(5)
        assert EvidenceService(target,cache).resolve(t)['missing']==['offline']
    finally:resume.set();thread.join(5)
    assert not thread.is_alive() and not errors
    assert EvidenceService(target,cache).resolve(t)['plan'][0]['status']=='ok'


def test_review_manual_json_metadata_hash_stable_across_cases(tmp_path):
    from hre.models import file_sha256
    from hre.storage import write_json,read_json
    from hre.evidence import annotation_hash
    s,item,record=offline_bundle(tmp_path/'worker','T1_OCR');root=tmp_path/'worker'
    write_json(root/'metadata.json',{'source_asset_id':'A','annotation':'synthetic annotation'})
    record['assets']=[dict(asset_id='metadata',path='metadata.json',sha256=file_sha256(root/'metadata.json'),role='evidence',width=None,height=None,color_space=None,evidence_format=dict(kind='json',dtype='annotation_json',value_range=None,coordinate_asset_id='A'))]
    record['payload']['data']={'metadata_asset_id':'metadata'}
    contract=record['cache_contract'];contract['model'].update(name='manual_annotation',revision='annotation_v1',weights_sha256=None);contract['backend']['implementation']='manual_annotation';contract['parameters']={'annotation_sha256':annotation_hash(record['payload'],record['binding']['inputs'],record['assets'],case_root=root),'annotation_version':'annotation_v1'}
    record['cache_key_sha256']=make_cache_key(contract);write_json(root/'record.json',record)
    manifest=read_json(root/'evidence_bundle.json');manifest['records'][0]['sha256']=file_sha256(root/'record.json');write_json(root/'evidence_bundle.json',manifest)
    cfg=read_json(root/'config.json');cfg['tool_profile']['T1_OCR'].update(model=contract['model'],parameters=contract['parameters'],backend=contract['backend']);write_json(root/'config.json',cfg)
    cache=tmp_path/'cache';register_cache_bundle(root,cache)
    target=tmp_path/'target';target.mkdir();t=state(target);t['inputs'][0]['asset_id']='newA';t['case_id']='newcase';t['evidence_plan']=[item];write_json(target/'config.json',cfg)
    result=EvidenceService(target,cache).resolve(t);actual=read_json(target/result['snapshot']['evidence'][0]['path'])
    assert read_json(target/actual['assets'][0]['path'])['source_asset_id']=='newA'
    assert actual['cache_contract']['parameters']['annotation_sha256']==contract['parameters']['annotation_sha256']


def test_review_bundle_existing_conflicts_preflight_before_any_publication(tmp_path):
    from hre.storage import read_json,write_json
    from hre.models import file_sha256
    one=tmp_path/'one';s,item,first=offline_bundle(one,'T1_OCR')
    two=tmp_path/'two';_,_,second=offline_bundle(two,'T2_FACE')
    cache=tmp_path/'cache';register_cache_bundle(two,cache)
    bundle=tmp_path/'both';bundle.mkdir()
    import shutil
    for p in one.iterdir():
        if p.is_file():shutil.copyfile(p,bundle/p.name)
    second['payload']['data']['different']='conflicting output under identical frozen contract'
    write_json(bundle/'second.json',second)
    manifest=read_json(bundle/'evidence_bundle.json');manifest['records'].append(dict(path='second.json',sha256=file_sha256(bundle/'second.json')));write_json(bundle/'evidence_bundle.json',manifest)
    with pytest.raises(Exception,match='immutable existing'):register_cache_bundle(bundle,cache)
    assert not (cache/first['cache_key_sha256']).exists()
    assert (cache/second['cache_key_sha256']/'entry.json').exists()


def test_review_concurrent_registration_keeps_complete_single_entry(tmp_path):
    import concurrent.futures
    s,item,record=offline_bundle(tmp_path/'worker','T1_OCR');cache=tmp_path/'cache'
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:register_cache_bundle(tmp_path/'worker',cache),range(2)))
    assert all(r['count']==1 for r in results)
    from hre.evidence import _read_cache_entry
    actual,_=_read_cache_entry(cache/record['cache_key_sha256']);assert actual['status']=='ok'


def test_review_wave2_nested_manual_annotation_binds_inner_actual_contents(tmp_path):
    from hre.evidence import annotation_hash,validate_record
    from hre.storage import write_json
    from hre.models import file_sha256
    s,item,record=offline_bundle(tmp_path/'worker','T1_OCR');root=tmp_path/'worker'
    write_json(root/'outer.json',{'nested_asset_id':'inner'});write_json(root/'inner.json',{'annotation':'original'})
    def artifact(name):
        return dict(asset_id=name,path=name+'.json',sha256=file_sha256(root/(name+'.json')),role='evidence',width=None,height=None,color_space=None,evidence_format=dict(kind='json',dtype='annotation_json',value_range=None,coordinate_asset_id='A'))
    record['assets']=[artifact('outer'),artifact('inner')];record['payload']['data']={'metadata_asset_id':'outer'}
    contract=record['cache_contract'];contract['model'].update(name='manual_annotation',revision='annotation_v1',weights_sha256=None);contract['backend']['implementation']='manual_annotation'
    before=annotation_hash(record['payload'],record['binding']['inputs'],record['assets'],case_root=root)
    contract['parameters']={'annotation_version':'annotation_v1','annotation_sha256':before};record['cache_key_sha256']=make_cache_key(contract);validate_record(root,record,s['inputs'])
    write_json(root/'inner.json',{'annotation':'REPLACED'});record['assets'][1]['sha256']=file_sha256(root/'inner.json')
    after=annotation_hash(record['payload'],record['binding']['inputs'],record['assets'],case_root=root)
    assert before!=after
    with pytest.raises(Exception,match='model_provenance'):validate_record(root,record,s['inputs'])


def test_review_wave2_nested_annotation_remaps_and_new_key_preserves_old_cache(tmp_path):
    from hre.evidence import annotation_hash,_read_cache_entry
    from hre.storage import write_json,read_json
    from hre.models import file_sha256
    s,item,record=offline_bundle(tmp_path/'worker','T1_OCR');root=tmp_path/'worker'
    write_json(root/'outer.json',{'nested_asset_id':'inner'});write_json(root/'inner.json',{'source_asset_id':'A','annotation':'original'})
    record['assets']=[dict(asset_id=name,path=name+'.json',sha256=file_sha256(root/(name+'.json')),role='evidence',width=None,height=None,color_space=None,evidence_format=dict(kind='json',dtype='annotation_json',value_range=None,coordinate_asset_id='A')) for name in ('outer','inner')]
    record['payload']['data']={'metadata_asset_id':'outer'};c=record['cache_contract'];c['model'].update(name='manual_annotation',revision='annotation_v1',weights_sha256=None);c['backend']['implementation']='manual_annotation'
    def finalize():
        c['parameters']={'annotation_version':'annotation_v1','annotation_sha256':annotation_hash(record['payload'],record['binding']['inputs'],record['assets'],case_root=root)}
        record['cache_key_sha256']=make_cache_key(c);write_json(root/'record.json',record)
        m=read_json(root/'evidence_bundle.json');m['records'][0]['sha256']=file_sha256(root/'record.json');write_json(root/'evidence_bundle.json',m)
        cfg=read_json(root/'config.json');cfg['tool_profile']['T1_OCR'].update(model=c['model'],parameters=c['parameters'],backend=c['backend']);write_json(root/'config.json',cfg)
        return cfg
    cfg=finalize();old_key=record['cache_key_sha256'];cache=tmp_path/'cache';register_cache_bundle(root,cache);old_bytes=(cache/old_key/'record.json').read_bytes()
    target=tmp_path/'target';target.mkdir();t=state(target);t['case_id']='other';t['inputs'][0]['asset_id']='newA';t['evidence_plan']=[item];write_json(target/'config.json',cfg)
    result=EvidenceService(target,cache).resolve(t);materialized=read_json(target/result['snapshot']['evidence'][0]['path'])
    assert annotation_hash(materialized['payload'],materialized['binding']['inputs'],list(reversed(materialized['assets'])),case_root=target)==c['parameters']['annotation_sha256']
    assert read_json(target/materialized['assets'][1]['path'])['source_asset_id']=='newA'
    write_json(root/'inner.json',{'source_asset_id':'A','annotation':'NEW source annotation'});record['assets'][1]['sha256']=file_sha256(root/'inner.json');finalize()
    new_key=record['cache_key_sha256'];assert new_key!=old_key;register_cache_bundle(root,cache)
    assert (cache/old_key/'record.json').read_bytes()==old_bytes
    assert _read_cache_entry(cache/old_key)[0]['cache_key_sha256']==old_key
    assert _read_cache_entry(cache/new_key)[0]['cache_key_sha256']==new_key


def test_review_wave2_annotation_unknown_reference_and_cycle_rejected(tmp_path):
    from hre.evidence import annotation_hash
    from hre.storage import write_json
    from hre.models import file_sha256
    s,item,record=offline_bundle(tmp_path/'worker','T1_OCR');root=tmp_path/'worker'
    write_json(root/'outer.json',{'nested_asset_id':'inner'});write_json(root/'inner.json',{'nested_asset_id':'outer'})
    assets=[dict(asset_id=name,path=name+'.json',sha256=file_sha256(root/(name+'.json')),role='evidence',width=None,height=None,color_space=None,evidence_format=dict(kind='json',dtype='annotation_json',value_range=None,coordinate_asset_id='A')) for name in ('outer','inner')]
    payload=record['payload'];payload['data']={'metadata_asset_id':'outer'}
    with pytest.raises(Exception,match='annotation_cycle'):annotation_hash(payload,record['binding']['inputs'],assets,case_root=root)
    write_json(root/'inner.json',{'nested_asset_id':'undeclared'});assets[1]['sha256']=file_sha256(root/'inner.json')
    with pytest.raises(Exception,match='annotation_reference'):annotation_hash(payload,record['binding']['inputs'],assets,case_root=root)
    write_json(root/'inner.json',{'annotation':'changed without metadata byte hash'})
    with pytest.raises(Exception,match='asset_hash'):annotation_hash(payload,record['binding']['inputs'],assets,case_root=root)
