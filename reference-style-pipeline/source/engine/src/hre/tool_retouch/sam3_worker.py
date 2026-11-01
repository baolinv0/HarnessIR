"""Production CPU bridge to existing SAM3. Only invoked by explicit segmentation config.

No installation or model download. All socket connects are denied in this worker;
missing local tokenizer/weights fail rather than fetching remote assets.
"""
from pathlib import Path
import sys

def main():
    import socket
    def offline(*args,**kwargs):raise RuntimeError('SAM3 worker network access disabled; provision local assets separately')
    socket.socket.connect=offline;socket.socket.connect_ex=offline;socket.create_connection=offline
    from PIL import Image
    from hre.storage import read_json
    from hre.tool_retouch.color import require
    import importlib.metadata
    root=Path(sys.argv[1]).resolve();request=read_json(root/'request.json')
    require(Path(request['checkpoint']).is_file(),'local checkpoint required')
    require(importlib.metadata.version('ultralytics')==request['producer_version'],'ultralytics version mismatch')
    repo=Path(__file__).resolve().parents[4];sys.path.insert(0,str(repo))
    from harness import settings
    settings.SAM3_CKPT=request['checkpoint'];settings.SAM3_LABELS=request['labels']
    settings.SAM3_CONF=request['conf'];settings.SAM3_IOU=request['iou'];settings.SAM3_IMGSZ=request['imgsz']
    from harness.perception.segment import run_segment
    with Image.open(root/'input.png') as image:result=run_segment(image.convert('RGB'),root,labels=request['labels'])
    require(result is not None and result.reliable,'SAM3 returned missing/unreliable segmentation')

if __name__=='__main__':main()
