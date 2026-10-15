"""Bind an unbound result archive to an independently frozen local export.

No contracts are taken from the results as authority. The existing strict bundle
importer performs all source/asset/geometry checks after this metadata binding.
"""
import argparse
import json
from pathlib import Path
import sys
import zipfile
import shutil

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'engine/src'))
from hir_manual.storage import read_json
from hir_manual.bundles import import_cache_bundle


def bind(source,ledger,target):
    frozen=read_json(ledger)
    expected={(r['tool_id'],r['cache_key']):r for r in frozen['entries']}
    seen=set()
    with zipfile.ZipFile(source) as archive:
        infos=archive.infolist()
        if len(infos)>100000 or sum(x.file_size for x in infos)>8*1024**3:
            raise ValueError('Archive exceeds strict import budget')
        if len({x.filename.casefold() for x in infos})!=len(infos):raise ValueError('Duplicate archive entries')
        index=json.loads(archive.read('bundle.json'))
        if index.get('protocol_version')!='1.1' or index.get('bundle_kind')!='unbound_cache_results':
            raise ValueError('Expected an explicitly unbound result archive')
        for row in index['entries']:
            identity=(row['tool_id'],row['cache_key'])
            if identity in seen or identity not in expected:raise ValueError('Unrequested/duplicate result')
            wanted=expected[identity];seen.add(identity)
            if row['contract']!=wanted['contract'] or row['image_id']!=wanted['image_id'] or row['input_path']!=wanted['input_path']:
                raise ValueError('Result differs from independently frozen local source/contract')
        index.update(bundle_kind='cache_results',bundle_id=frozen['bundle_id'])
        temp=Path(target).with_suffix('.zip.tmp')
        with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as output:
            for info in infos:
                if info.filename=='bundle.json':continue
                # Do not extract before the strict importer checks path safety.
                with archive.open(info) as incoming,output.open(info,'w',force_zip64=True) as outgoing:
                    shutil.copyfileobj(incoming,outgoing,1024*1024)
            output.writestr('bundle.json',json.dumps(index,ensure_ascii=False,allow_nan=False))
        temp.replace(target)
    return target


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True);p.add_argument('--ledger',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True);p.add_argument('--import-root',type=Path)
    a=p.parse_args();bind(a.source,a.ledger,a.out)
    if a.import_root:
        result=import_cache_bundle(a.out,a.import_root/'Data/annotations/cache')
        print(json.dumps(result.model_dump(),ensure_ascii=False))
        raise SystemExit(3 if result.rejected else 0)
    print(a.out)
