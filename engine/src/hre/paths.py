"""Portable, case relative paths. No symlinks or filesystem device aliases."""
from pathlib import Path
import os
import re
import stat
from uuid import uuid4
from .models import HREError

_DEVICE=re.compile(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]|CONIN\$|CONOUT\$)(?:\.|$)', re.I)
_ID=re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]*$')

def _no_link(path):
    try:s=path.lstat()
    except FileNotFoundError:return
    if stat.S_ISLNK(s.st_mode) or (getattr(s,'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400)):
        raise HREError('unsafe_path',f'Symlink/reparse point: {path}')

def safe_path(root:Path,relative:str,must_exist:bool=False)->Path:
    root=Path(root).absolute()
    if not isinstance(relative,str) or not relative or '\\' in relative or ':' in relative or relative.startswith('/'):
        raise HREError('unsafe_path',f'Not a portable relative path: {relative!r}')
    parts=relative.split('/')
    if any(p in ('','.','..') or p.endswith((' ','.')) or _DEVICE.match(p) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_. -]*',p) for p in parts):
        raise HREError('unsafe_path',f'Unsafe path segment: {relative!r}')
    # Check ancestors too, so a symlinked root cannot create a false security boundary.
    for parent in reversed((root,*root.parents)):_no_link(parent)
    path=root
    for part in parts:path=path/part;_no_link(path)
    if not path.resolve().is_relative_to(root.resolve()):raise HREError('unsafe_path','Path escaped case root')
    if must_exist and not path.exists():raise HREError('missing_file',relative)
    return path

def make_id(prefix:str)->str:
    if not _ID.fullmatch(prefix) or _DEVICE.match(prefix):raise HREError('unsafe_id',prefix)
    return f'{prefix}_{uuid4().hex}'
