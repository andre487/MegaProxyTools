# MegaProxyTools

<p align="center">
  <img src="docs/assets/icon-radius.svg" width="160" alt="MPX — MegaProxyTools">
</p>

Run individual commands with or without a proxy. Python standard library only; macOS and Linux.
Part of [MegaProxy](https://github.com/andre487/MegaProxyServer).

Documentation: **[English](docs/en/README.md)** · **[Русский](docs/ru/README.md)**

## Quick start

Requires Git, Python 3.9+ and a POSIX shell. No pip, virtualenv or background service.

```sh
git clone https://github.com/andre487/MegaProxyTools.git
cd MegaProxyTools
./install.sh
proxy487 --init
${EDITOR:-vi} ~/.proxy487/proxy-list.txt
proxy487 curl https://example.com
noproxy487 curl https://example.com
```

Add `~/.local/bin` to PATH if needed. Existing `~/.proxy487` settings work unchanged.
Put one proxy URL per line, e.g. `https://USER:URL_ENCODED_PASSWORD@proxy.example.com:443`.
Configuration contains secrets: never commit it.

## Development

```sh
python3 -m unittest discover -s tests -v
sh -n install.sh
```

## License

See [LICENSE](LICENSE). Icon from [MegaProxyServer](https://github.com/andre487/MegaProxyServer).
