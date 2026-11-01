"""Opt-in actual worker M0 tests; no mocks or model calls allowed."""
from pathlib import Path
import numpy as np
from .color import require,resolve_domain
from .planner import TOOLS,validate_plan,identity
from ..storage import write_json

def probe(backend,out):
    require(not backend.simulation,'M0 needs actual PhotoCraft backend')
    out=Path(out);require(not out.exists(),'probe output must be new');out.mkdir(parents=True)
    x=np.linspace(.08,.8,257);a=np.broadcast_to(x[None,:,None],(129,257,3)).copy();a*=np.array([1.,.75,.5])
    checks=[];empty={'operations':[],'reason':'identity probe','feedback_ids':[]}
    plain=backend.render_from_source(a,empty,(),{})
    checks.append({'check':'identity','pass':bool(np.max(abs(a-plain))<=2/65535),'max_error':float(np.max(abs(a-plain)))})
    active={'gamma':(1.2,), 'brightness_contrast':(10.,10.), 'exposure':(.25,), 'curve':(144.,), 'balance':(0.,5.), 'saturation':(10.,)}
    for tool,specs in TOOLS.items():
        params={k:dict(lower=v[0],upper=v[1],suggested=v[2],min_step=v[3]) for k,v in specs.items()}
        plan={'operations':[dict(id='probe',tool=tool,target_ids=['probe'],mask_id=None,parameters=params,expected_effect='probe',protect_target_ids=[])],'reason':'probe','feedback_ids':[]}
        validate_plan(plan,{'targets':[{'id':'probe'}]},{});values=identity(plan)
        neutral=backend.render_from_source(a,plan,values,{})
        checks.append({'check':tool+'_identity','pass':bool(np.max(abs(a-neutral))<=2/65535),'max_error':float(np.max(abs(a-neutral)))})
        changed=backend.render_from_source(a,plan,active[tool],{})
        delta=float(np.max(abs(changed-neutral)))
        checks.append({'check':tool+'_nonzero','pass':bool(delta>1e-4),'max_change':delta})
    plan={'operations':[dict(id='e',tool='exposure',target_ids=['probe'],mask_id='m',parameters={'ev':dict(lower=-1.,upper=1.,suggested=0.,min_step=.015625)},expected_effect='brighten',protect_target_ids=[])],'reason':'locality probe','feedback_ids':[]}
    for name,m in [('zero',np.zeros(a.shape[:2])),('one',np.ones(a.shape[:2])),('local',np.pad(np.ones((65,129)),((32,32),(64,64))))]:
        c=backend.render_from_source(a,plan,(.25,),{'m':m});outside=m==0
        checks.append({'check':'mask_'+name,'pass':bool((not outside.any() or np.max(abs(c[outside]-a[outside]))<=2/65535) and (not m.any() or np.mean(c[m>0])>np.mean(a[m>0])) )})
        actual,meta=backend.export_native(out/f'{name}.png',c)
        checks.append({'check':'native_'+name,'pass':actual.shape==a.shape and meta['bit_depth']==16 and bool(meta['icc_sha256'])})
        checks.append({'check':'replay_'+name,**backend.replay(a,plan,(.25,),{'m':m},c,0.)})
    # Soft external mask must interpolate actual backend results, including its edges.
    soft=np.broadcast_to(np.linspace(0,1,a.shape[1]),a.shape[:2]).copy()
    zero=backend.render_from_source(a,plan,(.25,),{'m':np.zeros_like(soft)})
    one=backend.render_from_source(a,plan,(.25,),{'m':np.ones_like(soft)})
    blend=backend.render_from_source(a,plan,(.25,),{'m':soft})
    error=float(np.max(abs(blend-(zero+(one-zero)*soft[...,None]))))
    checks.append({'check':'soft_mask_edges','pass':error<=4/65535,'max_error':error})
    large=np.broadcast_to(np.linspace(.08,.8,1537)[None,:,None],(1409,1537,3)).copy()
    native=backend.render_from_source(large,empty,(),{})
    actual,meta=backend.export_native(out/'native_large.png',native)
    err=float(np.max(abs(actual-large)))
    checks.append({'check':'native_over_2mp_identity_roundtrip','pass':actual.shape==large.shape and meta['bit_depth']==16 and bool(meta['icc_sha256']) and err<=2/65535,'shape':list(actual.shape),'max_error':err})
    result={'backend':backend.identity,'checks':checks,'pass':all(c['pass'] for c in checks),'real_vlm':False,'real_photo_effect':False,'color_domain':resolve_domain(getattr(backend,'domain',None)).identity,'capability_scope':f"synthetic CPU U16 {resolve_domain(getattr(backend,'domain',None)).id}; no band rendering or Photoshop equivalence"}
    write_json(out/'probe.json',result);return result
