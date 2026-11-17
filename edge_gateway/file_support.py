"""Small OS adapters for the gateway's durable, exclusively owned journal."""

from __future__ import annotations

import os
from pathlib import Path

WINDOWS = os.name == "nt"


def lock_exclusive(fd: int) -> None:
    if WINDOWS:
        import msvcrt

        # locking() may lock beyond EOF; no write to a byte already locked by
        # another process is necessary. Always lock the same byte, nonblocking.
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def unlock(fd: int) -> None:
    if WINDOWS:
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)


def sync_parent_directory(path: Path) -> None:
    # The journal file itself has already been flushed with os.fsync (which
    # uses _commit on Windows). CRT os.open/fsync cannot open a Windows
    # directory; POSIX retains its existing extra directory-entry flush.
    if WINDOWS:
        return
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
