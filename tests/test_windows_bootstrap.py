import os
import shutil
import subprocess as sp
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "nt", "PowerShell bootstrap")
class WindowsBootstrap(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.source = self.base / "source"
        for name in ("bin", "lib", "win"):
            shutil.copytree(
                ROOT / name,
                self.source / name,
                ignore=shutil.ignore_patterns("__pycache__"),
            )
        shutil.copy2(ROOT / "install.cmd", self.source / "install.cmd")
        # Run the real installer but prevent changes to the user's registry.
        installer = self.source / "win/install.py"
        installer.write_text(
            installer.read_text(encoding="utf-8").replace(
                'if __name__ == "__main__":',
                'if __name__ == "__main__":\n    update_user_path = lambda target: None',
            ),
            encoding="utf-8",
        )
        self.temp = self.base / "temporary downloads"
        self.temp.mkdir()
        self.prefix = self.base / "installed tools"
        self.archive = self.base / "source.zip"
        self.env = dict(
            os.environ,
            PREFIX=str(self.prefix),
            INSTALL_FROM_GIT="0",
            MEGAPROXY_TOOLS_REF="main",
            TEMP=str(self.temp),
            TMP=str(self.temp),
            TEST_LOADER=str(ROOT / "win/install.ps1"),
            TEST_ARCHIVE=str(self.archive),
            TEST_DOWNLOAD_LOG=str(self.base / "download.log"),
            PYTHONUTF8="1",
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_COUNT="0",
            GIT_TERMINAL_PROMPT="0",
        )
        self.env["PATH"] = (
            str(Path(sys.executable).parent) + os.pathsep + self.env["PATH"]
        )

    def pack(self):
        with zipfile.ZipFile(self.archive, "w") as archive:
            for path in self.source.rglob("*"):
                if path.is_file():
                    archive.write(
                        path,
                        "MegaProxyTools-main/"
                        + path.relative_to(self.source).as_posix(),
                    )

    def run_loader(self):
        result = sp.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Restricted",
                "-Command",
                r"""
function Invoke-WebRequest {
    param([switch]$UseBasicParsing, [string]$Uri, [string]$OutFile)
    if ($env:TEST_DOWNLOAD_FAIL -eq '1') { throw 'Simulated download failure' }
    [IO.File]::WriteAllText($env:TEST_DOWNLOAD_LOG, $Uri)
    Copy-Item -LiteralPath $env:TEST_ARCHIVE -Destination $OutFile
}
function Expand-Archive { throw 'Archive script module is unavailable under Restricted' }
try {
    [IO.File]::ReadAllText($env:TEST_LOADER) | Invoke-Expression
    exit 0
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
""",
            ],
            env=self.env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=45,
        )
        self.assertFalse(list(self.temp.glob("megaproxy-*")), result.stderr)
        return result

    def test_archive_install_update_and_download_cleanup(self):
        for marker in ("first", "updated"):
            (self.source / "lib/megaproxy-tools/revision.txt").write_text(marker)
            self.pack()
            result = self.run_loader()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                (self.prefix / "lib/megaproxy-tools/revision.txt").read_text(), marker
            )
            self.assertTrue((self.prefix / "bin/proxy487.cmd").exists())
        self.assertEqual(
            (self.base / "download.log").read_text(),
            "https://codeload.github.com/andre487/MegaProxyTools/zip/main",
        )
        self.env["TEST_DOWNLOAD_FAIL"] = "1"
        result = self.run_loader()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Simulated download failure", result.stderr)
        self.assertEqual(
            (self.prefix / "lib/megaproxy-tools/revision.txt").read_text(), "updated"
        )

    def test_invalid_archive_and_failed_installer_are_reported(self):
        self.archive.write_text("not a zip file")
        self.assertNotEqual(self.run_loader().returncode, 0)
        (self.source / "install.cmd").write_text("@exit /b 7\n")
        self.pack()
        result = self.run_loader()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Installation failed", result.stderr)
        self.assertFalse(self.prefix.exists())

    @unittest.skipUnless(shutil.which("git"), "Git integration requires Git")
    def test_git_clone_update_and_dirty_checkout_protection(self):
        def git(*args):
            return sp.run(
                ["git", *args],
                env=self.env,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )

        def commit():
            git("-C", str(self.source), "add", ".")
            git(
                "-C",
                str(self.source),
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.invalid",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "-m",
                "Test snapshot",
            )

        git("init", "-b", "main", str(self.source))
        commit()
        remote = self.base / "remote.git"
        git("clone", "--bare", str(self.source), str(remote))
        self.env.update(
            INSTALL_FROM_GIT="1",
            GIT_CONFIG_COUNT="1",
            GIT_CONFIG_KEY_0=f"url.{remote.as_uri()}.insteadOf",
            GIT_CONFIG_VALUE_0="https://github.com/andre487/MegaProxyTools.git",
        )
        result = self.run_loader()
        self.assertEqual(result.returncode, 0, result.stderr)
        checkout = self.prefix / "src/MegaProxyTools"
        wrapper = self.prefix / "bin/proxy487.cmd"
        self.assertIn(str(checkout), wrapper.read_text(encoding="utf-8"))
        marker = self.source / "revision.txt"
        marker.write_text("new revision")
        commit()
        git("-C", str(self.source), "push", str(remote), "main")
        result = self.run_loader()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((checkout / "revision.txt").read_text(), "new revision")
        (checkout / "revision.txt").write_text("local changes")
        result = self.run_loader()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("local changes", result.stderr)
        self.assertEqual((checkout / "revision.txt").read_text(), "local changes")


if __name__ == "__main__":
    unittest.main()
