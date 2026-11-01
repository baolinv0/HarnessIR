"""Single-user Streamlit frontend; persisted Controller state is the sole workflow source."""
from pathlib import Path
from tempfile import TemporaryDirectory
import io
import json
import os
import zipfile

from hre.models import HREError
from hre.cli import list_cases, current_request, import_payload, import_candidate_manual

ACTIVE_ANALYSIS={'WAIT_DIAGNOSIS','WAIT_COMPOSITION','WAIT_VERIFICATION','WAIT_REFINEMENT'}
TERMINAL={'COMPLETED','FAILED','CANCELLED'}


def allowed_operations(state: str) -> tuple[str,...]:
    common=('export','history')
    if state=='CREATED':return common+('start','cancel','new_revision')
    if state in ACTIVE_ANALYSIS:return common+('task','response','retry_transport','pause','cancel')
    if state=='WAIT_EXECUTION':return common+('task','candidate','execution_error','submitted','retry_transport','pause','cancel')
    if state=='WAIT_EVIDENCE':return common+('evidence','pause','cancel')
    if state=='PAUSED':return common+('resume','reconcile','cancel','new_revision')
    return common+('new_revision',)


def archive(root: Path) -> bytes:
    """Case package retains all raw provenance; files stay in their original revision."""
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w',zipfile.ZIP_DEFLATED) as z:
        for path in sorted(root.rglob('*')):
            if path.is_file() and not path.is_symlink() and path.name not in {'.lock','state.lock'}:
                z.write(path,path.relative_to(root).as_posix())
    return data.getvalue()


def bind_uploaded_extras(metadata: dict, uploads: list, rows: list[dict], directory: Path) -> dict:
    """Bind declared filenames to controlled temporary paths; never infer provider order."""
    if not isinstance(rows,list) or not all(isinstance(row,dict) for row in rows):
        raise HREError('extra_order_required','Extra upload order table must contain explicit source filename, provider_order and complete.')
    names=[upload.name for upload in uploads]
    declared=[row.get('source') for row in rows]
    if len(set(names))!=len(names) or len(set(declared))!=len(declared) or set(names)!=set(declared):
        raise HREError('extra_filename_mismatch','Each uploaded filename must occur exactly once in the explicit order table.')
    if metadata.get('extras'):
        raise HREError('ambiguous_extras','Choose uploaded extra rows or metadata extras paths, not both.')
    from hre.desktop import validate_output_order
    validate_output_order({**metadata,'extras':rows})
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    paths={}
    for index,upload in enumerate(uploads):
        path=directory/f'extra_{index:03d}.bin'
        path.write_bytes(upload.getvalue());paths[upload.name]=str(path)
    return {**metadata,'extras':[{**row,'source':paths[row['source']]} for row in rows]}


