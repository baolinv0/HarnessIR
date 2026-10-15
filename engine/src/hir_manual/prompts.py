import json
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from .protocol import DESIGN_DIR


def render_prompt(role: str, context: dict, design_dir: Path = DESIGN_DIR) -> str:
    environment = Environment(loader=FileSystemLoader(str(design_dir / "prompts")), undefined=StrictUndefined, autoescape=False, keep_trailing_newline=True)
    rendered = environment.get_template(f"{role}.j2").render(**context)
    if "{{" in rendered or "{%" in rendered or "{#" in rendered:
        raise ValueError("Unresolved template markers; task will not be issued")
    return rendered


def encoded(value) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False)
