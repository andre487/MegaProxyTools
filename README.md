# MegaProxyTools

<p align="center">
  <img src="docs/assets/icon-radius.svg" width="160" alt="MPX — MegaProxyTools">
</p>

Run individual commands with or without a proxy. Python standard library only; macOS and Linux.
Part of [MegaProxy](https://github.com/andre487/MegaProxyServer).

Documentation: **[English](docs/en/README.md)** · **[Русский](docs/ru/README.md)**

## Quick start

Requires Python 3.9+, Bash, curl and tar on macOS or Linux. No Git, pip, virtualenv or background service.

```sh
curl -fsSL https://raw.githubusercontent.com/andre487/MegaProxyTools/main/install.sh | bash
proxy487ctl import /path/to/MegaProxy.json
proxy487ctl list
proxy487ctl choose
proxy487 curl https://example.com
noproxy487 curl https://example.com
```

Run the same install command to update; configuration is retained.
Add `~/.local/bin` to PATH if needed. Settings use MegaProxyConfig v8 in
`~/.config/megaproxy-tools/config.json` (respects `XDG_CONFIG_HOME`). Existing
`proxy-list.txt` and `chosen` are migrated automatically, retaining the originals.
Import also accepts ProxyList, SuperProxy, FoxyProxy, legacy browser JSON and
ZeroOmega/SwitchyOmega fixed profiles; use `proxy487ctl import -` for stdin.
HTTPS and SOCKS5 are supported; incompatible protocols/settings produce a notice.
Stable IDs are merged, existing selection and eligible omitted passwords are retained.
A root `subscription` in imported JSON enables startup refresh, at most once per hour.
Use `proxy487 --no-config-sync COMMAND` or `proxy487ctl --no-config-sync list` to skip it.
Refresh logs go to stderr before command execution; failures retain saved settings.
Configuration contains secrets: never commit it.

## Development

```sh
python3 -m unittest discover -s tests -v
sh -n install.sh
```

## License

See [LICENSE](LICENSE). Icon from [MegaProxyServer](https://github.com/andre487/MegaProxyServer).
