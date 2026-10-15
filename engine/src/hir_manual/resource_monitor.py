"""One isolated child, fixed argv, measured process-tree memory and termination."""
import os
import subprocess
import time
from pathlib import Path
import psutil
from filelock import FileLock, Timeout
from .storage import write_json, now, read_json, sha256_file
from .tool_models import WorkerResult
from .tool_registry import check_entry
from .windows_job import WindowsJob


def available_mb():
    return psutil.virtual_memory().available / 1024**2


def terminate_tree(process):
    try:
        parent = psutil.Process(process.pid)
        children = parent.children(recursive=True)
        for child in reversed(children):
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        parent.terminate()
        _, alive = psutil.wait_procs([*children, parent], timeout=2)
        for item in alive:
            try:
                item.kill()
            except psutil.NoSuchProcess:
                pass
        psutil.wait_procs(alive, timeout=2)
    except psutil.NoSuchProcess:
        pass
    process.wait(timeout=5)


def wait_retired_windows_pids(identities, timeout=2):
    """Job exit accounting can precede removal from Windows' PID table.

    Only wait for the observed process incarnation. Never terminate a PID that
    could have been reused by another application.
    """
    deadline=time.monotonic()+timeout
    while True:
        remaining=[]
        for pid,created in identities.items():
            if not psutil.pid_exists(pid):
                continue
            try:
                current=psutil.Process(pid).create_time()
                if created is not None and current != created:
                    continue
            except psutil.NoSuchProcess:
                # pid_exists can briefly see a retired entry that cannot be
                # opened. Wait for that entry to disappear as well.
                pass
            remaining.append(pid)
        if not remaining:
            return True
        if time.monotonic()>=deadline:
            return False
        time.sleep(.01)


