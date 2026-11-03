"""All new commands import the same installed engine; no API calls on help."""
import pytest
from hre.cli import main


@pytest.mark.parametrize('arguments', [
    ['reference-style', '--help'], ['reference-style', 'semantic-freeze', '--help'],
    ['reference-style', 'holistic-import', '--help'], ['reference-study', '--help'],
    ['reference-study', 'build', '--help'], ['reference-study', 'blind', '--help'],
    ['reference-evaluate', '--help'], ['models', '--help']])
def test_command_help_is_runnable(arguments):
    with pytest.raises(SystemExit) as result:
        main(arguments)
    assert result.value.code == 0


@pytest.mark.parametrize('arguments',[
    ['reference-evaluate','resolve','--help'],['reference-style','holistic-resolve','--help'],
    ['reference-style','native-detail-request','--help'],['reference-style','native-detail-import','--help']])
def test_bound_resolution_and_native_detail_help(arguments):
    with pytest.raises(SystemExit) as result:main(arguments)
    assert result.value.code==0


def test_actual_resolution_cli_imports_file_bound_observation(tmp_path):
    import json
    from hre.reference_core import evaluation
    from test_reference_evaluation import review_spec
    root=tmp_path/'review';records=[]
    for stage in evaluation.STAGES:
        spec=review_spec(tmp_path,stage,None if not records else records[-1]['content_hash'])
        if stage=='explanations':spec['conflicts']=['Actual synthetic CLI discrepancy']
        records.append(evaluation.append_review(root,spec))
    last=records[-1]
    spec=dict(schema_version='hre_holistic_resolution_v1',resolution_id='resolution1',sample_id=last['payload']['sample_id'],
        predecessor_hash=last['content_hash'],review_hashes=[r['content_hash'] for r in records],images=last['payload']['images'],
        display=last['payload']['display'],reviewer=last['payload']['reviewer'],resolutions=[dict(review_hash=last['content_hash'],conflict_index=0,
            conflict=last['payload']['conflicts'][0],status='resolved',confidence='high',evidence='Actual file-bound synthetic CLI resolution')])
    path=tmp_path/'resolution.json';path.write_text(json.dumps(spec),encoding='utf-8')
    assert main(['reference-evaluate','resolve','--root',str(root),'--spec',str(path)])==0
    assert not evaluation.conflict_state(root)['unresolved_conflicts']
