"""Publish validated SAM3.1 alternatives without masquerading as v1.1 cache.

The existing Evidence Manager only consumes normalized v1.1 manifests. These
native NPZ records are separately named, source/contract bound and readable by
the standalone test; no old SAM3 profile or case is upgraded implicitly.
"""
from pathlib import Path
import argparse,json,shutil,uuid,csv,sys,zipfile
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'engine/colab'))
import sam3_handoff as h

def publish(delivery,cache_root):
    delivery=delivery.resolve();cache_root=cache_root.resolve()
    validation=h.read(delivery/'local_validation.json');run=h.read(delivery/'run.json')
    assert validation['strictly_validated'] and run['model']=='SAM3.1' and not run['formal_eligible']
    assert run['contract_sha256']=='489d609effd25eb58204fb7b614756b072c60850785d56586b70c18c5f06df23'
    assert h.digest(run['contract'])==run['contract_sha256']
    rows=h.read(delivery/'inputs.json')['images']
    with zipfile.ZipFile(ROOT/'runtime/sam3_colab/uploads/847d740a9d1c0c47/harnessir_sam3_inputs20.zip') as archive:
        assert h.read(delivery/'inputs.json')==json.loads(archive.read('inputs.json'))
    destination=cache_root/'alternatives/SAM31'/run['contract_sha256']/run['run_id']
    assert destination.is_relative_to(cache_root)
    if destination.exists():
        ready=h.read(destination/'raw_ready.json')
        assert ready['contract_sha256']==run['contract_sha256']
        for entry in ready['files']:
            assert h.sha(h.under(destination,entry['path']))==entry['sha256']
        return dict(status='existing_verified',directory=str(destination),count=ready['count'])
    temporary=destination.parent/('_tmp_'+uuid.uuid4().hex);temporary.mkdir(parents=True)
    records=[];files=[]
    def copy(source,relative):
        target=h.under(temporary,relative);target.parent.mkdir(parents=True,exist_ok=True)
        with source.open('rb') as reader,target.open('wb') as writer:shutil.copyfileobj(reader,writer,8*1024**2)
        assert h.sha(source)==h.sha(target)
        files.append(dict(path=relative,sha256=h.sha(target)))
    for name in ['run.json','inputs.json','prompt_set.json','deployment.json','pilot_review.json','local_validation.json']:
        if (delivery/name).is_file():copy(delivery/name,name)
    for row in rows:
        metadata=h.read(delivery/'images'/f"{row['image_id']}.json")
        assert metadata['status'] in ('ok','empty')
        assert metadata['process_released'] and metadata['checkpoint_strict_load']
        assert metadata['canonical_sha256']==row['canonical_sha256']
        h.validate_result(delivery,row,run['contract_sha256'])
        for suffix in ['.json','.npz']:copy(delivery/'images'/(row['image_id']+suffix),'images/'+row['image_id']+suffix)
        records.append(dict(image_id=row['image_id'],raw_cache_key=h.digest(dict(original_sha256=row['original_sha256'],canonical_sha256=row['canonical_sha256'],canonicalizer_version=row['canonicalizer_version'],contract_sha256=run['contract_sha256'])),
            original_sha256=row['original_sha256'],canonical_sha256=row['canonical_sha256'],width=row['width'],height=row['height'],model=run['model'],checkpoint_sha256=run['checkpoint_sha256'],weight_revision=run['contract']['weight_revision'],
            status=metadata['status'],json_path='images/'+row['image_id']+'.json',npz_path='images/'+row['image_id']+'.npz',elapsed_seconds=metadata['elapsed_seconds'],peak_rss_mib=metadata['peak_rss_mb'],peak_gpu_mib=metadata['peak_gpu_memory_mb']))
        h.validate_result(temporary,row,run['contract_sha256'])
    h.write(temporary/'manifest.json',dict(kind='validated_native_SAM31_alternative_cache',formal_eligible=False,production_v1_1_registered=False,contract=run['contract'],records=records))
    with (temporary/'processing_status.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(records[0]));writer.writeheader();writer.writerows(records)
    for name in ['manifest.json','processing_status.csv']:files.append(dict(path=name,sha256=h.sha(temporary/name)))
    h.write(temporary/'raw_ready.json',dict(kind='raw_only_not_production_v1_1',contract_sha256=run['contract_sha256'],count=len(records),files=files))
    temporary.rename(destination)
    return dict(status='published_raw_alternative',directory=str(destination),count=len(records),production_v1_1_registered=False)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--delivery',type=Path,required=True);p.add_argument('--cache-root',type=Path,default=ROOT/'Data/annotations/cache');args=p.parse_args()
    print(json.dumps(publish(args.delivery,args.cache_root)))
