"""One frozen JSON/hash contract and strict, offline JSON Schema registry."""
from datetime import datetime, timezone
from functools import lru_cache
from hashlib import sha256
from importlib.resources import files
from pathlib import Path
import json
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from pydantic import BaseModel, ConfigDict

SCHEMA_VERSION = 'ref_enhance_v1'

class HREError(Exception):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(f'{code}: {message}')

class ImportResult(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    accepted: bool
    code: str
    message: str = ''
    duplicate: bool = False

class GateResult(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    status: str
    observations: dict

def canonical_json(value) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')

def sha256_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()

def file_sha256(path: Path) -> str:
    h=sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024*1024), b''): h.update(chunk)
    return h.hexdigest()

def request_hash(data: dict) -> str:
    return sha256_bytes(canonical_json({k:v for k,v in data.items() if k!='request_sha256'}))

def config_hash(data: dict) -> str:
    return sha256_bytes(canonical_json({k:v for k,v in data.items() if k!='config_sha256'}))

def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')

@lru_cache(maxsize=1)
def _schemas():
    root=files('hre').joinpath('resources/schemas')
    docs={p.name:json.loads(p.read_text('utf-8')) for p in root.iterdir() if p.name.endswith('.json')}
    registry=Registry().with_resources((name,Resource.from_contents(doc)) for name,doc in docs.items())
    return docs,registry

def validate_schema(name: str, data: dict, fragment: str='') -> None:
    if not name.endswith('.schema.json'): name=name.removesuffix('.json')+'.schema.json'
    docs,registry=_schemas()
    if name not in docs:raise HREError('unknown_schema',name)
    schema=docs[name]
    try:
        if fragment:
            pointer=fragment.removeprefix('#').strip('/')
            for part in pointer.split('/'):schema=schema[part.replace('~1','/').replace('~0','~')]
        validator=Draft202012Validator(schema,registry=registry,format_checker=FormatChecker())
        error=next(iter(validator.iter_errors(data)),None)
        if error:raise HREError('schema_error', f'{name}{fragment}: {error.json_path}: {error.message}')
        canonical_json(data)
    except HREError:raise
    except Exception as e:raise HREError('schema_error',f'{name}{fragment}: {e}') from e