def render_app():
    import streamlit as st
    from hre.storage import read_json
    from hre.paths import safe_path, make_id
    from hre.workflow import Controller
    from hre.assets import create_case
    st.set_page_config(page_title='HarnessRefEnhance',layout='wide')
    st.title('HarnessRefEnhance')
    status_slot=st.empty()
    st.caption('A is the frozen editing base. B guides comparable appearance; it is not pixel ground truth. Preserve A content.')
    data_root=Path(st.sidebar.text_input('Case collection directory',os.environ.get('HRE_DATA_ROOT','Data/ref_enhance_cases')))
    cases=list_cases(data_root)
    tabs=st.tabs(['Cases','A / B and comparability','Task and evidence','Candidates','History','Export and capabilities'])
    with tabs[0]:
        st.subheader('Cases and historical revisions')
        if cases:st.dataframe(cases,use_container_width=True)
        available=[item['case_root'] for item in cases if item.get('compatible')]
        chosen=st.selectbox('Current case revision directory',available,index=0) if available else None
        st.caption('The collection is read-only for discovery. Each action targets one exact revision containing state.json.')
        with st.expander('Create a new frozen revision',expanded=not available):
            a=st.file_uploader('Editing base A',type=['png','jpg','jpeg','tif','tiff'],key='A')
            b=st.file_uploader('Appearance reference B',type=['png','jpg','jpeg','tif','tiff'],key='B')
            if a:st.image(a,caption='A preview — editing base')
            if b:st.image(b,caption='B preview — appearance only')
            case_name=st.text_input('New case ID','case_new')
            revision=st.number_input('New frozen case revision',min_value=1,value=1,step=1)
            profile=st.selectbox('Frozen experiment profile',['agent_adaptive','agent_single','direct_ref','direct_best_of_3','baseline'])
            assume=st.checkbox('Explicitly assume untagged SDR inputs are sRGB',value=False)
            annotation=st.selectbox('Reference usability annotation',['unknown','usable','unusable'])
            comparable=st.checkbox('I checked global or annotated ROI comparability and excluded changed content',value=False)
            limitations=st.text_area('Reference limitations and comparison scope','')
            roi_json=st.text_area('Optional independent A/B ROI manifest JSON','[]')
            manifest_json=st.text_area('Optional source provenance manifest JSON','{}')
            cache_root=st.text_input('Offline evidence cache directory','Data/ref_enhance_cache')
            config_json=st.text_area('Additional frozen runtime configuration JSON','{}',help='For tool_profile and protected_content. Displayed settings override these keys.')
            if st.button('Create frozen case',disabled=not(a and b)):
                try:
                    if annotation=='usable' and not(comparable and limitations.strip()):
                        raise HREError('annotation_required','Usable reference needs confirmed comparability and explicit limitations/scope.')
                    config=json.loads(config_json)
                    config.update({'profile_id':profile,'assume_srgb':assume,'reference_usable':annotation,
                                   'reference_limitations':[limitations] if limitations.strip() else [],'roi_manifest':json.loads(roi_json),'cache_root':cache_root})
                    manifest=json.loads(manifest_json);manifest.update({'case_id':case_name,'case_revision':int(revision)})
                    dest=safe_path(data_root,f'{case_name}/rev{revision}')
                    with TemporaryDirectory() as temp:
                        pa=Path(temp)/('A'+Path(a.name).suffix);pb=Path(temp)/('B'+Path(b.name).suffix)
                        pa.write_bytes(a.getvalue());pb.write_bytes(b.getvalue())
                        create_case(pa,pb,manifest,config,dest)
                    st.success(f'Frozen revision created: {dest}');st.rerun()
                except (HREError,ValueError,OSError,TypeError) as exc:st.error(str(exc))
    if not chosen:
        with tabs[2]:st.info('Create or select a compatible case revision to continue. Historical files are retained.')
        return
    root=Path(chosen);controller=Controller(root)
    try:state=controller.state()
    except (HREError,OSError) as exc:st.error(str(exc));return
    workflow=state['workflow_state'];ops=allowed_operations(workflow)
    pending=state.get('pending_task') or {}
    status_slot.markdown(f"**{workflow}** · round {pending.get('round',state.get('round',0))} · attempt {pending.get('attempt',0)} · generations {state['budget']['consumed']}/{state['budget']['max_generations']} · reserved {state['budget']['reserved']}")
    if state.get('pause_reason'):st.warning(state['pause_reason'])
    with tabs[1]:
        from hre.reference_ui import render_reference_panel
        render_reference_panel(st,root)
    def action(label, callback, key=None):
        if st.button(label,key=key):
            try:
                result=callback()
                if hasattr(result,'model_dump'):result=result.model_dump()
                st.session_state['last_result']=result
                st.rerun()
            except (HREError,OSError,ValueError,KeyError,TypeError) as exc:st.error(str(exc))
    with tabs[0]:
        if 'start' in ops:action('Start',controller.start)
        if 'pause' in ops:action('Pause',lambda:controller.pause('operator paused in UI'))
        if 'resume' in ops:
            resume_action=st.selectbox('Resume action',['continue','retry_analysis','retry','reconcile_submitted','release_unsubmitted','stop'])
            action('Resume',lambda:controller.resume(resume_action))
            ledger=state['budget']['ledger']
            retry_confirmed=bool(ledger and (ledger[-1]['status']=='released_unsubmitted' or (ledger[-1]['status']=='submitted' and ledger[-1]['outcome']=='error')))
            if state.get('resume_state')=='WAIT_EXECUTION' and not pending and retry_confirmed:
                st.caption('A new generation retry creates a new task and reserves remaining budget. It requires confirmed failure or confirmed non-submission.')
                action('Retry generation (new task and reserved budget)',lambda:controller.resume('retry_generation'))
            if state.get('resume_state')=='WAIT_EXECUTION' and pending:
                st.caption('Reconcile unknown submission before continuing; reserved budget stays held.')
                reconcile_count=st.number_input('Observed actual generation count',min_value=1,value=1,step=1)
                action('Confirm submitted while paused',lambda:controller.mark_submitted(pending['task_id'],int(reconcile_count)))
                action('Confirm never submitted and release reservation',lambda:controller.release_unsubmitted(pending['task_id']))
            st.info('Frozen reference annotation and policy cannot be changed here. Create a new revision for changed inputs or policy.')
        if 'cancel' in ops:action('Cancel',lambda:controller.cancel('operator cancelled in UI'))
        if 'retry_transport' in ops:action('Retry transport (same task; no new generation)',controller.retry_transport)
        if 'last_result' in st.session_state:st.json(st.session_state['last_result'])
    with tabs[1]:
        for column,key,label in zip(st.columns(2),['prediction','reference'],['Editing base A','Appearance reference B']):
            asset=next(a for a in state['inputs'] if a['role']==key)
            with column:
                st.image(str(safe_path(root,asset['path'],must_exist=True)),caption=label)
                st.json(asset)
        config=read_json(root/'config.json')
        st.json({'reference_usable':config['reference_usable'],'reference_limitations':config.get('reference_limitations'),'roi_manifest':config.get('roi_manifest'),'config_sha256':state['config_sha256']})
        st.caption('ROI coordinates are independent for A and B. Changes require a new frozen revision.')
    with tabs[2]:
        st.subheader('Current task and planned evidence')
        st.json({'pending_task':state.get('pending_task'),'evidence_plan':state.get('evidence_plan'),
                 'evidence_snapshot':state.get('evidence_snapshot')})
        if 'task' in ops:
            try:
                from hre.prompts import build_context, render_stage
                from hre.desktop import export_task_bundle
                request=current_request(root)
                prompt=render_stage(request['stage'],build_context(root,request),case_root=root)
                st.code(prompt,language=None)
                st.download_button('Download prompt',prompt,file_name=f"{request['task_id']}.txt")
                with TemporaryDirectory() as temp:
                    bundle=export_task_bundle(request,Path(temp)/'bundle',case_root=root)
                    st.download_button('Download current task bundle',archive(Path(bundle)),file_name=f"{request['task_id']}.zip")
            except (HREError,OSError,ValueError,KeyError) as exc:st.error(f'Task bundle unavailable: {exc}')
        if 'response' in ops:
            raw=st.text_area('Paste stage JSON payload','',key='payload')
            upload=st.file_uploader('Or import stage JSON file',type=['json'],key='response_file')
            model_name=st.text_input('Observed UI model display name','unknown')
            if st.button('Validate and import response'):
                try:
                    source=upload.getvalue() if upload else raw.encode()
                    with TemporaryDirectory() as temp:
                        path=Path(temp)/'payload.json';path.write_bytes(source);payload=read_json(path)
                    result=import_payload(root,payload,raw_text=source,provenance={'transport':'desktop_manual','ui_model_name':model_name,'operator_steps':['Manual JSON import in Streamlit']})
                    st.session_state['last_result']=result.model_dump();st.rerun()
                except (HREError,OSError,ValueError,KeyError) as exc:st.error(str(exc))
        if 'evidence' in ops:
            from hre.evidence import EvidenceService, register_cache_bundle
            resolution=EvidenceService(root).resolve(state)
            st.json({'missing':resolution['missing'],'plan':resolution['plan']})
            st.download_button('Download offline evidence plan',json.dumps(resolution['plan'],indent=2),file_name='offline_plan.json')
            jobs_dir=st.text_input('Offline jobs export directory',str(root/'exports'/'missing_jobs'))
            action('Export complete offline jobs and frozen inputs',lambda:{'path':str(EvidenceService(root).export_missing_jobs(state,Path(jobs_dir)))})
            precomputed_dir=st.text_input('Builtin STATS / ROI output bundle directory',str(root/'exports'/'builtin_bundle'))
            action('Precompute planned CPU evidence bundle',lambda:{'path':str(EvidenceService(root).precompute_bundle(state,state['evidence_plan'],Path(precomputed_dir)))})
            bundle_path=st.text_input('Precomputed evidence bundle directory')
            import_cache=st.text_input('Evidence cache destination','Data/ref_enhance_cache')
            if st.button('Validate and register evidence bundle',disabled=not bundle_path):
                try:register_cache_bundle(Path(bundle_path),Path(import_cache));controller.collect_evidence();st.rerun()
                except (HREError,OSError,ValueError) as exc:st.error(str(exc))
            action('Retry evidence validation',controller.collect_evidence)
        if 'candidate' in ops:
            st.caption('Every generation uses frozen A+B. Saving C does not imply acceptance.')
            image=st.file_uploader('Raw candidate C',type=['png','jpg','jpeg','tif','tiff'],key='candidate')
            extra_uploads=st.file_uploader('Extra raw outputs (including partial outputs)',accept_multiple_files=True,key='raw_extras')
            extra_rows_json=st.text_area('Extra upload order/completion JSON table (source = exact filename)','[]',help='Each uploaded filename needs explicit observed provider_order and complete boolean. No order is inferred from file selection.')
            if extra_uploads:st.write({'uploaded_filenames':[upload.name for upload in extra_uploads]})
            submission=st.selectbox('Actual external submission status',['unknown','submitted','already_recorded','not_submitted'])
            metadata=st.text_area('Observed candidate metadata JSON','{"actual_generation_count":1,"provider_order":0}')
            if st.button('Validate and import raw candidate',disabled=image is None):
                try:
                    with TemporaryDirectory() as temp:
                        path=Path(temp)/('C'+Path(image.name).suffix);path.write_bytes(image.getvalue())
                        observed_metadata=json.loads(metadata)
                        if extra_uploads:observed_metadata=bind_uploaded_extras(observed_metadata,extra_uploads,json.loads(extra_rows_json),Path(temp)/'extras')
                        elif json.loads(extra_rows_json):raise HREError('extra_filename_mismatch','Order table supplied without matching uploaded files.')
                        result=import_candidate_manual(root,pending['task_id'],path,observed_metadata,submission)
                    st.session_state['last_result']=result.model_dump();st.rerun()
                except (HREError,OSError,ValueError,KeyError,TypeError) as exc:st.error(str(exc))
            action('Submission result unknown: pause and hold budget',lambda:controller.mark_submission_unknown(pending['task_id']))
            if st.button('Record confirmed generation submission'):
                try:controller.mark_submitted(pending['task_id']);st.rerun()
                except HREError as exc:st.error(str(exc))
            failure_code=st.selectbox('External execution failure',['generation_error','image_not_saved','timeout','refusal'])
            if st.button('Record submitted execution failure'):
                try:
                    controller.mark_submitted(pending['task_id'])
                    result=import_payload(root,None,error={'code':failure_code,'message':'Operator reported external execution failure','retryable':False})
                    st.session_state['last_result']=result.model_dump();st.rerun()
                except (HREError,ValueError,KeyError) as exc:st.error(str(exc))
    with tabs[3]:
        st.subheader('Candidate history and selection')
        st.json({'success':state['success'],'terminal_reason':state['terminal_reason'],'selection':state['selection']})
        for item in state.get('candidates',state.get('rounds',[])):
            st.json(item)
            asset=item.get('asset') or item.get('candidate_asset') or item.get('raw_asset')
            if asset and asset.get('path'):
                st.image(str(safe_path(root,asset['path'],must_exist=True)),caption=f"Candidate C — {item.get('candidate_id','unknown')}")
    with tabs[4]:
        st.subheader('State, budget ledger and immutable audit history')
        st.json(state['budget'])
        for path in sorted(root.rglob('*.json')):
            if 'transactions' in path.parts or 'event' in path.parts or 'events' in path.parts or 'log' in path.name or (path.name=='response.json' and 'accepted' in path.parts):
                with st.expander(str(path.relative_to(root))):
                    try:st.json(read_json(path))
                    except (HREError,OSError):st.caption('Record unreadable; retained for inspection.')
        with st.expander('Full persisted state'):st.json(state)
    with tabs[5]:
        from hre.capabilities import run_capability_probe
        st.subheader('Independent capability evidence')
        cap_path=root/'capabilities.json'
        capabilities=read_json(cap_path).get('capabilities',{}) if cap_path.exists() else {}
        for name in ['local_file_io','role_dispatch','two_image_edit','image_save']:
            st.write(f"{name}: {capabilities.get(name,{}).get('status','untested')}")
        st.caption('Local controller file I/O does not prove desktop file I/O, role dispatch, two-image editing or image saving.')
        probe_name=st.selectbox('Capability to inspect',['local_file_io','role_dispatch','two_image_edit','image_save'])
        evidence_path=st.text_input('Optional real capability evidence JSON path')
        action('Record capability probe',lambda:run_capability_probe(probe_name,root,evidence=read_json(Path(evidence_path)) if evidence_path else None))
        st.download_button('Download full case and provenance',archive(root),file_name=f"{state['case_id']}_rev{state['case_revision']}.zip")
        if workflow in TERMINAL:
            from hre.reporting import write_report
            action('Generate report',lambda:{'path':str(write_report(root))})
            from hre.reporting import resolve_selected_asset
            selected=resolve_selected_asset(state)
            if selected:
                st.download_button('Download selected image',safe_path(root,selected['path'],must_exist=True).read_bytes(),file_name='selected.png')
            st.caption('Training candidate review remains pending. B and generated C are not ground truth.')


if __name__=='__main__':render_app()
