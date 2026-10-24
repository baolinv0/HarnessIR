#!/usr/bin/env python3
"""Strict paired, scene-clustered bootstrap for external measured CSVs.

No model calls and no metrics are generated here. Replicates are averaged within
image, images within scene, then scenes are bootstrapped. Non-OK or incomplete
cohorts are rejected; report failures separately before constructing this CSV.
"""
import argparse
import csv
import json
import math
import random
from collections import defaultdict
from statistics import mean


def scene_effects(rows, model, control, treatment, metric, direction, expected=None):
    if direction not in (-1,1) or control == treatment:
        raise ValueError('Use distinct arms and direction -1 or 1')
    arms={control:{},treatment:{}}
    for r in rows:
        if r['model'] != model or r['metric'] != metric or r['arm'] not in arms:
            continue
        if r['status'] != 'ok':
            raise ValueError('Non-OK outcome; audit failures separately, never fill with zero')
        key=tuple(r[k] for k in ('scene_id','sample_id','replicate'))
        if any(not x for x in key) or key in arms[r['arm']]:
            raise ValueError('Missing identity or duplicate outcome')
        value=float(r['value'])
        if not math.isfinite(value):
            raise ValueError('Finite measured values required')
        arms[r['arm']][key]=value
    a,b=arms[control],arms[treatment]
    if not a or set(a)!=set(b):
        raise ValueError('Nonempty exact paired cohort required; missing outcomes cannot be dropped silently')
    if expected is not None:
        expected=list(expected)
        if len(expected)!=len(set(expected)) or set(a)!=set(expected):
            raise ValueError('Observed cohort differs from frozen expected manifest')
    images=defaultdict(list)
    for key in a:
        images[key[:2]].append(direction*(b[key]-a[key]))
    scenes=defaultdict(list)
    for (scene,_),values in images.items():
        scenes[scene].append(mean(values))
    return {scene:mean(values) for scene,values in sorted(scenes.items())}


def summarize(effects, *, seed=20261024, draws=10000):
    if len(effects)<2 or draws<100:
        raise ValueError('Need >=2 independent scenes and >=100 bootstrap draws')
    values=list(effects.values())
    rng=random.Random(seed)
    samples=sorted(mean(rng.choices(values,k=len(values))) for _ in range(draws))
    return dict(n_scenes=len(values),effect=mean(values),
                ci95=[samples[int(.025*draws)],samples[min(draws-1,int(.975*draws))]],
                bootstrap_draws=draws,bootstrap_seed=seed,
                unit='scene',estimand='equal-scene mean of within-image replicate-mean paired effects',
                provenance='external CSV; not automatically a verified experiment')


def compare(rows,model,control,treatment,metric,direction,*,expected=None,**kwargs):
    result=summarize(scene_effects(rows,model,control,treatment,metric,direction,expected),**kwargs)
    result['cohort_bound']=expected is not None
    return result


def interaction(rows,model_a,model_b,control,treatment,metric,direction,*,expected=None,**kwargs):
    a=scene_effects(rows,model_a,control,treatment,metric,direction,expected)
    b=scene_effects(rows,model_b,control,treatment,metric,direction,expected)
    # Match image/replicate identities across models, not only scene labels.
    def cohort(model):
        return {(r['scene_id'],r['sample_id'],r['replicate']) for r in rows
                if r['model']==model and r['metric']==metric and r['arm']==control}
    if set(a)!=set(b) or cohort(model_a)!=cohort(model_b):
        raise ValueError('Interaction requires the same image and replicate cohort in both models')
    result=summarize({scene:a[scene]-b[scene] for scene in a},**kwargs)
    result['contrast']=f'({model_a}: {treatment}-{control}) - ({model_b}: {treatment}-{control})'
    result['cohort_bound']=expected is not None
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('csv');p.add_argument('--model',required=True)
    p.add_argument('--cohort',required=True,help='Frozen CSV with scene_id,sample_id,replicate; exact expected quality cohort')
    p.add_argument('--model-b');p.add_argument('--control',required=True)
    p.add_argument('--treatment',required=True);p.add_argument('--metric',required=True)
    p.add_argument('--direction',type=int,choices=(-1,1),required=True)
    p.add_argument('--draws',type=int,default=10000)
    args=p.parse_args()
    with open(args.csv,newline='',encoding='utf-8') as f: rows=list(csv.DictReader(f))
    with open(args.cohort,newline='',encoding='utf-8') as f:
        expected=[tuple(r[k] for k in ('scene_id','sample_id','replicate')) for r in csv.DictReader(f)]
    fn=interaction if args.model_b else compare
    models=[args.model,args.model_b] if args.model_b else [args.model]
    print(json.dumps(fn(rows,*models,args.control,args.treatment,args.metric,args.direction,
                        expected=expected,draws=args.draws),ensure_ascii=False,indent=2,allow_nan=False))


if __name__=='__main__':main()
