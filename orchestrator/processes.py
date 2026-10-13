"""Bounded hidden subprocesses; Windows children enter a Job before execution."""
from __future__ import annotations

import ctypes
from ctypes import wintypes as w
import os
import signal
import subprocess
import threading
import time


MAX_OUTPUT = 2 * 1024 * 1024
MAX_LINE = 256 * 1024


class ProcessFailure(RuntimeError):
    pass


def settled_empty(job, seconds=.25):
    """Bounded observation after root exit; a live orphan still fails the gate."""
    deadline = time.monotonic() + seconds
    while not job.empty():
        if time.monotonic() >= deadline:
            return False
        time.sleep(.01)
    return True


class WindowsJob:
    def __init__(self):
        self.k = ctypes.WinDLL("kernel32", use_last_error=True)
        self.k.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
        self.k.CreateJobObjectW.restype = w.HANDLE
        self.k.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        self.k.QueryInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.c_void_p]
        self.k.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        self.k.TerminateJobObject.argtypes = [w.HANDLE, w.UINT]
        self.k.CloseHandle.argtypes = [w.HANDLE]
        self.handle = self.k.CreateJobObjectW(None, None)
        if not self.handle:
            raise ProcessFailure("JOB_CREATE_FAILED")

        class Basic(ctypes.Structure):
            _fields_ = [("user", ctypes.c_longlong), ("job", ctypes.c_longlong),
                        ("flags", w.DWORD), ("min_ws", ctypes.c_size_t), ("max_ws", ctypes.c_size_t),
                        ("process_limit", w.DWORD), ("affinity", ctypes.c_size_t),
                        ("priority", w.DWORD), ("schedule", w.DWORD)]

        class Limits(ctypes.Structure):
            _fields_ = [("basic", Basic), ("io", ctypes.c_ulonglong * 6),
                        ("process_mem", ctypes.c_size_t), ("job_mem", ctypes.c_size_t),
                        ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]

        limits = Limits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.k.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.close()
            raise ProcessFailure("JOB_POLICY_FAILED")

    def attach_and_resume(self, process):
        if not self.k.AssignProcessToJobObject(self.handle, w.HANDLE(int(process._handle))):
            raise ProcessFailure("JOB_ASSIGN_FAILED")

        class ThreadEntry(ctypes.Structure):
            _fields_ = [("size", w.DWORD), ("usage", w.DWORD), ("id", w.DWORD),
                        ("owner", w.DWORD), ("base_priority", w.LONG),
                        ("delta_priority", w.LONG), ("flags", w.DWORD)]

        self.k.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
        self.k.CreateToolhelp32Snapshot.restype = w.HANDLE
        self.k.Thread32First.argtypes = [w.HANDLE, ctypes.POINTER(ThreadEntry)]
        self.k.Thread32Next.argtypes = [w.HANDLE, ctypes.POINTER(ThreadEntry)]
        self.k.OpenThread.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        self.k.OpenThread.restype = w.HANDLE
        self.k.ResumeThread.argtypes = [w.HANDLE]
        self.k.ResumeThread.restype = w.DWORD
        snapshot = self.k.CreateToolhelp32Snapshot(4, 0)
        if snapshot == ctypes.c_void_p(-1).value:
            raise ProcessFailure("THREAD_SNAPSHOT_FAILED")
        resumed = 0
        try:
            entry = ThreadEntry()
            entry.size = ctypes.sizeof(entry)
            found = self.k.Thread32First(snapshot, ctypes.byref(entry))
            while found:
                if entry.owner == process.pid:
                    handle = self.k.OpenThread(2, False, entry.id)
                    if not handle:
                        raise ProcessFailure("THREAD_OPEN_FAILED")
                    try:
                        if self.k.ResumeThread(handle) != 1:
                            raise ProcessFailure("THREAD_RESUME_FAILED")
                        resumed += 1
                    finally:
                        self.k.CloseHandle(handle)
                found = self.k.Thread32Next(snapshot, ctypes.byref(entry))
        finally:
            self.k.CloseHandle(snapshot)
        if resumed != 1:
            raise ProcessFailure("PRIMARY_THREAD_NOT_VERIFIED")

    def terminate(self):
        if self.handle:
            self.k.TerminateJobObject(self.handle, 1)

    def empty(self):
        class Accounting(ctypes.Structure):
            _fields_ = [("times", ctypes.c_longlong * 4), ("faults", w.DWORD),
                        ("total", w.DWORD), ("active", w.DWORD), ("terminated", w.DWORD)]
        value = Accounting()
        if not self.k.QueryInformationJobObject(self.handle, 1, ctypes.byref(value), ctypes.sizeof(value), None):
            return False
        return value.active == 0

    def close(self):
        if self.handle:
            self.k.CloseHandle(self.handle)
            self.handle = None


