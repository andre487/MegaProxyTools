# MegaProxyTools

<p align="center">
  <img src="docs/assets/icon-radius.svg" width="160" alt="MPX — MegaProxyTools">
</p>

Run individual commands with or without a proxy. Python standard library only; macOS and Linux.
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

## License

See [LICENSE](LICENSE). Icon from [MegaProxyServer](https://github.com/andre487/MegaProxyServer).
