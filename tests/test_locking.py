import errno
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parents[1] / "lib/megaproxy-tools")
)

from megaproxy_tools import locking
from megaproxy_tools.locking import config_lock

LIB = pathlib.Path(__file__).resolve().parents[1] / "lib/megaproxy-tools"


class ConfigLock(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows locking errors")
    def test_windows_retries_contention_but_propagates_other_errors(self):
        stream = mock.Mock()
        with (
            mock.patch.object(
                locking.msvcrt,
                "locking",
                side_effect=[OSError(errno.EACCES, "locked"), None],
            ) as acquire,
            mock.patch.object(locking.time, "sleep") as sleep,
        ):
            locking.lock(stream)
            self.assertEqual(acquire.call_count, 2)
            sleep.assert_called_once_with(0.05)

        with (
            mock.patch.object(
                locking.msvcrt,
                "locking",
                side_effect=OSError(errno.EBADF, "bad descriptor"),
            ),
            self.assertRaises(OSError) as error,
        ):
            locking.lock(stream)
        self.assertEqual(error.exception.errno, errno.EBADF)

    def test_process_waits_and_exception_releases_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = pathlib.Path(temporary) / "config"
            child = None
            try:
                with self.assertRaisesRegex(ValueError, "release lock"):
                    with config_lock(folder):
                        child = subprocess.Popen(
                            [
                                sys.executable,
                                "-u",
                                "-c",
                                "import pathlib, sys; "
                                "sys.path.insert(0, sys.argv[1]); "
                                "from megaproxy_tools.locking import config_lock; "
                                "print('ready', flush=True)\n"
                                "with config_lock(pathlib.Path(sys.argv[2])):\n"
                                "    print('acquired', flush=True)\n",
                                str(LIB),
                                str(folder),
                            ],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                        )
                        self.assertEqual(child.stdout.readline().strip(), "ready")
                        with self.assertRaises(subprocess.TimeoutExpired):
                            child.communicate(timeout=0.3)
                        raise ValueError("release lock")
                stdout, stderr = child.communicate(timeout=5)
                self.assertEqual(child.returncode, 0, stderr)
                self.assertEqual(stdout.strip(), "acquired")
                with config_lock(folder):
                    self.assertTrue((folder / "config.lock").exists())
            finally:
                if child is not None:
                    if child.poll() is None:
                        child.kill()
                    child.communicate()


if __name__ == "__main__":
    unittest.main()
