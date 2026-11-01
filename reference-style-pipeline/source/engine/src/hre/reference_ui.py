"""Read/evaluate v2 cases in the existing six-tab UI, without capability toggles."""
from pathlib import Path
import numpy as np
from .storage import read_json
from .models import HREError


def render_reference_panel(st,root):
    config=read_json(Path(root)/'config.json')
    if 'reference_v2' not in config:return
    from .reference_runtime import v2_status,evaluate_reference_case
    from .masks import validate_mask
    from .storage import CaseStore
    spec=config['reference_v2'];status=v2_status(root)
    with st.expander('Generative reference enhancement v2',expanded=True):
        st.write(f"Arm: {status['arm_id']} · scope: {status['task_scope']}")
        st.write(f"Mask capability: {status['capability']} · mode: {status['mask_mode'] or 'unavailable'}")
        st.caption('A/B/C regions are frozen independently. Region metrics explain appearance changes; independent content review remains required.')
        st.caption('Mask guidance is soft. A capability proof cannot be enabled by a checkbox. Changed executor versions/settings require a new probe and revision.')
        if status['simulation_only']:st.warning('Synthetic protocol fixture; no real image-model efficacy or capability claim.')
        st.json({'executor':status['executor'],'target_regions':spec['roi_pairs']})
        a=CaseStore(root).load()['inputs'][0]
        for name in ('eval_mask','edit_mask'):
            if spec[name] is not None:
                st.image(validate_mask(root,spec[name],a)*np.uint8(255),caption=name+' preview: white = allow_edit/target; preview only')
        if st.button('Evaluate frozen A/B/C regions',key='reference_v2_evaluate'):
            try:st.json(evaluate_reference_case(root))
            except (HREError,ValueError,OSError) as exc:st.error(str(exc))
        index=Path(root)/'evaluation/reference_attributes_v2.json'
        if index.exists():
            from .masks import checked_file
            st.json(read_json(checked_file(root,read_json(index))))
