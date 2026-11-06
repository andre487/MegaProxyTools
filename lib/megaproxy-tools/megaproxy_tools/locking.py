"""Exclusive configuration locks for POSIX and Windows."""

import contextlib
import os

if os.name == "nt":
    import errno
    import msvcrt
    import time

    def lock(stream):
        # LK_LOCK gives up after ten retries; configuration locks must keep waiting.
        while True:
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except OSError as error:
                if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                time.sleep(0.05)

    def unlock(stream):
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def lock(stream):
        fcntl.flock(stream, fcntl.LOCK_EX)

    def unlock(stream):
        fcntl.flock(stream, fcntl.LOCK_UN)


@contextlib.contextmanager
def config_lock(folder):
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    with os.fdopen(
        os.open(folder / "config.lock", os.O_RDWR | os.O_CREAT, 0o600), "r+b"
    ) as stream:
        lock(stream)
        try:
            yield
        finally:
            unlock(stream)
