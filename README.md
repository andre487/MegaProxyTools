# MegaProxyTools

<p align="center">
  <img src="docs/assets/icon-radius.svg" width="160" alt="MPX — MegaProxyTools">
</p>

Run individual commands with or without a proxy. Python standard library only; macOS, Linux and Windows.
Part of [MegaProxy](https://github.com/andre487/MegaProxyServer).

Documentation: **[English](docs/en/README.md)** · **[Русский](docs/ru/README.md)**

## Quick start

Requires Python 3.10+, Bash, curl and tar on macOS or Linux. No Git, pip, virtualenv or background service.

```sh
curl -fsSL https://raw.githubusercontent.com/andre487/MegaProxyTools/main/install.sh | bash
proxy487ctl import /path/to/MegaProxy.json
proxy487ctl list
proxy487ctl choose
proxy487 curl https://example.com
noproxy487 curl https://example.com
```

Run the same install command to update; configuration is retained.
For a live Git checkout, use `./install.sh --git` or `INSTALL_FROM_GIT=1 ./install.sh`.
With a piped installer, `bash -s -- --git` clones into `~/.local/src/MegaProxyTools`
and links the commands from there. `PREFIX` changes the installation root.
Add `~/.local/bin` to PATH if needed. Settings use MegaProxyConfig v8 in
`~/.config/megaproxy-tools/config.json` (respects `XDG_CONFIG_HOME`).
Import accepts only MegaProxy JSON v8; use `proxy487ctl import -` for stdin.
HTTPS and SOCKS5 are supported; incompatible protocols/settings produce a notice.
Stable IDs are merged, existing selection and eligible omitted passwords are retained.
A root `subscription` in imported JSON enables startup refresh, at most once per hour.
Use `proxy487 --no-config-sync COMMAND` or `proxy487ctl --no-config-sync list` to skip it.
Refresh logs go to stderr before command execution; failures retain saved settings.
Configuration contains secrets: never commit it.

`proxy487` defaults `NODE_USE_ENV_PROXY=1` so supported Node.js clients read proxy
variables. Existing environment and `default.env` values take precedence;
`noproxy487` removes this flag. Node.js supports it for `fetch` from 22.21.0/24.0.0,
and for `http`/`https` from 22.21.0/24.5.0. Older versions need application-specific
configuration; built-in Node.js proxy support does not support SOCKS.
See [Node.js proxy configuration](https://nodejs.org/en/learn/http/enterprise-network-configuration)
and the runtime compatibility notes in the documentation.

## Windows installation

Install or update from PowerShell (Windows PowerShell 5.1 or newer):

```powershell
irm https://raw.githubusercontent.com/andre487/MegaProxyTools/main/win/install.ps1 | iex
```

The loader downloads a source archive, runs `install.cmd`, then removes its
temporary files. Repeating the command updates the tools and preserves settings.
For a persistent Git checkout instead of copied files:

```powershell
$env:INSTALL_FROM_GIT = '1'
irm https://raw.githubusercontent.com/andre487/MegaProxyTools/main/win/install.ps1 | iex
Remove-Item Env:INSTALL_FROM_GIT
```

Git mode clones into `PREFIX\src\MegaProxyTools`, creates command wrappers pointing
there, and updates through fast-forward on repeated installation. Local changes,
diverged history or an unrelated checkout stop the update. `MEGAPROXY_TOOLS_REF`
selects the branch, tag or commit (default `main`). Use the same ref in the loader
URL when you need a different loader version.

Alternatively, download and extract the repository, or clone it, then run locally:

```powershell
.\install.cmd
# Run commands directly from the current Git checkout instead of copying:
.\install.cmd --git
```

The installer checks Python 3.10+ (`python`, then `py -3`); if missing, it prints a
winget installation command. `--git` also requires Git and prints installation
instructions if it is missing. Local `install.cmd --git` does not fetch or change
the checkout.
Commands are installed into `%LOCALAPPDATA%\MegaProxyTools\bin` and added to the
user PATH. Reopen your terminal afterward. Set `PREFIX` to change the installation
root. Generated `.cmd` files resolve Python through PATH; PowerShell execution
policy changes and administrator privileges are not required. Keep the checkout
at the same path when using `--git`. Re-run the installer to update or change modes.

## Diagnostics

```sh
proxy487ctl diagnose
proxy487ctl diagnose --speed --megabytes 10
proxy487ctl diagnose --speed --compare
```

Checks the selected proxy; speed measurement is optional (10, 25 or 50 MB each way).
`--compare` also tests a direct connection. Diagnostics require curl 8.4+ with TLS
and HTTPS-proxy support; HTTP/2 depends on the curl build.

## Development

```sh
python3 -m unittest discover -s tests -v
sh -n install.sh
uvx --from ruff==0.17.3 ruff check .
uvx --from ruff==0.17.3 ruff format --check .
```

On Windows, run the same suite with:

```powershell
python -m unittest discover -s tests -v
```

The suite tests installed commands by name in cmd and PowerShell, arguments and
exit codes, copy/Git installation, user PATH updates and process locking. Tests
use temporary directories and mock registry writes; your user PATH is unchanged.
POSIX installer tests are skipped on Windows. CI runs Python 3.10 and 3.14 on
Windows, Linux and macOS.

## License

See [LICENSE](LICENSE). Icon from [MegaProxyServer](https://github.com/andre487/MegaProxyServer).
