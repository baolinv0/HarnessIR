"""Immutable serialized target contract. Model values are references, not measurements."""
from dataclasses import dataclass
import json
import math
from .color import require,digest_bytes
from .evidence import pair_manifest

def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)

def number(x):return type(x) in (int,float) and math.isfinite(x)

def strict(x,keys):require(isinstance(x,dict) and set(x)==set(keys),'unknown or missing fields: '+','.join(sorted(set(x) ^ set(keys))) if isinstance(x,dict) else 'expected object')

@dataclass(frozen=True)
class FrozenContract:
    payload: str
    sha256: str
    @classmethod
    def freeze(cls,data):
        text=canonical(data);return cls(text,digest_bytes(text.encode()))
    @property
    def data(self):self.verify();return json.loads(self.payload)
    def verify(self):require(digest_bytes(self.payload.encode())==self.sha256,'contract hash mismatch')
    def save(self,path):
        with path.open('x',encoding='utf8') as f:f.write(canonical({'sha256':self.sha256,'contract':self.data}))

def compile_contract(proposal,observations,pairs,source,reference,policy,diagnosis=None):
    strict(proposal,{'targets','protected_properties','exclusions','uncertainties'})
    require(isinstance(proposal['targets'],list) and 0<len(proposal['targets'])<=32,'need explicit targets')
    require(all(isinstance(proposal[k],list) and all(isinstance(v,str) and v.strip() for v in proposal[k]) for k in ('protected_properties','exclusions','uncertainties')),'text arrays required')
    require(proposal['protected_properties'],'protection required')
    regions={p['id']:p for p in pairs};targets=[];ids=set();linked_deltas=set()
    if diagnosis is not None:
        require(set(diagnosis['protected_properties'])<=set(proposal['protected_properties']),'contract dropped diagnosed source protection')
        require(set(diagnosis['uncertainties'])<=set(proposal['uncertainties']),'contract dropped diagnosed uncertainty')
        deltas={d['id']:d for d in diagnosis['deltas']}
    for t in proposal['targets']:
        strict(t,{'id','kind','regions','metric','evidence_ids','tolerance_id','mandatory','direction','description'} | ({'delta_id'} if diagnosis is not None else set()))
        if diagnosis is not None:
            require(t['delta_id'] in deltas,'target missing diagnosed difference')
            delta=deltas[t['delta_id']]
            require(delta['transfer'] in ('target','preserve') and t['regions']==delta['regions'] and set(delta['evidence_ids'])<=set(t['evidence_ids']),'target changed diagnosed regions/evidence or transfers an excluded difference')
            linked_deltas.add(t['delta_id'])
        require(isinstance(t['id'],str) and t['id'] and t['id'] not in ids,'target identity');ids.add(t['id'])
        require(t['kind'] in ('interval','direction','relation','perceptual','protection') and type(t['mandatory']) is bool,'target kind/priority')
        require(isinstance(t['description'],str) and t['description'].strip(),'target description')
        require(isinstance(t['regions'],list) and t['regions'] and set(t['regions'])<=regions.keys(),'unknown regions')
        require(isinstance(t['evidence_ids'],list) and t['evidence_ids'] and set(t['evidence_ids'])<=observations.keys(),'unknown evidence')
        require(all(observations[e]['region'] in t['regions'] for e in t['evidence_ids']),'unrelated evidence')
        row=dict(t)
        if t['kind'] in ('perceptual','protection'):
            require(t['metric'] is None and t['tolerance_id'] is None and t['direction'] is None,'visual target cannot invent numerical measurements')
        else:
            require(len(t['regions'])==(2 if t['kind']=='relation' else 1),'target region count')
            require(all(regions[r]['comparability']!='not_comparable' for r in t['regions']),'not comparable numeric target')
            if t['kind']!='direction':require(all(regions[r]['comparability']=='comparable' for r in t['regions']),'partial comparisons require directional goals')
            tol=policy['tolerances'].get(t['tolerance_id']);require(number(tol) and tol>0,'unknown/invalid frozen tolerance')
            values={}
            for role in ('a','b'):
                refs=[f'{role}:{r}:{t["metric"]}' for r in t['regions']]
                require(all(e in t['evidence_ids'] and e in observations for e in refs),'target lacks actual bilateral metric evidence')
                v=[observations[e]['value'] for e in refs];values[role]=v[0] if len(v)==1 else v[0]-v[1]
            if t['kind']=='direction':
                require(t['direction'] in ('increase','decrease'),'direction required')
                sign=1 if t['direction']=='increase' else -1
                require(sign*(values['b']-values['a'])>tol,'direction contradicts evidence')
                row.update(lower=values['a']+tol if sign>0 else None,upper=values['a']-tol if sign<0 else None)
            else:
                require(t['direction'] is None,'interval has no direction')
                row.update(lower=values['b']-tol,upper=values['b']+tol)
            row.update(scale=tol,source_value=values['a'],reference_value=values['b'])
        targets.append(row)
    require(any(t['mandatory'] for t in targets),'need mandatory target')
    if diagnosis is not None:require({d['id'] for d in diagnosis['deltas'] if d['transfer']=='target'}<=linked_deltas,'contract omitted a diagnosed transfer target')
    return FrozenContract.freeze(dict(version='reference_tool_retouch_v1',source=source,reference=reference,observations=observations,
        region_pairs=pair_manifest(pairs),targets=targets,protected_properties=proposal['protected_properties'],exclusions=proposal['exclusions'],
        uncertainties=proposal['uncertainties'],policy=policy,measured_diagnosis=diagnosis))
