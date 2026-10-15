import pytest
import subprocess
import sys
from filelock import Timeout
from hir_manual.storage import atomic_write, resolve_case_path, writer_lock


@pytest.mark.parametrize("path", ["../escape", "C:/evil", "/evil", "a\\b", "a/../b", "a:stream", "a//b"])
def test_path_escape_rejected(tmp_path, path):
    with pytest.raises(ValueError):
        resolve_case_path(tmp_path, path)


def test_atomic_and_no_partial(tmp_path):
    path = tmp_path / "result.json"
    atomic_write(path, b"old")
    atomic_write(path, b"complete")
    assert path.read_bytes() == b"complete"
    assert not list(tmp_path.glob("*.tmp"))


def test_single_writer(tmp_path):
    with writer_lock(tmp_path):
        with pytest.raises(Timeout):
            with writer_lock(tmp_path):
                pass


def test_second_process_cannot_write(tmp_path):
    script = "from pathlib import Path;from hir_manual.storage import writer_lock;from filelock import Timeout;import sys\ntry:\n with writer_lock(Path(sys.argv[1])): sys.exit(3)\nexcept Timeout: sys.exit(0)"
    with writer_lock(tmp_path):
        result = subprocess.run([sys.executable, "-c", script, str(tmp_path)], capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr.decode(errors="replace")


def test_junction_cannot_escape_case(tmp_path):
    case_dir = tmp_path / "case"
    target = tmp_path / "outside"
    case_dir.mkdir()
    target.mkdir()
    link = case_dir / "junction"
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, timeout=15)
    if result.returncode:
        pytest.skip("Junction creation unavailable on this test filesystem")
    with pytest.raises(ValueError):
        resolve_case_path(case_dir, "junction/escape.json")
