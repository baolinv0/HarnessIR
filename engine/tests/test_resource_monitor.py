import os
import sys
import psutil
import pytest
from hir_manual.resource_monitor import monitor_process
from hir_manual.tool_registry import load_profile


def profile(timeout=2):
    p = load_profile()
    p.min_available_memory_mb = 0
    p.abort_available_memory_mb = 0
    p.tools["_active"] = {"timeout_seconds": timeout}
    p.memory_sample_interval_ms = 20
    return p


def test_low_memory_does_not_start_process(tmp_path):
    p = profile()
    p.min_available_memory_mb = 2048
    result = monitor_process([sys.executable, "-c", "raise RuntimeError('must not start')"], tmp_path, p, tmp_path/"logs", memory_reader=lambda: 100)
    assert result.status == "resource_wait" and result.pid is None


def test_timeout_kills_and_releases(tmp_path):
    result = monitor_process([sys.executable, "-c", "import time;time.sleep(20)"], tmp_path, profile(1), tmp_path/"logs")
    assert result.error_code == "timeout" and result.process_released


def test_oom_tree_is_terminated(tmp_path):
    p = profile()
    p.max_worker_rss_mb = 1
    result = monitor_process([sys.executable, "-c", "import time;buffer=bytearray(8*1024*1024);time.sleep(5)"], tmp_path, p, tmp_path/"logs")
    assert result.error_code == "oom" and result.process_released


def test_fixed_thread_environment(tmp_path):
    result = monitor_process([sys.executable, "-c", "import os;assert os.environ['OMP_NUM_THREADS']=='2';assert os.environ['HF_HUB_OFFLINE']=='1';assert os.environ['YOLO_AUTOINSTALL']=='false'"], tmp_path, profile(), tmp_path/"logs")
    assert result.status == "completed"


def test_surviving_child_is_cleaned_and_reported(tmp_path):
    code = "import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']); open('child.pid','w').write(str(p.pid)); time.sleep(.3)"
    result = monitor_process([sys.executable,"-c",code],tmp_path,profile(5),tmp_path/"logs")
    assert result.status == "failed" and result.process_released
    assert not psutil.pid_exists(int((tmp_path/"child.pid").read_text()))


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object containment")
def test_immediate_parent_exit_releases_unsampled_child(tmp_path):
    p = profile(5)
    p.memory_sample_interval_ms = 1000
    code = "import subprocess,sys; p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']); open('child.pid','w').write(str(p.pid))"
    child_pid = None
    try:
        result = monitor_process([sys.executable,"-c",code], tmp_path, p, tmp_path/"logs")
        child_pid = int((tmp_path/"child.pid").read_text())
        assert result.status == "failed" and result.error_code == "worker_error"
        assert result.process_released and not psutil.pid_exists(child_pid)
    finally:
        if child_pid and psutil.pid_exists(child_pid):
            psutil.Process(child_pid).kill()


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object containment")
def test_timeout_releases_child_and_grandchild(tmp_path):
    grandchild = "import time;time.sleep(30)"
    child = f"import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c',{grandchild!r}]); open('grandchild.pid','w').write(str(p.pid)); time.sleep(30)"
    parent = f"import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c',{child!r}]); open('child.pid','w').write(str(p.pid)); time.sleep(30)"
    descendants = []
    try:
        result = monitor_process([sys.executable,"-c",parent], tmp_path, profile(5), tmp_path/"logs")
        descendants = [int((tmp_path/name).read_text()) for name in ("child.pid", "grandchild.pid")]
        assert result.error_code == "timeout" and result.process_released
        assert all(not psutil.pid_exists(pid) for pid in descendants)
    finally:
        for pid in descendants:
            if psutil.pid_exists(pid):
                psutil.Process(pid).kill()


@pytest.mark.skipif(os.name != "nt", reason="Windows suspended worker fail-closed behavior")
def test_job_assignment_failure_never_executes_worker(tmp_path, monkeypatch):
    from hir_manual.windows_job import WindowsJob
    def unavailable(self, process):
        raise OSError("test assignment rejected")
    monkeypatch.setattr(WindowsJob, "assign_and_resume", unavailable)
    result = monitor_process([sys.executable,"-c","open('must_not_run','w').write('executed')"], tmp_path, profile(), tmp_path/"logs")
    assert result.status == "failed" and result.error_code == "worker_error"
    assert result.process_released and not (tmp_path/"must_not_run").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows job release accounting")
def test_unconfirmed_job_release_is_not_reported_released(tmp_path, monkeypatch):
    from hir_manual.windows_job import WindowsJob
    monkeypatch.setattr(WindowsJob, "wait_empty", lambda self, timeout=5: False)
    result = monitor_process([sys.executable,"-c","pass"], tmp_path, profile(), tmp_path/"logs")
    assert result.status == "failed" and not result.process_released
