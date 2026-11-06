import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "windows_install", ROOT / "win/install.py"
)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


@unittest.skipUnless(os.name == "nt", "Windows installation")
class WindowsInstallation(unittest.TestCase):
    def test_commands_run_by_name_in_cmd_and_powershell(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            target = installer.install(ROOT, base / "installed tools")
            config = base / "config/megaproxy-tools"
            config.mkdir(parents=True)
            (config / "config.json").write_text(
                json.dumps(
                    {
                        "schema": "net.megaproxy487.config",
                        "version": 8,
                        "profiles": [
                            {
                                "id": "test",
                                "proxy": {
                                    "type": "HTTPS",
                                    "host": "proxy.example",
                                    "port": 443,
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            probe = base / "probe arguments.py"
            probe.write_text(
                "import json,sys; print(json.dumps(sys.argv[1:])); sys.exit(23)",
                encoding="utf-8",
            )
            env = dict(os.environ, XDG_CONFIG_HOME=str(config.parent), PYTHONUTF8="1")
            env["PATH"] = os.pathsep.join(
                (
                    str(target),
                    str(Path(sys.executable).parent),
                    env["PATH"],
                )
            )
            for shell in ("cmd", "powershell"):
                for command in installer.COMMANDS:
                    with self.subTest(shell=shell, command=command):
                        if command == "proxy487ctl":
                            arguments = "--help"
                        else:
                            arguments = (
                                f'python "{probe}" "argument & with spaces" "кириллица"'
                            )
                        if shell == "cmd":
                            invocation = (
                                subprocess.list2cmdline([os.environ["COMSPEC"]])
                                + f' /d /s /c "{command} {arguments}"'
                            )
                        else:
                            invocation = [
                                "powershell.exe",
                                "-NoProfile",
                                "-NonInteractive",
                                "-Command",
                                f"& {command} {arguments}; exit $LASTEXITCODE",
                            ]
                        result = subprocess.run(
                            invocation,
                            env=env,
                            capture_output=True,
                            text=True,
                            encoding="utf-8",
                            timeout=15,
                        )
                        self.assertEqual(
                            result.returncode,
                            0 if command == "proxy487ctl" else 23,
                            result.stderr,
                        )
                        if command != "proxy487ctl":
                            self.assertEqual(
                                json.loads(result.stdout),
                                ["argument & with spaces", "кириллица"],
                            )

    def test_main_uses_prefix_and_selected_python_without_changing_real_path(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            mock.patch.dict(
                os.environ, {"PREFIX": temporary, "megaproxy_python": "py -3"}
            ),
            mock.patch.object(sys, "argv", ["install.py"]),
            mock.patch.object(installer, "update_user_path") as update,
            mock.patch("builtins.print"),
        ):
            installer.main()
            update.assert_called_once_with(Path(temporary).resolve() / "bin")
            self.assertIn(
                'py -3 "',
                (Path(temporary) / "bin/proxy487.cmd").read_text(encoding="utf-8"),
            )

    @unittest.skipUnless(shutil.which("git"), "Git checkout integration requires Git")
    def test_copy_git_update_and_wrappers(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "source пробел %PATH% ! (checkout)"
            prefix = base / "installed tools"
            for name in ("bin", "lib"):
                shutil.copytree(ROOT / name, source / name)
            subprocess.run(
                ["git", "init", str(source)], check=True, capture_output=True
            )
            env = dict(os.environ, XDG_CONFIG_HOME=str(base / "config"))
            env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env["PATH"]
            for git in (False, True, False):
                target = installer.install(source, prefix, git)
                wrapper = target / "proxy487ctl.cmd"
                self.assertNotIn(sys.executable, wrapper.read_text(encoding="utf-8"))
                expected = source if git else prefix
                self.assertIn(
                    str(expected).replace("%", "%%"),
                    wrapper.read_text(encoding="utf-8"),
                )
                result = subprocess.run(
                    [os.environ["COMSPEC"], "/d", "/c", str(wrapper), "--help"],
                    env=env,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                probe = base / "probe arguments.py"
                probe.write_text(
                    "import json,sys; print(json.dumps(sys.argv[1:])); sys.exit(7)",
                    encoding="utf-8",
                )
                result = subprocess.run(
                    subprocess.list2cmdline([os.environ["COMSPEC"]])
                    + ' /d /s /c "'
                    + subprocess.list2cmdline(
                        [
                            str(target / "noproxy487.cmd"),
                            sys.executable,
                            str(probe),
                            "argument & with spaces",
                            "plain",
                        ]
                    )
                    + '"',
                    env=env,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 7, result.stderr)
                self.assertEqual(
                    json.loads(result.stdout), ["argument & with spaces", "plain"]
                )
            self.assertTrue(
                (prefix / "lib/megaproxy-tools/megaproxy_tools/locking.py").exists()
            )

    def test_git_missing_and_overlapping_paths_do_not_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            prefix = Path(temporary) / "destination"
            with mock.patch.object(installer.shutil, "which", return_value=None):
                with self.assertRaisesRegex(ValueError, "winget install --id Git.Git"):
                    installer.install(ROOT, prefix, git=True)
            self.assertFalse(prefix.exists())
            with self.assertRaisesRegex(ValueError, "overlap"):
                installer.install(ROOT, ROOT)

    def test_user_path_preserves_type_and_is_idempotent(self):
        import winreg

        target = Path(os.environ["LOCALAPPDATA"]) / "MegaProxyTools/bin"
        with (
            mock.patch.object(winreg, "CreateKeyEx"),
            mock.patch.object(
                winreg,
                "QueryValueEx",
                return_value=(r"%USERPROFILE%\bin", winreg.REG_EXPAND_SZ),
            ),
            mock.patch.object(winreg, "SetValueEx") as write,
            mock.patch.object(installer.ctypes, "windll") as windll,
        ):
            installer.update_user_path(target)
            self.assertEqual(write.call_args.args[3], winreg.REG_EXPAND_SZ)
            self.assertEqual(
                write.call_args.args[4], r"%USERPROFILE%\bin;" + str(target)
            )
            windll.user32.SendMessageTimeoutW.assert_called_once()
        with (
            mock.patch.object(winreg, "CreateKeyEx"),
            mock.patch.object(
                winreg,
                "QueryValueEx",
                return_value=(
                    r"%LOCALAPPDATA%\MegaProxyTools\bin",
                    winreg.REG_EXPAND_SZ,
                ),
            ),
            mock.patch.object(winreg, "SetValueEx") as write,
        ):
            installer.update_user_path(target)
            write.assert_not_called()

    def test_cmd_bootstrap_passes_arguments_and_exit_status(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "bootstrap with spaces"
            (source / "win").mkdir(parents=True)
            shutil.copy2(ROOT / "install.cmd", source / "install.cmd")
            (source / "win/install.py").write_text(
                "import json,os,sys; "
                "print(json.dumps([sys.argv[1:], os.environ['megaproxy_python']])); "
                "sys.exit(7)",
                encoding="utf-8",
            )
            env = dict(os.environ)
            env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env["PATH"]
            result = subprocess.run(
                [
                    os.environ["COMSPEC"],
                    "/d",
                    "/c",
                    str(source / "install.cmd"),
                    "--git",
                ],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 7, result.stderr)
            self.assertEqual(json.loads(result.stdout), [["--git"], "python"])

            env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
            result = subprocess.run(
                [os.environ["COMSPEC"], "/d", "/c", str(source / "install.cmd")],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn(
                "winget install --id Python.Python.3.14 --exact", result.stdout
            )


if __name__ == "__main__":
    unittest.main()