def monitor_process(argv, cwd, profile, log_dir, memory_reader=available_mb, environment=None):
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    if memory_reader() < profile.min_available_memory_mb:
        write_json(log_dir / "resource_guard.json", {"at": now(), "available_memory_mb": memory_reader(), "required_memory_mb": profile.min_available_memory_mb, "process_started": False})
        result = WorkerResult(status="resource_wait", error_code="insufficient_memory", message="Available RAM below frozen startup minimum", log_dir=str(log_dir), output_dir=str(Path(cwd) / "result"))
        write_json(log_dir / "result.json", result)
        return result
    env = os.environ.copy()
    env.update(environment or {})
    for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        env[key] = str(profile.cpu_threads)
    env.update(PYTHONUTF8="1", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1", YOLO_AUTOINSTALL="false", PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK="True")
    samples, peak, error, message = [], 0.0, None, None
    process, observed_children, job = None, {}, None
    released, phase = True, "isolation"
    with (log_dir / "stdout.txt").open("wb") as stdout, (log_dir / "stderr.txt").open("wb") as stderr:
        try:
            if os.name == "nt":
                job = WindowsJob()
            phase = "launch"
            flags = (subprocess.CREATE_NO_WINDOW | WindowsJob.CREATE_SUSPENDED) if job else 0
            process = subprocess.Popen([str(x) for x in argv], cwd=str(cwd), env=env, stdout=stdout, stderr=stderr, shell=False, creationflags=flags)
            released = False
            phase = "isolation"
            if job:
                job.assign_and_resume(process)
            phase = "running"
            root_process = psutil.Process(process.pid)
            while process.poll() is None:
                try:
                    if job:
                        family = []
                        for pid in job.process_ids():
                            try:
                                family.append(psutil.Process(pid))
                            except psutil.NoSuchProcess:
                                pass
                    else:
                        family = [root_process, *root_process.children(recursive=True)]
                    rss = 0.0
                    for member in family:
                        try:
                            if member.pid != process.pid:
                                observed_children[(member.pid, member.create_time())] = member
                            if member.is_running():
                                rss += member.memory_info().rss / 1024**2
                        except psutil.NoSuchProcess:
                            pass
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    rss = 0.0
                available = memory_reader()
                elapsed = (time.monotonic() - start) * 1000
                peak = max(peak, rss)
                samples.append({"elapsed_ms": elapsed, "tree_rss_mb": rss, "available_memory_mb": available})
                if rss > profile.max_worker_rss_mb:
                    error, message = "oom", "Sampled process-tree RSS exceeds frozen limit"
                elif available < profile.abort_available_memory_mb:
                    error, message = "oom", "Available system RAM below frozen abort floor"
                elif elapsed > profile.tools["_active"]["timeout_seconds"] * 1000:
                    error, message = "timeout", "Worker exceeded frozen timeout including model loading"
                if error:
                    break
                time.sleep(profile.memory_sample_interval_ms / 1000)
        except OSError as exc:
            error, message = "import_error" if phase == "launch" else "worker_error", str(exc)
        finally:
            if job is not None:
                retirement_identities={}
                try:
                    for pid in job.process_ids():
                        try:
                            retirement_identities[pid]=psutil.Process(pid).create_time()
                        except psutil.NoSuchProcess:
                            retirement_identities[pid]=None
                    # Accounting includes descendants missed by every RSS
                    # sample, including children whose parent already exited.
                    # Windows can signal the process handle before job exit
                    # accounting has drained. Allow that notification to settle
                    # before treating outstanding membership as a live orphan.
                    parent_exited = process is not None and process.poll() is not None
                    orphaned = parent_exited and not job.wait_empty(timeout=.2)
                    job.terminate()
                    released = job.wait_empty()
                    if process is not None and process.poll() is None:
                        # Assignment failure leaves a suspended, unassigned
                        # parent. It cannot execute; explicitly release it.
                        process.kill()
                    if process is not None:
                        process.wait(timeout=5)
                    released = released and (process is None or process.poll() is not None)
                    if orphaned and error is None:
                        error, message = "worker_error", "Worker exited with surviving children; controller terminated the Windows job"
                    if not released:
                        error, message = "worker_error", "Windows job still has active processes after termination"
                except (OSError, subprocess.TimeoutExpired) as exc:
                    released = False
                    error, message = "worker_error", "Cannot confirm worker job release: " + str(exc)
                finally:
                    try:
                        job.close()  # Kill-on-close also covers cleanup exceptions.
                    except OSError as exc:
                        released = False
                        error, message = "worker_error", "Cannot close worker containment job: " + str(exc)
                    if process is not None and process.poll() is None:
                        try:
                            process.kill()
                            process.wait(timeout=5)
                        except (OSError, subprocess.TimeoutExpired):
                            released = False
                    if process is not None and process.returncode is not None:
                        # Popen otherwise retains its process handle until this
                        # function returns. Close it before verifying PID-table
                        # retirement; all wait/poll operations are already done.
                        process._handle.Close()
                    if released and not wait_retired_windows_pids(retirement_identities):
                        released=False
                        error,message="worker_error","Windows process exit accounting completed but PID retirement was not confirmed"
            else:
                # Portable fallback: retain the existing psutil process-tree
                # cleanup. Windows correctness does not depend on sampling.
                try:
                    if process is not None and process.poll() is None:
                        terminate_tree(process)
                    survivors = []
                    for child in observed_children.values():
                        try:
                            if child.is_running():
                                survivors.append(child)
                                child.terminate()
                        except psutil.NoSuchProcess:
                            pass
                    if survivors:
                        _, alive = psutil.wait_procs(survivors, timeout=2)
                        for child in alive:
                            try:
                                child.kill()
                            except psutil.NoSuchProcess:
                                pass
                        _, remaining = psutil.wait_procs(alive, timeout=2)
                        if error is None:
                            error, message = "worker_error", "Worker exited with surviving children; controller cleaned up the process tree"
                    else:
                        remaining = []
                    released = (process is None or process.poll() is not None) and not remaining
                except (OSError, subprocess.TimeoutExpired) as exc:
                    released = False
                    error, message = "worker_error", "Cannot confirm worker tree release: " + str(exc)
    returncode = process.returncode if process else None
    if error is None and returncode != 0:
        error, message = "worker_error", "Worker exited unsuccessfully; inspect isolated stderr/error.json"
        error_path = Path(cwd) / "result" / "error.json"
        if error_path.exists():
            error_record = read_json(error_path)
            error = error_record.get("code", error)
            message = error_record.get("message", message)
    result = WorkerResult(status="completed" if error is None else "failed", error_code=error, message=message, returncode=returncode, elapsed_ms=(time.monotonic()-start)*1000, peak_rss_mb=peak, log_dir=str(log_dir), output_dir=str(Path(cwd)/"result"), pid=process.pid if process else None, process_released=released)
    write_json(log_dir / "samples.json", {"sampling_interval_ms": profile.memory_sample_interval_ms, "peak_is_sampled": True, "cpu_threads": profile.cpu_threads, "offline": True, "samples": samples})
    write_json(log_dir / "result.json", result)
    return result


def run_worker(job, registry, work_dir, profile, root, require_ready=True):
    work_dir = Path(work_dir).resolve()
    log_dir = work_dir / "logs"
    entry = registry.tools[job.tool_id]
    try:
        check_entry(entry, require_ready=require_ready)
    except (ValueError, OSError) as exc:
        result = WorkerResult(status="failed", error_code="model_missing", message=str(exc), log_dir=str(log_dir), output_dir=str(work_dir/"result"))
        write_json(log_dir / "result.json", result)
        return result
    active = profile.model_copy(deep=True)
    active.tools["_active"] = {"timeout_seconds": job.timeout_seconds}
    executable = Path(entry["python_executable"])
    script = Path(root) / "preprocessing/worker_main.py"
    try:
        with FileLock(str(Path(root) / ".hir-tool-worker.lock"), timeout=0):
            return monitor_process([executable, script, "--job", work_dir/"job.json", "--out", work_dir/"result"], work_dir, active, log_dir)
    except Timeout:
        return WorkerResult(status="resource_wait", error_code="worker_busy", message="Another isolated worker holds the single-worker lock", log_dir=str(log_dir), output_dir=str(work_dir/"result"))
