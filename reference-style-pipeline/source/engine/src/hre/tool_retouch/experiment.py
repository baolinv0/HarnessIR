"""Paired G/T import, fixed common display scale, blind rating and ITT summaries.

This never generates a baseline, selects best-of-N, or interprets missing images as wins.
"""
from pathlib import Path
from collections import Counter
import hashlib
import json
import numpy as np
from ..storage import read_json,write_json
from .color import require,ColorContext,resize_float,preview_size,encode_png16,digest_bytes
from .contracts import strict,canonical,FrozenContract
from .verifier import target_results

def write_case_report(root,result):
    root=Path(root)
    text=['# Reference tool retouch 运行报告','',f'- 状态：{result["status"]}',f'- 成功：{result["success"]}',f'- 输出：{result["output"]}',
          f'- 真实效果已验证：{result.get("real_effect_validated",False)}',f'- 原因：{result.get("reason","无")}',
          f'- 合同：{result.get("contract_sha256","未冻结")}',f'- 预算：{result.get("budget",{})}',
          f'- 测试替身：{result.get("simulation",False)}','', '完整逐目标、操作、原生检查和错误记录：','', '```json',canonical(result),'```','',
          '自动通过不代替独立人审；本报告不声称摄影风格效果或 PS 数值等价。']
    text.extend(['','## 实际阶段顺序与变化','', '按持久化 trace 顺序列出；恢复尝试单独留痕，completed 不等同语义验收通过。未产生记录的阶段不伪造结果。'])
    observed=set()
    for path in sorted((root/'trace').glob('*.json')):
        row=read_json(path);observed.add(row['stage'])
        text.extend(['',f"### {row['sequence']} · {row['stage']} · {row['status']}",
                     f"来源：{row['source']}；耗时：{row['seconds']} 秒；尝试：{row['attempt']}",
                     f"相对前阶段：{row['change_from_previous_stage']}",f"对下一阶段：{row['impact_on_next_stage']}",
                     '图像：'+('产生工作像素/候选变化，详见实际输出；不是累积编辑' if row['image_changed'] else '未改变'),
                     f"输入哈希：{row['input_sha256']}；输出哈希：{row['output_sha256']}",
                     '```json',json.dumps({'inputs':row['inputs'],'actual_output':row['output']},ensure_ascii=False,indent=2),'```'])
    expected=['input_color_audit','discover_regions','segmentation','correspond_regions','statistics','diagnose','contract_frozen','plan','parameter_search','native_render','export','exported_native_acceptance','replay','verify','feedback_revision']
    text.extend(['','## 未记录阶段','',', '.join(x for x in expected if x not in observed) or '无',
                 '未记录可能是未运行、不适用或旧记录缺失；不能当作通过。','', '## 实际图像对照索引','',
                 '所有候选从原始 A 重渲染；轮间差值仅供比较，不累积编辑。'])
    for path in [root/'inputs'/'A-working.png',root/'inputs'/'B-working.png']+sorted(root.glob('native-attempt-*.png'))+sorted(root.glob('candidate-*.png')):
        if path.is_file():text.append(f"- {path.relative_to(root)} · SHA256 {digest_bytes(path.read_bytes())}")
    (root/'REPORT.md').write_text('\n'.join(text),encoding='utf8')

