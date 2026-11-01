from pathlib import Path
import importlib.util


def test_explicit_synthetic_demo_runs_direct_agent_and_refinement(tmp_path):
    spec=importlib.util.spec_from_file_location('hre_synthetic_demo',Path(__file__).parents[1]/'examples'/'demo.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    output=module.run_demo(tmp_path/'demo')
    assert output['synthetic'] is True and output['actual_model_called'] is False
    assert set(output['cases'])=={'direct_ref','agent_single','agent_adaptive'}
    for profile, item in output['cases'].items():
        assert item['workflow_state']=='COMPLETED' and item['success'] is True
        assert item['consumed']==(2 if profile=='agent_adaptive' else 1)
        assert Path(item['report']).exists()
