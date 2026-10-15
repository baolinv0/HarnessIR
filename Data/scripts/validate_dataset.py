"""Read-only image/manifest audit. Writes a fresh report only inside the data root."""
import pathlib,json,hashlib,collections,argparse,sys
from PIL import Image
def validate(root):
 root=pathlib.Path(root).resolve();rows=json.loads((root/'manifest.json').read_text(encoding='utf-8'));supp=json.loads((root/'supplementary_manifest.json').read_text(encoding='utf-8'));errors=[];checked=0
 for row in rows+supp:
  for role in ['input','gt','mask']:
   rel=row.get(role+'_path','')
   if not rel:continue
   p=(root/rel).resolve()
   try:
    if not p.is_relative_to(root):raise ValueError('path escapes data root')
    if not p.is_file():raise ValueError('missing actual image')
    b=p.read_bytes()
    if hashlib.sha256(b).hexdigest()!=row[role+'_sha256']:raise ValueError('SHA256 mismatch')
    if len(b)!=row[role+'_bytes']:raise ValueError('byte count mismatch')
    with Image.open(p) as im:
     im.load()
     if im.size!=(row[role+'_width'],row[role+'_height']):raise ValueError('dimensions mismatch')
    if b[:8]==b'\x89PNG\r\n\x1a\n' and b[24]!=row[role+'_bit_depth']:raise ValueError('PNG bit depth mismatch')
    checked+=1
   except Exception as e:errors.append({'sample_id':row['sample_id'],'role':role,'path':rel,'error':str(e)})
 if len(set(r['input_sha256'] for r in rows))!=len(rows):errors.append({'error':'duplicate main input hashes'})
 if len(set(r['scene_id'] for r in rows))!=len(rows):errors.append({'error':'duplicate main scene IDs'})
 queue=[json.loads(x) for x in (root/'run_queue.jsonl').read_text(encoding='utf-8').splitlines()]
 if {r['sample_id'] for r in queue}!={r['sample_id'] for r in rows}:errors.append({'error':'queue/manifest sample IDs differ'})
 for q in queue:
  if any('gt' in k.lower() or 'ground_truth' in k.lower() for k in q):errors.append({'sample_id':q['sample_id'],'error':'GT field leaked to run queue'})
  if not(root/q['image_path']).is_file():errors.append({'sample_id':q['sample_id'],'error':'queue image missing'})
 official=json.loads((root/'harness_manifest_no_gt.json').read_text(encoding='utf-8'))
 if len(official)!=len(rows):errors.append({'error':'official HarnessIR manifest count differs'})
 for q in official:
  p=pathlib.Path(q['lq']).resolve()
  if not p.is_relative_to(root):errors.append({'path':q['lq'],'error':'official manifest points outside current data root; regenerate after moving'})
  elif not p.is_file():errors.append({'path':q['lq'],'error':'official manifest actual lq path missing'})
  if set(q)!={'lq','prompt'}:errors.append({'error':'unexpected fields in official inference-only manifest'})
 report={'data_root':str(root),'main_inputs':len(rows),'main_scene_ids':len(rows),'scene_independence_pending':sum('not confirmed independent' in r.get('scene_independence','') for r in rows),'gt_files':sum(r['has_gt'] for r in rows),'main_image_files':len(rows)+sum(r['has_gt'] for r in rows),'person_mask_files':sum(bool(r.get('mask_path')) for r in rows),'supplementary_records':len(supp),'all_image_files_checked':checked,'source_counts':dict(collections.Counter(r['dataset'] for r in rows)),'errors':errors,'passed':not errors,'checks':['actual paths within data root','full image decode','SHA256','byte sizes','pixel dimensions','PNG bit depth','unique scene IDs/input hashes','run queue identities/no GT fields'],'does_not_confirm':['model performance','pixel-level GT registration','original-author identity for unverified mirrors','independent image-photo licenses for unknown sources']}
 (root/'verification_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');return report
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('root',nargs='?',default=str(pathlib.Path(__file__).resolve().parent.parent));args=parser.parse_args();report=validate(args.root);print(json.dumps(report,ensure_ascii=False,indent=2));sys.exit(0 if report['passed'] else 1)