def export_experiment(manifest_path,out):
    manifest_path=Path(manifest_path);base=manifest_path.resolve().parent;m=read_json(manifest_path)
    strict(m,{'protocol_id','split','seed','development_case_ids','cases','baseline','original_user_goal'})
    require(m['split'] in ('development','held_out') and type(m['seed']) is int and m['original_user_goal'],'protocol fields')
    strict(m['baseline'],{'model','version','prompt_sha256','seed','configuration_sha256'})
    require(all(m['baseline'][k] for k in ('model','version','prompt_sha256','configuration_sha256')),'freeze actual strong baseline, no unknown placeholders')
    ids=[x['case_id'] for x in m['cases']];require(ids and len(ids)==len(set(ids)),'one row per image pair')
    if m['split']=='held_out':require(not set(ids)&set(m['development_case_ids']),'development/held-out leakage')
    out=Path(out);require(not out.exists(),'experiment output must be new');out.mkdir(parents=True);(out/'review').mkdir();mapping={};rows=[]
    for i,case in enumerate(m['cases']):
        strict(case,{'case_id','tool_run','G','source_sha256','reference_sha256'})
        run=(base/case['tool_run']).resolve();snapshot=read_json(run/'input_snapshot.json');result=read_json(run/'result.json')
        require(snapshot['config']['source']['sha256']==case['source_sha256'] and snapshot['config']['reference']['sha256']==case['reference_sha256'],'G/T source/reference not identical')
        a,_=ColorContext.load(run/'inputs'/'A-working.png');b,_=ColorContext.load(run/'inputs'/'B-working.png')
        candidates={};row={'case_id':case['case_id'],'T_status':result['status'],'G_status':case['G']['status'],'T_seconds':result.get('seconds'),'T_simulation':result.get('simulation',False)}
        strict(case['G'],{'status','path','sha256','source_sha256','reference_sha256','baseline_configuration_sha256'})
        require(case['G']['source_sha256']==case['source_sha256'] and case['G']['reference_sha256']==case['reference_sha256'] and case['G']['baseline_configuration_sha256']==m['baseline']['configuration_sha256'],'baseline receipt binding')
        if case['G']['status']=='output':
            gp=(base/case['G']['path']).resolve();require(digest_bytes(gp.read_bytes())==case['G']['sha256'],'G file changed')
            candidates['G'],_=ColorContext.load(gp)
        else:require(case['G']['status'] in ('execution_failed','not_run'),'unknown baseline state')
        if result['output']=='original_A':candidates['T']=a
        else:
            tp=(run/result['output']).resolve();require(tp.parent==run,'candidate escapes run')
            candidates['T'],_=ColorContext.load(tp)
            require(result['delivery']['pixel_sha256']==__import__('hre.tool_retouch.evidence',fromlist=['array_hash']).array_hash(candidates['T']),'T pixels changed')
        frozen=run/'contract.json'
        if frozen.exists():
            record=read_json(frozen);contract=FrozenContract(canonical(record['contract']),record['sha256']);contract.verify()
            support=np.load(run/'evaluation_supports.npz',allow_pickle=False)
            supports={p['id']:support[f'{j}_a'] for j,p in enumerate(contract.data['region_pairs']) if p['comparability']!='not_comparable'}
            row['contract_sha256']=contract.sha256
            row['targets']={arm:target_results(im,contract,supports) if im.shape==a.shape else 'not measured: native geometry differs' for arm,im in candidates.items()}
        row['native_dimensions']={arm:[im.shape[1],im.shape[0]] for arm,im in candidates.items()}
        row['native_delivery']={arm:im.shape==a.shape for arm,im in candidates.items()}
        public_id=f'pair-{i+1:03d}';directory=out/'review'/public_id;directory.mkdir()
        encode_png16(directory/'A.png',resize_float(a,preview_size(a,1024)));encode_png16(directory/'B.png',resize_float(b,preview_size(b,1024)))
        order=['G','T'] if hashlib.sha256(f'{m["seed"]}:{case["case_id"]}'.encode()).digest()[0]&1 else ['T','G']
        mapping[public_id]={'case_id':case['case_id'],'X':order[0],'Y':order[1]}
        # Common scale does not upsample small outputs or conceal native dimensions in private report.
        display_side=min([1024]+[max(im.shape[:2]) for im in candidates.values()]+[max(a.shape[:2])])
        for label,arm in zip(('X','Y'),order):
            if arm in candidates:
                encode_png16(directory/f'{label}.png',resize_float(candidates[arm],preview_size(candidates[arm],display_side)))
                encode_png16(directory/f'{label}-native.png',candidates[arm])
            else:(directory/f'{label}-missing.txt').write_text('No output; retain this pair in ITT accounting.')
        rows.append(row)
    protocol_hash=digest_bytes(canonical(m).encode());write_json(out/'protocol.json',{'sha256':protocol_hash,'manifest':m});write_json(out/'private_mapping.json',mapping);write_json(out/'results.json',{'cases':rows})
    (out/'review'/'INSTRUCTIONS.md').write_text('# 匿名评审\n\n第一阶段：只看 A/B/X/Y 和完整原始用户目标，分别判断参考风格、内容保持、自然协调与任务完成；写遗漏的参考目标。第二阶段才由管理员提供冻结合同，核对每个目标。原生图另检查边缘、文字、身份。失败/缺失图不排除；一对图像是一个样本。\n\n原始用户目标：'+m['original_user_goal']+'\n',encoding='utf8')
    write_json(out/'ratings.template.json',{'protocol_sha256':protocol_hash,'reviewer':'填写独立评审者','phase':'before_contract','ratings':[{'pair_id':k,'winner':'unrated','reference_match':'unrated','content':'unrated','naturalness':'unrated','omitted_goals':''} for k in mapping]})
    return {'status':'exported','pairs':len(rows),'protocol_sha256':protocol_hash,'real_effect_validated':False}

def analyze(experiment,ratings_path):
    root=Path(experiment);protocol=read_json(root/'protocol.json');mapping=read_json(root/'private_mapping.json');ratings=read_json(ratings_path)
    strict(ratings,{'protocol_sha256','reviewer','phase','ratings'})
    require(ratings['protocol_sha256']==protocol['sha256'] and ratings['reviewer'] and ratings['phase']=='before_contract','need independent pre-contract review bound to protocol')
    require(len(ratings['ratings'])==len(mapping) and {r['pair_id'] for r in ratings['ratings']}==set(mapping),'include every planned pair once')
    wins=Counter()
    for r in ratings['ratings']:
        strict(r,{'pair_id','winner','reference_match','content','naturalness','omitted_goals'})
        for k in ('winner','reference_match','content','naturalness'):require(r[k] in ('X','Y','tie','unrated'),'review label')
        wins[mapping[r['pair_id']][r['winner']] if r['winner'] in ('X','Y') else r['winner']]+=1
    rows=read_json(root/'results.json')['cases'];summary={'image_pairs':len(rows),'reviewer':ratings['reviewer'],'wins':dict(wins),'T_statuses':dict(Counter(r['T_status'] for r in rows)),'G_statuses':dict(Counter(r['G_status'] for r in rows)),'raw_ratings':ratings,'limits':'single reviewer; paired image units; no general model ranking or statistical equivalence claim'}
    write_json(root/'analysis.json',summary);(root/'EXPERIMENT_REPORT.md').write_text('# G/T 成对实验报告\n\n```json\n'+json.dumps(summary,ensure_ascii=False,indent=2)+'\n```\n',encoding='utf8')
    return summary
