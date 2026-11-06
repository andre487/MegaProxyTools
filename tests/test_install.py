import json
import os
import pathlib
import shutil
import subprocess as sp
import sys
import tarfile
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


@unittest.skipIf(os.name == "nt", "POSIX shell installer; see test_windows_install")
class Installation(unittest.TestCase):
    def test_checkout_and_piped_installation(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = pathlib.Path(temporary).resolve()
            archive = folder / "source.tar.gz"

            with tarfile.open(archive, "w:gz") as stream:
                for name in ("install.sh", "bin", "lib"):
                    stream.add(
                        ROOT / name,
                        arcname="MegaProxyTools-example/" + name,
                        filter=lambda info: (
                            None if "__pycache__" in info.name else info
                        ),
                    )

            fake_bin = folder / "fake-bin"
            fake_bin.mkdir()
            curl = fake_bin / "curl"
            curl.write_text(
                f"#!{sys.executable}\n"
                + """import os
import pathlib
import shutil
import sys

if os.environ.get('FAIL_DOWNLOAD'):
    sys.exit(22)

pathlib.Path(os.environ['CURL_LOG']).write_text('\\n'.join(sys.argv[1:]))
shutil.copyfile(os.environ['TEST_ARCHIVE'], sys.argv[sys.argv.index('-o') + 1])
"""
            )
            curl.chmod(0o755)
            env = dict(
                os.environ,
                HOME=str(folder),
                TMPDIR=str(folder),
                PATH=str(fake_bin) + os.pathsep + os.environ["PATH"],
                TEST_ARCHIVE=str(archive),
                CURL_LOG=str(folder / "curl.log"),
            )

            for mode in ("checkout", "pipe", "download-fails", "bad-archive"):
                prefix = folder / mode
                run_env = dict(
                    env, PREFIX=str(prefix), MEGAPROXY_TOOLS_REF="work/proxy-tools"
                )

                if mode == "checkout":
                    result = sp.run(
                        ["sh", str(ROOT / "install.sh")],
                        cwd=folder,
                        env=run_env,
                        text=True,
                        capture_output=True,
                    )
                    self.assertFalse((folder / "curl.log").exists())
                else:
                    if mode == "download-fails":
                        run_env["FAIL_DOWNLOAD"] = "1"

                    if mode == "bad-archive":
                        broken = folder / "broken.tar.gz"
                        broken.write_text("not an archive")
                        run_env["TEST_ARCHIVE"] = str(broken)

                    result = sp.run(
                        ["bash"],
                        input=(ROOT / "install.sh").read_text(),
                        cwd=folder,
                        env=run_env,
                        text=True,
                        capture_output=True,
                    )

                if mode in ("download-fails", "bad-archive"):
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse(prefix.exists())
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)

                    for command in ("noproxy487", "proxy487ctl"):
                        check = sp.run(
                            [str(prefix / "bin" / command), "--help"],
                            env=run_env,
                            text=True,
                            capture_output=True,
                        )
                        self.assertEqual(check.returncode, 0, check.stderr)

                    self.assertTrue(
                        (
                            prefix / "lib/megaproxy-tools/megaproxy_tools/sync.py"
                        ).exists()
                    )
                    independent_env = dict(
                        run_env, XDG_CONFIG_HOME=str(prefix / "independent-config")
                    )
                    runner, controller = (
                        prefix / "bin/proxy487",
                        prefix / "bin/proxy487ctl",
                    )
                    hidden_runner = runner.with_name("proxy487-hidden")
                    runner.rename(hidden_runner)

                    try:
                        check = sp.run(
                            [str(controller), "--no-config-sync", "import", "-"],
                            input=json.dumps(
                                {
                                    "schema": "net.megaproxy487.config",
                                    "version": 8,
                                    "profiles": [
                                        {
                                            "id": "example",
                                            "proxy": {
                                                "type": "HTTPS",
                                                "host": "proxy.example",
                                                "port": 443,
                                            },
                                        }
                                    ],
                                }
                            ),
                            env=independent_env,
                            text=True,
                            capture_output=True,
                        )
                        self.assertEqual(check.returncode, 0, check.stderr)
                        check = sp.run(
                            [str(controller), "--no-config-sync", "list"],
                            env=independent_env,
                            text=True,
                            capture_output=True,
                        )
                        self.assertEqual(check.returncode, 0, check.stderr)
                        self.assertIn("proxy.example", check.stdout)
                    finally:
                        hidden_runner.rename(runner)

                    hidden_controller = controller.with_name("proxy487ctl-hidden")
                    controller.rename(hidden_controller)

                    try:
                        check = sp.run(
                            [
                                str(runner),
                                "--no-config-sync",
                                sys.executable,
                                "-c",
                                'import os; assert os.environ["https_proxy"] == "https://proxy.example:443"',
                            ],
                            env=independent_env,
                            text=True,
                            capture_output=True,
                        )
                        self.assertEqual(check.returncode, 0, check.stderr)
                    finally:
                        hidden_controller.rename(controller)

                if mode == "pipe":
                    config = folder / ".config/megaproxy-tools/config.json"
                    config.parent.mkdir(parents=True)
                    config.write_text("existing private configuration")
                    (prefix / "bin/proxy487").write_text("outdated installed command")
                    update = sp.run(
                        ["bash"],
                        input=(ROOT / "install.sh").read_text(),
                        cwd=folder,
                        env=run_env,
                        text=True,
                        capture_output=True,
                    )
                    self.assertEqual(update.returncode, 0, update.stderr)
                    self.assertEqual(
                        (prefix / "bin/proxy487").read_bytes(),
                        (ROOT / "bin/proxy487").read_bytes(),
                    )
                    self.assertEqual(
                        config.read_text(), "existing private configuration"
                    )
                    self.assertIn(
                        "https://codeload.github.com/andre487/MegaProxyTools/tar.gz/work/proxy-tools",
                        (folder / "curl.log").read_text(),
                    )

                self.assertFalse(list(folder.glob("tmp.*")))

    @unittest.skipUnless(
        shutil.which("git"), "Git is required for checkout installation"
    )
    def test_git_links_local_checkout_and_remote_updates(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = pathlib.Path(temporary).resolve()
            source = folder / "checkout"
            source.mkdir()

            for name in ("bin", "lib"):
                shutil.copytree(
                    ROOT / name,
                    source / name,
                    ignore=shutil.ignore_patterns("__pycache__"),
                )

            for name in ("install.sh", ".gitignore"):
                shutil.copy2(ROOT / name, source / name)

            env = dict(
                os.environ,
                GIT_CONFIG_GLOBAL=os.devnull,
                GIT_CONFIG_NOSYSTEM="1",
                GIT_TERMINAL_PROMPT="0",
                GIT_CONFIG_COUNT="0",
                INSTALL_FROM_GIT="0",
            )

            def git(*args):
                return sp.run(
                    ["git", *args], env=env, text=True, check=True, capture_output=True
                )

            def commit():
                git("-C", str(source), "add", ".")
                git(
                    "-C",
                    str(source),
                    "-c",
                    "user.name=Installer Test",
                    "-c",
                    "user.email=installer@example.invalid",
                    "-c",
                    "commit.gpgsign=false",
                    "commit",
                    "-m",
                    "Test snapshot",
                )

            git("init", "-b", "main", str(source))
            commit()
            bare = folder / "remote.git"
            git("clone", "--bare", str(source), str(bare))
            original = (source / "bin/noproxy487").read_text()

            for flag in (True, False):
                prefix = folder / ("flag prefix" if flag else "environment prefix")
                run_env = dict(
                    env, PREFIX=str(prefix), INSTALL_FROM_GIT="0" if flag else "1"
                )
                result = sp.run(
                    ["sh", str(source / "install.sh"), *(["--git"] if flag else [])],
                    cwd=folder,
                    env=run_env,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

                for name in ("proxy487", "noproxy487", "proxy487ctl"):
                    link = prefix / "bin" / name
                    self.assertTrue(link.is_symlink())
                    self.assertEqual(link.resolve(), source / "bin" / name)

                self.assertFalse((prefix / "lib").exists())
                (source / "bin/noproxy487").write_text(
                    original.replace("Usage: noproxy487", "Usage: live noproxy487")
                )
                check = sp.run(
                    [str(prefix / "bin/noproxy487"), "--help"],
                    env=run_env,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(check.returncode, 0, check.stderr)
                self.assertIn("Usage: live", check.stdout)
                # Local Git mode leaves a dirty working tree untouched.
                result = sp.run(
                    ["sh", str(source / "install.sh"), "--git"],
                    env=run_env,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                before_copy = (source / "bin/noproxy487").read_bytes()
                result = sp.run(
                    ["sh", str(source / "install.sh")],
                    env=dict(run_env, INSTALL_FROM_GIT="0"),
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse((prefix / "bin/noproxy487").is_symlink())
                self.assertEqual((source / "bin/noproxy487").read_bytes(), before_copy)
                (source / "bin/noproxy487").write_text(original)

            home = folder / "remote home"
            remote_env = dict(
                env,
                HOME=str(home),
                MEGAPROXY_TOOLS_REF="main",
                GIT_CONFIG_COUNT="1",
                GIT_CONFIG_KEY_0=f"url.{bare.as_uri()}.insteadOf",
                GIT_CONFIG_VALUE_0="https://github.com/andre487/MegaProxyTools.git",
            )
            remote_env.pop("PREFIX", None)
            checkout = home / ".local/src/MegaProxyTools"

            def piped(flag=True):
                return sp.run(
                    ["bash", "-s", "--", *(["--git"] if flag else [])],
                    input=(ROOT / "install.sh").read_text(),
                    cwd=folder,
                    env=dict(remote_env, INSTALL_FROM_GIT="0" if flag else "1"),
                    text=True,
                    capture_output=True,
                )

            result = piped()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                (home / ".local/bin/proxy487ctl").resolve(),
                checkout / "bin/proxy487ctl",
            )
            (source / "bin/noproxy487").write_text(
                original + "\n# Updated source snapshot\n"
            )
            commit()
            git("-C", str(source), "push", str(bare), "main")
            result = piped(flag=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                git("-C", str(checkout), "rev-parse", "HEAD").stdout,
                git("-C", str(source), "rev-parse", "HEAD").stdout,
            )
            modified = checkout / "bin/noproxy487"
            modified.write_text(modified.read_text() + "\n# Uncommitted user change\n")
            before = modified.read_bytes()
            result = piped()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("local changes", result.stderr)
            self.assertEqual(modified.read_bytes(), before)
            # Installing directly over the source bin directory must not replace source files.
            before = (source / "bin/proxy487").read_bytes()
            result = sp.run(
                ["sh", str(source / "install.sh"), "--git"],
                env=dict(env, PREFIX=str(source)),
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((source / "bin/proxy487").read_bytes(), before)
            alias_prefix = folder / "aliased prefix"
            alias_prefix.mkdir()
            (alias_prefix / "bin").symlink_to(source / "bin", target_is_directory=True)
            result = sp.run(
                ["sh", str(source / "install.sh"), "--git"],
                env=dict(env, PREFIX=str(alias_prefix)),
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((source / "bin/proxy487").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
