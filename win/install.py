"""Install Windows command wrappers using the current Python interpreter."""

import argparse
import ctypes
import os
import shutil
import subprocess
import sys
from pathlib import Path

COMMANDS = ("proxy487", "noproxy487", "proxy487ctl")


def install(source, prefix, git=False, python_command="python"):
    if python_command not in ("python", "py -3"):
        raise ValueError("Unsupported Python command")
    source, prefix = source.resolve(), prefix.resolve()
    if (
        prefix == source
        or source in prefix.parents
        or (not git and prefix in source.parents)
    ):
        raise ValueError("Installation and source directories must not overlap")
    for name in COMMANDS:
        if not (source / "bin" / name).is_file():
            raise ValueError("Incomplete source checkout")
    runtime = source / "lib/megaproxy-tools"
    if not (runtime / "megaproxy_tools/locking.py").is_file():
        raise ValueError("Incomplete source checkout")
    if git:
        if not shutil.which("git"):
            raise ValueError(
                "Git is required for --git. Install it with: "
                "winget install --id Git.Git --exact"
            )
        result = subprocess.run(
            ["git", "-C", str(source), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if Path(result.stdout.strip()).resolve() != source:
            raise ValueError("Git installation requires a repository checkout")
    else:
        shutil.copytree(
            runtime,
            prefix / "lib/megaproxy-tools",
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )

    scripts = source if git else prefix
    target = prefix / "bin"
    target.mkdir(parents=True, exist_ok=True)
    for name in COMMANDS:
        if not git:
            shutil.copy2(source / "bin" / name, target / name)
        script = str(scripts / "bin" / name).replace("%", "%%")
        (target / (name + ".cmd")).write_text(
            "@echo off\nsetlocal DisableDelayedExpansion\n"
            "chcp 65001 >nul\n"
            f'{python_command} "{script}" %*\nexit /b %errorlevel%\n',
            encoding="utf-8",
            newline="\r\n",
        )
    return target


def update_user_path(target):
    import winreg

    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER,
        "Environment",
        0,
        winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE,
    ) as key:
        try:
            value, kind = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            value, kind = "", winreg.REG_EXPAND_SZ
        if kind not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
            raise ValueError("User Path must be a string")

        def normalized(entry):
            return os.path.normcase(
                os.path.normpath(os.path.expandvars(entry.strip().strip('"')))
            )

        if normalized(str(target)) in (
            normalized(entry) for entry in value.split(";") if entry.strip()
        ):
            return
        winreg.SetValueEx(
            key,
            "Path",
            0,
            kind,
            value + (";" if value and not value.endswith(";") else "") + str(target),
        )

    # Notify Explorer and other applications that the registry environment changed,
    # so newly launched processes can inherit the updated PATH. Existing terminals
    # keep their current environment and must be reopened. This notification is
    # best-effort: even if delivery fails, PATH remains saved in the registry.
    ctypes.windll.user32.SendMessageTimeoutW(
        0xFFFF,  # HWND_BROADCAST: send to all top-level windows.
        0x001A,  # WM_SETTINGCHANGE: notify applications of changed settings.
        0,  # wParam is unused for this environment notification.
        ctypes.c_wchar_p("Environment"),  # lParam identifies environment changes.
        2,  # SMTO_ABORTIFHUNG: do not wait for unresponsive applications.
        1000,  # Response timeout in milliseconds per window.
        None,  # No output buffer for the recipient's message-processing result.
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--git", action="store_true", help="run directly from this Git checkout"
    )
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("Use install.sh on POSIX")
    prefix = Path(
        os.environ.get("PREFIX") or Path(os.environ["LOCALAPPDATA"]) / "MegaProxyTools"
    )
    target = install(
        Path(__file__).resolve().parents[1],
        prefix,
        args.git,
        os.environ.get("megaproxy_python", "python"),
    )
    update_user_path(target)
    print(f"Installed to {target}; Python is resolved through PATH.")
    print("User PATH updated. Reopen your terminal to use the commands by name.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Installation failed: {error}", file=sys.stderr)
        sys.exit(1)
