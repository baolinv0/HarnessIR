"""Export the official HarnessIR manifest format, with no GT or oracle labels."""
import pathlib,json,argparse
def export(root):
 root=pathlib.Path(root).resolve();rows=[json.loads(x) for x in (root/'run_queue.jsonl').read_text(encoding='utf-8').splitlines()]
 out=[{'lq':str(root/r['image_path']),'prompt':r['request']} for r in rows]
 path=root/'harness_manifest_no_gt.json';path.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8');return path
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('root',nargs='?',default=str(pathlib.Path(__file__).resolve().parent.parent));a=p.parse_args();print(export(a.root))
