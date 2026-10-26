"""Read-only views of recorded experiments; no model invocation or case mutation."""
import json
from pathlib import Path
import re

from .contracts import require


def experiment_root(workbench):
    return workbench.root.parent / "retouch_experiments"


def directory(workbench, identifier):
    require(isinstance(identifier, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", identifier), "experiment_id", "无效实验 ID")
    root = experiment_root(workbench).resolve()
    folder = (root / identifier).resolve()
    require(folder.is_relative_to(root) and folder.is_dir(), "experiment_missing", "实验不存在")
    return folder


def listing(workbench):
    root = experiment_root(workbench)
    items = []
    for path in sorted(root.glob("*/manifest.json"), key=lambda path: path.stat().st_mtime, reverse=True):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", path.parent.name):
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        items.append({key: data.get(key) for key in ("id", "title", "status", "created_at", "calls_submitted")})
    return {"experiments": items}


def detail(workbench, identifier):
    folder = directory(workbench, identifier)
    data = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    for key, filename in (("measurements", "measurements.json"), ("regions_v2", "evidence/regions_v2.json"), ("reassessment_v2", "evidence/reassessment_v2.json")):
        path = folder / filename
        if path.is_file():
            data[key] = json.loads(path.read_text(encoding="utf-8"))
    return data


def asset(workbench, identifier, name):
    folder = directory(workbench, identifier) / "assets"
    require(isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,100}\.png", name), "experiment_asset", "无效实验图像")
    path = (folder / name).resolve()
    require(path.is_relative_to(folder.resolve()) and path.is_file(), "experiment_asset", "实验图像不存在")
    return path
