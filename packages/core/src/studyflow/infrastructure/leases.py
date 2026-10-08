"""Cross-process shared activity / exclusive maintenance locks (no lockfile deletion)."""
from contextlib import contextmanager
from pathlib import Path
import hashlib
import os
from studyflow.shared.domain import DomainError

@contextmanager
def workspace_lease(root,exclusive=False):
    root=Path(root).resolve()
    name=".studyflow-"+hashlib.sha256(os.path.normcase(str(root)).encode()).hexdigest()[:24]+".lease"
    root.parent.mkdir(parents=True,exist_ok=True)
    with (root.parent/name).open("a+b") as stream:
        if os.name=="nt":
            import ctypes,msvcrt
            from ctypes import wintypes
            class OVERLAPPED(ctypes.Structure):
                _fields_=[("Internal",ctypes.c_size_t),("InternalHigh",ctypes.c_size_t),("Offset",wintypes.DWORD),("OffsetHigh",wintypes.DWORD),("hEvent",wintypes.HANDLE)]
            kernel=ctypes.WinDLL("kernel32",use_last_error=True)
            kernel.LockFileEx.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,ctypes.POINTER(OVERLAPPED)]
            kernel.UnlockFileEx.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,ctypes.POINTER(OVERLAPPED)]
            handle=msvcrt.get_osfhandle(stream.fileno());overlapped=OVERLAPPED()
            acquired=kernel.LockFileEx(handle,1|(2 if exclusive else 0),0,1,0,ctypes.byref(overlapped))
        else:
            import fcntl
            try:fcntl.flock(stream.fileno(),(fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)|fcntl.LOCK_NB);acquired=True
            except OSError:acquired=False
        if not acquired:raise DomainError("WORKSPACE_MAINTENANCE_BUSY","工作区正在运行或维护，未替换任何数据。","关闭使用该工作区的程序，或恢复到一个全新目录。")
        try:yield
        finally:
            if os.name=="nt":kernel.UnlockFileEx(handle,0,1,0,ctypes.byref(overlapped))
            else:fcntl.flock(stream.fileno(),fcntl.LOCK_UN)