def bounded_run(argv, *, cwd, stdin=b"", timeout=30, stop=None, before_terminate=lambda: None, env=None):
    """No shell, fixed output cap, fence callback before killing on cancellation."""
    job = None
    proc = None
    readers = []
    data = [bytearray(), bytearray()]
    overflow = threading.Event()
    mutex = threading.Lock()
    started = time.monotonic()
    reason = None
    tree_empty = False
    fence_called = False
    try:
        if os.name == "nt":
            job = WindowsJob()
        options = {"creationflags": 0x08000000 | 0x00000004} if job else {"start_new_session": True}
        proc = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, env=env, **options)
        created_at = time.monotonic()
        if job:
            job.attach_and_resume(proc)

        def drain(stream, index):
            try:
                while chunk := stream.read(65536):
                    with mutex:
                        remaining = MAX_OUTPUT - sum(len(x) for x in data)
                        data[index].extend(chunk[:max(0, remaining)])
                        if len(chunk) > remaining:
                            overflow.set()
            except OSError:
                pass
            finally:
                stream.close()

        for index, stream in enumerate((proc.stdout, proc.stderr)):
            reader = threading.Thread(target=drain, args=(stream, index), daemon=True)
            reader.start()
            readers.append(reader)
        def send_input():
            try:
                proc.stdin.write(stdin)
            except (BrokenPipeError, OSError):
                pass
            finally:
                proc.stdin.close()
        # Native startup can stall before reading stdin; writes share the deadline.
        writer = threading.Thread(target=send_input, daemon=True)
        writer.start()
        readers.append(writer)
        while proc.poll() is None:
            if overflow.is_set():
                reason = "OUTPUT_LIMIT"
            elif stop is not None and stop.is_set():
                reason = "CANCELLED"
            elif time.monotonic() - started >= timeout:
                reason = "TIMEOUT"
            if reason:
                break
            time.sleep(0.02)
        exited_at = time.monotonic() if proc.poll() is not None else None
        # A CLI that exits while descendants still run is not a clean completion.
        if job and not reason and not settled_empty(job):
            reason = "DESCENDANTS_REMAIN"
        if reason:
            fence_called = True
            before_terminate()
            if job:
                job.terminate()
            else:
                os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(timeout=5)
        exited_at = exited_at if exited_at is not None else time.monotonic()
        deadline = time.monotonic() + 5
        while job and not job.empty() and time.monotonic() < deadline:
            time.sleep(0.02)
        tree_empty = job.empty() if job else proc.poll() is not None
        for reader in readers:
            reader.join(timeout=max(0, deadline - time.monotonic()))
        if any(reader.is_alive() for reader in readers):
            tree_empty = False
        if overflow.is_set():
            reason = reason or "OUTPUT_LIMIT"
        return {"returncode": proc.returncode, "stdout": bytes(data[0]), "stderr": bytes(data[1]),
                "reason": reason, "tree_empty": tree_empty, "pid": proc.pid,
                "process_created_at": created_at, "process_exited_at": exited_at,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "process_boundary": "WINDOWS_JOB_BEFORE_RESUME" if job else "POSIX_GROUP_LIMITED"}
    except BaseException:
        fence_error = None
        try:
            if not fence_called:
                fence_called = True
                before_terminate()
        except BaseException as error:
            fence_error = error
        finally:
            try:
                if job:
                    job.terminate()
            finally:
                # Assignment can fail before the suspended process joins the Job.
                if proc and proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=5)
        if fence_error:
            raise ProcessFailure("FENCING_FAILED_CLEANUP_ATTEMPTED") from fence_error
        raise
    finally:
        if proc:
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                if stream and not stream.closed:
                    stream.close()
        if job:
            job.close()


def jsonl_events(raw):
    import json
    if len(raw) > MAX_OUTPUT:
        raise ProcessFailure("OUTPUT_LIMIT")
    result = []
    for line in raw.splitlines():
        if len(line) > MAX_LINE:
            raise ProcessFailure("EVENT_LINE_LIMIT")
        if line:
            value = json.loads(line)
            if type(value) is not dict:
                raise ProcessFailure("EVENT_SCHEMA")
            result.append(value)
    return result
