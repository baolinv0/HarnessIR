"""Package only explicit engine/design/worker/model assets, never credentials."""
import argparse
from pathlib import Path
import tarfile

ROOT=Path(__file__).resolve().parents[2]


def package(out):
    paths=[]
    for folder in ['engine/src','engine/scripts','Design_v1_20261012','Design_v1_1_20261012','preprocessing/workers','preprocessing/adapters']:
        paths.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix not in ('.pyc','.zip'))
    paths += [ROOT/'engine/pyproject.toml',ROOT/'preprocessing/worker_main.py',ROOT/'preprocessing/prepare_models.py',ROOT/'preprocessing/prepare_gpu_models.py']
    for folder in ['models/scrfd','models/ppocrv6_medium','models/depth_anything_v2_small/source']:
        paths.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    out=Path(out).resolve();out.parent.mkdir(parents=True,exist_ok=True)
    temp=out.with_suffix(out.suffix+'.tmp')
    with tarfile.open(temp,'w') as archive:
        for path in sorted(set(paths)):
            if not path.is_file():raise ValueError('Missing deployment file: '+str(path))
            archive.add(path,arcname='project/'+path.relative_to(ROOT).as_posix())
    temp.replace(out)
    print(out)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True)
    package(p.parse_args().out)
