"""Fail-closed advisory file locks, using the engine's flock/msvcrt protocol.

Locks are released when their handle closes, including after process crashes.
The first byte is reserved for Windows' byte-range locking.
"""
import errno
import os
import time


def acquire(handle, *, blocking=True):
    if os.name != "nt":
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        return
    import msvcrt
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0" if "b" in handle.mode else "\0")
        handle.flush()
    while True:
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return
        except OSError as exc:
            if exc.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                raise
            if not blocking:
                raise BlockingIOError(exc.errno, "File is locked") from exc
            time.sleep(0.05)


def release(handle):
    if os.name == "nt":
        import msvcrt
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
