# MegaProxyTools guide

## Installation and migration

Follow the [quick start](../../README.md). `PREFIX=/custom/path ./install.sh` installs into
`/custom/path/bin`. Re-run after pulling updates. Remove the two installed files to uninstall;
configuration is retained. You can also run `./bin/proxy487` directly from the checkout.
Python 3.9+ is the only runtime dependency. Installation performs no network requests.

The tools moved from andre487/dotfiles. Existing `~/.proxy487/proxy-list.txt` and
`~/.proxy487/chosen` remain supported. Remove old copies from an earlier PATH directory
(or use the forwarding wrappers in updated dotfiles). Run `command -v proxy487` to check.

## Configuration and execution

`proxy487 --init` creates a private configuration file without overwriting an existing one.
Add one URL per line. Blank lines and whole-line `#` comments are ignored.
Supported schemes: `http`, `https`, `socks5`, `socks5h`; an explicit port is required.
The target program must support the selected proxy type. HTTPS means TLS to the proxy;
`HTTPS_PROXY` does **not** imply that the proxy URL must start with `https`.
Never change `https://` to `http://` unless the endpoint actually serves plaintext HTTP.
Percent-encode reserved characters in credentials. Query strings and fragments are removed
for compatibility with exported profile labels. Invalid URLs fail before executing the command.

The first proxy is selected unless `chosen` contains its hostname. A missing selected host
is an error. Configuration is read on each invocation; no discovery, retry or daemon startup.

`proxy487 [--] COMMAND [ARG ...]` sets lowercase and uppercase HTTP_PROXY, HTTPS_PROXY,
ALL_PROXY, WS_PROXY and WSS_PROXY for the child only. Existing `no_proxy` takes precedence
over `NO_PROXY`; otherwise defaults bypass localhost, loopback and 192.168/16. CIDR handling
varies by client; explicit loopback addresses are included. Other private networks are not
silently bypassed. Existing explicit bypass lists, including empty lists, are preserved.
WebSocket variables serve clients that support them; client support is not universal.

`noproxy487 [--] COMMAND [ARG ...]` clears these variables and NO_PROXY in every letter case.
It does not override application-specific proxy files, OS proxy settings, VPNs or transparent proxies.
Both tools preserve arguments, signals and the command exit status through exec.
They do not modify the parent shell. `--help` needs no configuration.

## Transport audit

See [transport findings](../transport-audit.md). A successful HTTPS request does not establish
WebSocket support. Credentials stay in the child environment; never paste environment dumps
or proxy URLs into issues. Avoid commands that print the complete environment.
