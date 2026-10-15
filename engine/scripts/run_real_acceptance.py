"""Sequential real-photo probes. Resource waits stop the stage; no substitutes."""
import argparse
from pathlib import Path
from hir_manual.storage import read_json,write_json,now
from hir_manual.tool_cli import doctor
from hir_manual.cache import EvidenceCache

ROOT=Path(__file__).resolve().parents[2]
M1={"T2_FACE":["HC_WildDark_124","HC_Commons_002","HC_COZ_168"],"T1_OCR":["HC_ReWiTe_260_tele","HC_ReWiTe_336_tele","HC_ReWiTe_367_tele"]}
M2={"T3_DEPTH":["HC_ReWiTe_164_tele"],"T4_SEGMENTATION":["HC_Commons_008"]}
PILOT=["HC_WildDark_124","HC_RAIM_Phase1_011","HC_Commons_003","HC_COZ_155","HC_COZ_168","HC_ReWiTe_260_tele","HC_ReWiTe_336_tele","HC_ReWiTe_367_tele","HC_ReWiTe_164_tele","HC_Commons_008"]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage",choices=["M1","M2","prepare"],default="M1")
    args=parser.parse_args()
    rows={r["sample_id"]:r for r in read_json_list(ROOT/"Data/manifest.json")}
    directory=ROOT/"runtime/acceptance_v11"
    directory.mkdir(parents=True,exist_ok=True)
    write_json(directory/"pilot10.json",{"status":"prepared_not_run","formal_eligible":False,"images":[{"sample_id":i,"input_path":str((ROOT/"Data"/rows[i]["input_path"]).resolve()),"category":rows[i]["input_path"].split("/")[1:3]} for i in PILOT]})
    if args.stage=="prepare":
        return 0
    if args.stage=="M2":
        prior=directory/"M1.json"
        if not prior.exists() or not read_json(prior).get("passed"):
            write_json(directory/"M2.json",{"passed":False,"blocked":"M1 real acceptance must pass first","results":[]})
            return 3
    plan=M1 if args.stage=="M1" else M2
    report={"stage":args.stage,"started_at":now(),"scope":"real_photos_local_tools_only_CPU_interface_validation","formal_eligible":False,"passed":False,"results":[]}
    output=directory/(args.stage+".json")
    for tool,ids in plan.items():
        for image_id in ids:
            source=ROOT/"Data"/rows[image_id]["input_path"]
            try:
                result=doctor(ROOT,"cpu_probe_v1",tool,source)
                result.update(image_id=image_id,source_path=str(source),scope="real_photo")
                if result["ready"]:
                    cached=Path(result["cache_path"])
                    evidence=read_json(cached/"evidence.json")
                    result["outcome"]="empty_detection" if tool in ("T1_OCR","T2_FACE") and not evidence["detections"] else "evidence_returned"
                    result["cache_reuse_validated"]=EvidenceCache(ROOT/"Data/annotations/cache").lookup(read_json(cached/"contract.json"))==cached
                    result["detection_count"]=len(evidence["detections"])
                else:
                    result["outcome"]="resource_wait" if result["worker"].get("status")=="resource_wait" else "model_run_failed"
            except (ValueError,OSError,KeyError) as error:
                result={"tool":tool,"image_id":image_id,"ready":False,"outcome":"model_run_failed","error":str(error)}
            report["results"].append(result)
            write_json(output,report)
            if not result["ready"]:
                report["blocked"]=result["outcome"]
                report["stopped_at"]=now()
                write_json(output,report)
                print(report)
                return 3
    report["passed"]=True
    report["completed_at"]=now()
    report["visual_checks_required"]="Inspect actual faces/OCR/near-far/masks/legends before declaring algorithm quality"
    write_json(output,report)
    print(report)
    return 0


def read_json_list(path):
    from hir_manual.tool_cli import read_manifest
    return read_manifest(path)


if __name__=="__main__":
    raise SystemExit(main())
