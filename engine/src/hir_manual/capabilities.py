"""Evidence-based probes. Absence of a dispatcher never becomes an API fallback."""
import secrets
from pathlib import Path
from PIL import Image, ImageDraw

from .models import ImportResult
from .storage import atomic_write, now, read_json, sha256_file, write_json


def prepare_probe(root: Path):
    root = Path(root)
    directory = root / "runtime" / "probes" / secrets.token_hex(8)
    directory.mkdir(parents=True, exist_ok=False)
    nonce = secrets.token_hex(24)
    image = Image.new("RGB", (160, 120), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, 70, 70), fill="red")
    draw.ellipse((85, 35, 150, 100), fill="blue")
    image.save(directory / "probe.png")
    probe = {"nonce": nonce, "image": str(directory / "probe.png"), "created_at": now(), "response_path": str(directory / "probe_response.json"), "scope": "local Work/Codex session; distinct from desktop image editing"}
    write_json(directory / "probe.json", probe)
    atomic_write(directory / "task.txt", (f"Read {directory / 'probe.json'} and inspect {directory / 'probe.png'} with an image viewer. Write probe_response.json at the exact response_path with nonce, image_description, writer and completed_at. Do not infer image content from filenames. Do not alter nonce.\n").encode("utf-8"))
    write_json(root / "runtime" / "latest_probe.json", {"directory": str(directory)})
    return probe


def complete_probe(root: Path, response: Path):
    root = Path(root)
    probe = read_json(Path(response).parent / "probe.json")
    result = read_json(Path(response))
    if result.get("nonce") != probe["nonce"] or len(result.get("image_description", "")) < 20:
        raise ValueError("Probe nonce/visual description invalid")
    if Path(response).resolve() != Path(probe["response_path"]).resolve():
        raise ValueError("Probe was not written to the requested local path")
    from .protocol import parse_time
    if parse_time(result["completed_at"]) < parse_time(probe["created_at"]):
        raise ValueError("Probe timestamps invalid")
    target = root / "runtime" / "capabilities.json"
    caps = read_json(target) if target.exists() else {"local_read_write": "untested", "role_dispatch": "untested", "image_edit": "untested", "image_save": "untested", "observed_model_display_name": None, "backend_version": None, "dispatcher_mechanism": None, "evidence_files": []}
    caps.update(example_only=False, tested_on_user_device=True, local_read_write="supported", tested_at=now())
    caps["local_read_write_scope"] = "Current local Work/Codex session only; ChatGPT image editor file access not established"
    caps["evidence_files"] = list(dict.fromkeys(caps["evidence_files"] + [str(response), str(Path(response).parent / "probe.png")]))
    caps["probe_response_sha256"] = sha256_file(response)
    write_json(target, caps)
    return caps


def dispatch(controller, case_id):
    request = controller.current_task(case_id)
    if request is None:
        return ImportResult(accepted=False, code="no_pending_task", message="当前无待执行任务")
    return ImportResult(accepted=False, code="unsupported", message="当前未配置且未验证受支持的 ChatGPT 桌面角色派发桥。请复制当前任务到指定角色会话，随后导入 JSON / 图片。")
