"""Freeze twenty real inputs and inspection previews; never read references."""
import argparse
from pathlib import Path
from PIL import Image,ImageDraw
from hir_manual.cases import create_case
from hir_manual.storage import read_json,write_json,sha256_file,now,atomic_write
from hir_manual.tool_cli import read_manifest

ROOT=Path(__file__).resolve().parents[2]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection",required=True,type=Path)
    parser.add_argument("--out",required=True,type=Path)
    args=parser.parse_args()
    selection=read_json(args.selection)
    items=selection["items"]
    if len(items)!=20 or len({x["sample_id"] for x in items})!=20:
        raise ValueError("Exactly twenty distinct image IDs required")
    output=args.out.resolve()
    if not output.is_relative_to(ROOT/"runtime") or output.exists():
        raise ValueError("Choose a fresh output directory within runtime")
    rows={r["sample_id"]:r for r in read_manifest(ROOT/"Data/manifest.json")}
    hashes=set()
    for item in items:
        row=rows[item["sample_id"]]
        source=(ROOT/"Data"/row["input_path"]).resolve()
        if not source.is_relative_to((ROOT/"Data").resolve()) or sha256_file(source)!=row["input_sha256"]:
            raise ValueError("Source path/hash differs from dataset manifest")
        if row["input_sha256"] in hashes:
            raise ValueError("Duplicate original bytes in selected images")
        hashes.add(row["input_sha256"])
    output.mkdir(parents=True)
    write_json(output/"selection.json",selection)
    manifest={"created_at":now(),"selection_sha256":sha256_file(output/"selection.json"),"input_count":20,"scope":"purposeful_stratified_CPU_engineering_pilot; no population effect estimate","references_read":False,"images":[]}
    contact=Image.new("RGB",(1600,1360),(25,25,25))
    draw=ImageDraw.Draw(contact)
    for index,item in enumerate(items):
        row=rows[item["sample_id"]]
        source=ROOT/"Data"/row["input_path"]
        # Reuse the production canonicalizer. These are input containers, not
        # restoration cases; no diagnosis/evidence/edit result is manufactured.
        state=create_case(output/"input_containers",source,"Input-only preparation for twenty-photo visual inspection",{"auto_local_tools":False,"branch_type":"input_preparation"})
        directory=output/"input_containers/cases"/state.case_id
        canonical=directory/"input/canonical.png"
        metadata=read_json(directory/"input/metadata.json")
        with Image.open(canonical) as photo:
            photo.load()
            preview=photo.copy()
            preview.thumbnail((1000,1000))
            target=output/"previews"/(item["sample_id"]+".png")
            target.parent.mkdir(exist_ok=True)
            preview.save(target)
            tile=photo.copy()
            tile.thumbnail((304,286))
            x,y=(index%5)*320,(index//5)*340
            contact.paste(tile,(x+(320-tile.width)//2,y+28+(286-tile.height)//2))
            draw.text((x+6,y+5),f"{index+1:02d} {item['sample_id']}",fill="white")
            draw.text((x+6,y+316),item["stratum"],fill=(200,200,200))
        header=source.read_bytes()[:26]
        png_depth=header[24] if header.startswith(b"\x89PNG\r\n\x1a\n") else None
        conversion_note="Original PNG bit depth >8; Pillow decodes colour PNG to RGB8 display values for the production canonicalizer. Original bytes retained; no 16-bit fidelity/metric claim." if png_depth and png_depth>8 else None
        manifest["images"].append({**item,"input_path":str(source.resolve()),"original_sha256":metadata["original_sha256"],"canonical_path":str(canonical),"canonical_sha256":metadata["canonical_sha256"],"canonicalizer_version":metadata.get("canonicalizer_version","hir_rgb8_exif_icc_v1"),"width":metadata["width"],"height":metadata["height"],"canonical_operations":metadata["operations"],"source_png_bit_depth":png_depth,"canonical_display_note":conversion_note,"inspection_preview":str(target),"stage":"awaiting_visual_diagnosis","tool_inference_status":"not_run","editor_generation_count":0,"restoration_success":None})
        write_json(output/"manifest.json",manifest)
    contact.save(output/"contact_sheet_inputs_only.png")
    write_json(output/"preparation_result.json",{"passed":True,"actual_inputs":20,"unique_original_hashes":20,"all_original_hashes_match":True,"canonicalization":"production RGB8 EXIF/ICC without spatial resize","previews_only":"thumbnails for viewing; not model inputs or restored images","generated_restorations":0})
    print({"directory":str(output),"images":20,"all_original_hashes_match":True,"restoration_outputs":0})


if __name__=="__main__":
    main()
