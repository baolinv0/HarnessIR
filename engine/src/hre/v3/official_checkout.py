"""Import audited helpers from a pinned, local upstream checkout.

This module never clones a repository or installs a package.  The caller names
the upstream modules it needs, and the temporary import context prevents an
unrelated installed ``agent`` or ``pe_core`` package from supplying those names.
"""
from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
import importlib
from pathlib import Path
import re
import subprocess
import sys
from threading import RLock
from typing import Iterator, Sequence

from ..models import HREError


_IMPORT_LOCK = RLock()


def _git(root: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            stdin=subprocess.DEVNULL, capture_output=True, check=True,
            text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise HREError("upstream_checkout_invalid", "Could not inspect the local upstream checkout") from exc
    return result.stdout.strip()


def verified_checkout(config: dict, required_paths: Sequence[str]) -> tuple[Path, dict]:
    """Validate a local checkout and the tracked files used by this adapter.

    ``required_paths`` may contain files or package directories.  The selected
    trees must have no tracked changes or untracked Python files.  Generated
    bytecode and unrelated experimental files elsewhere in the checkout do not
    invalidate the adapter's source identity.
    """
    path, revision = config.get("upstream_path"), config.get("upstream_revision")
    if not isinstance(path, str) or not path or not Path(path).is_absolute():
        raise HREError("upstream_checkout_invalid", "upstream_path must be an absolute local checkout path")
    root = Path(path).resolve()
    if not root.is_dir() or not isinstance(revision, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", revision):
        raise HREError("upstream_checkout_invalid", "A local checkout and pinned 40-character upstream_revision are required")
    if _git(root, "rev-parse", "HEAD").lower() != revision.lower():
        raise HREError("upstream_revision_mismatch", "The local upstream HEAD differs from upstream_revision")
    if not required_paths:
        raise HREError("upstream_checkout_invalid", "Name the upstream files or packages used by this adapter")
    selected: list[str] = []
    for relative in required_paths:
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise HREError("upstream_checkout_invalid", "Upstream source paths must be relative to the checkout")
        target = (root / relative).resolve()
        if not target.is_relative_to(root) or not target.exists():
            raise HREError("upstream_source_missing", "A required upstream source path is missing or leaves the checkout")
        selected.append(relative)
    tracked = _git(root, "ls-files", "--", *selected).splitlines()
    if not tracked:
        raise HREError("upstream_source_untracked", "The requested upstream implementation is not tracked by this checkout")
    for relative in selected:
        if not any(name == relative or name.startswith(relative.rstrip("/") + "/") for name in tracked):
            raise HREError("upstream_source_untracked", "A required upstream source path is not tracked")
    if _git(root, "diff", "--name-only", "HEAD", "--", *selected):
        raise HREError("upstream_source_modified", "The required upstream sources differ from their pinned commit")
    untracked = _git(root, "ls-files", "--others", "--exclude-standard", "--", *selected).splitlines()
    if any(Path(name).suffix in {".py", ".pyi"} for name in untracked):
        raise HREError("upstream_source_untracked", "Untracked Python code exists in the imported upstream package")
    hashes = {}
    for relative in tracked:
        target = (root / relative).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            raise HREError("upstream_source_missing", "A tracked upstream source file is unavailable")
        hashes[relative] = sha256(target.read_bytes()).hexdigest()
    return root, {
        "upstream_path": str(root), "upstream_revision": revision.lower(),
        "source_sha256": hashes,
    }


@contextmanager
def import_context(root: Path, prefixes: Sequence[str], search_paths: Sequence[str] = (".",)) -> Iterator[None]:
    """Temporarily import selected module prefixes from a verified checkout.

    Keep the context active while an upstream helper makes lazy imports.  Only
    the selected prefixes are isolated; shared dependencies such as torch are
    left intact.  A lock also prevents concurrent temporary sys.path changes.
    """
    root = Path(root).resolve()
    prefix_tuple = tuple(prefixes)
    if not prefix_tuple or any(not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", item) for item in prefix_tuple):
        raise HREError("upstream_import_invalid", "Valid upstream module prefixes are required")
    paths = []
    for relative in search_paths:
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_dir():
            raise HREError("upstream_import_invalid", "An upstream import path is missing or leaves the checkout")
        paths.append(str(path))

    def selected(name: str) -> bool:
        return any(name == prefix or name.startswith(prefix + ".") for prefix in prefix_tuple)

    with _IMPORT_LOCK:
        old_path = list(sys.path)
        saved = {name: module for name, module in sys.modules.items() if selected(name)}
        for name in saved:
            sys.modules.pop(name, None)
        sys.path[:0] = paths
        importlib.invalidate_caches()
        try:
            yield
            for name, module in tuple(sys.modules.items()):
                if selected(name) and getattr(module, "__file__", None):
                    if not Path(module.__file__).resolve().is_relative_to(root):
                        raise HREError("upstream_import_mismatch", "An upstream module resolved outside its pinned checkout")
        finally:
            for name in tuple(sys.modules):
                if selected(name):
                    sys.modules.pop(name, None)
            sys.modules.update(saved)
            sys.path[:] = old_path
            importlib.invalidate_caches()
