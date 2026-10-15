"""Actual current-session file capability probe. No image editing is claimed."""
from pathlib import Path
from hir_manual.capabilities import complete_probe
from hir_manual.storage import read_json,write_json,now,atomic_write,sha256_file
root=Path(__file__).resolve().parents[2]
directory=Path(read_json(root/"runtime/latest_probe.json")["directory"])
probe=read_json(directory/"probe.json")
write_json(directory/"probe_response.json",{"nonce":probe["nonce"],"image_description":"Viewed with the session image viewer: white 160×120 canvas, solid red square at upper left and blue circle to its lower right.","writer":"Current local Work session; actual UI model name not captured","completed_at":now()})
caps=complete_probe(root,directory/"probe_response.json")
copied=directory/"copied_probe.png"
atomic_write(copied,(directory/"probe.png").read_bytes())
assert sha256_file(copied)==sha256_file(directory/"probe.png")
caps.update(role_dispatch="unsupported",dispatcher_mechanism=None,image_edit="untested",image_save="untested",local_image_copy="supported",local_image_copy_scope="Existing PNG copied and rehashed locally; no ChatGPT generated-image save tested")
caps["evidence_files"].append(str(copied))
write_json(root/"runtime/capabilities.json",caps)
print(caps)
