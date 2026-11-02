# MegaProxyTools guide

<p align="center">
  <img src="../assets/icon-radius.svg" width="160" alt="MPX — MegaProxyTools">
</p>

## Installation

Install or update without Git:

```sh
curl -fsSL https://raw.githubusercontent.com/andre487/MegaProxyTools/main/install.sh | bash
```

Requires Python 3.10+, Bash, curl and tar on macOS or Linux. The installer downloads
an HTTPS source archive into a temporary directory, installs the commands and removes
the temporary files. Repeating it updates the tools and preserves configuration.
There are no third-party Python packages or background services.

For a custom prefix:

```sh
curl -fsSL https://raw.githubusercontent.com/andre487/MegaProxyTools/main/install.sh | PREFIX="$HOME/tools" bash
```

`MEGAPROXY_TOOLS_REF` selects an archive branch, tag or commit (default `main`);
set it on the `bash` side of the pipe. Use the same ref in the installer URL when
installing a different version of the installer itself.

### Git checkout installation

```sh
./install.sh --git
INSTALL_FROM_GIT=1 ./install.sh
curl -fsSL https://raw.githubusercontent.com/andre487/MegaProxyTools/main/install.sh | bash -s -- --git
curl -fsSL https://raw.githubusercontent.com/andre487/MegaProxyTools/main/install.sh | INSTALL_FROM_GIT=1 bash
```

This optional mode requires Git. From a repository, it creates absolute symlinks in
`PREFIX/bin` to that checkout's scripts; edits take effect immediately, including
library changes. It does not fetch or change the current repository. A piped
installer clones into `PREFIX/src/MegaProxyTools` (default `~/.local/src/MegaProxyTools`).
Repeating the piped Git installation fetches the selected `MEGAPROXY_TOOLS_REF`
(default `main`), checks it out, and performs a fast-forward-only update. Local
changes or an unrelated source directory stop the installation without replacement.
Libraries are read from the checkout. Keep that directory while using the links.
Running the default installation again replaces the links with standalone copies.

A local checkout also supports `./install.sh` without network access.
`PREFIX=/custom/path ./install.sh` installs commands into `/custom/path/bin` and
runtime files into `/custom/path/lib/megaproxy-tools`. Re-run after pulling updates.
To uninstall, remove the three commands and that library directory; settings remain.
You can also run `./bin/proxy487` and `./bin/proxy487ctl` from the complete checkout.

## Configuration location

Configuration lives in `$XDG_CONFIG_HOME/megaproxy-tools`, defaulting to
`~/.config/megaproxy-tools`. Empty or relative `XDG_CONFIG_HOME` uses the default.

`config.json` uses the [MegaProxyConfig version 8 contract](https://github.com/andre487/MegaProxyConfig).
It stores profiles with stable IDs and the selection in `activeProfileId`.
New application directories use mode 0700; JSON is written atomically with mode 0600.
Treat configuration as secret: it contains credentials.

`default.env` is a separate local file. `proxy487ctl init` creates the configuration
directory. Import a nonempty configuration next: the portable schema requires at
least one profile.

## Management and import

```sh
proxy487ctl import /path/to/MegaProxy.json
cat /path/to/MegaProxy.json | proxy487ctl import -
proxy487ctl list
proxy487ctl choose                   # prompt
proxy487ctl choose 2                 # number
proxy487ctl choose stable-profile-id # ID
proxy487ctl choose proxy.example.com # unique hostname
```

`list` marks the selected profile with `*` and displays labels and IDs, without
usernames or passwords. A hostname shared by multiple profiles is ambiguous; use
a number or ID instead. Without a saved selection, the first profile is used.

Only [MegaProxy JSON v8](https://github.com/andre487/MegaProxyConfig) is accepted,
including its schema identifiers `net.megaproxy487.config` and `dev.megaproxy.config`.
Input must be UTF-8 (an optional BOM is accepted), at most 1 MiB and 1,000 profiles.
Both manual import and subscription refresh use this same format and validation.
Other JSON structures, older configuration versions and text proxy lists are rejected.

Validation uses pinned MegaProxyConfig schemas offline with stdlib. Source revision
and SHA-256 hashes are recorded in `lib/megaproxy-tools/config-schema/schema-lock.json`.
The validator supports the keywords in that pinned schema rather than arbitrary
JSON Schema documents.

### Merge rules

MegaProxy JSON imports update matching stable IDs and append new IDs. Existing
profile order is retained; absent profiles are not removed. The current selection,
including an implicit first-profile selection, is retained. On the first import,
`activeProfileId` is used if compatible. Import never starts a command or connects.

An omitted password retains a saved password only when type, normalized host, port
and username are unchanged. An explicit empty password clears it. A changed recipient
never inherits the previous password. Incomplete authenticated SOCKS5 profiles may be
stored, but execution requires both credentials or neither. Duplicate IDs, missing
active references and invalid known fields reject the import. Invalid imports leave
existing JSON unchanged; unsupported profiles are skipped with a warning. Optional
platform fields and unknown keys are reported and discarded, not retained for export.
Document-level `routing.bypassLocalNetworks` is applied when explicitly supplied;
otherwise the local preference is retained.

### Transport support

Only HTTPS and SOCKS5 profiles can be executed through this portable configuration.
SOCKS5 is exported to child environment variables as `socks5h://` for proxy-side DNS;
the child must support it. HTTPS uses `https://` and retains TLS to the proxy.
SSH, Jump, MASQUE and profiles requiring invalid-certificate acceptance are explicitly
skipped, never flattened into another transport. HTTP is not a portable
MegaProxyConfig protocol; use an HTTPS endpoint. TLS fingerprints, HTTP/3 preferences,
DNS settings, knock, per-app/domain routing and browser settings are not implemented
and produce an import notice.

## Configuration subscriptions

Import a MegaProxy JSON document containing a root `subscription` object:

```json
"subscription": {
  "url": "https://configs.example.com/MegaProxy.json",
  "fallbackUrls": ["https://backup.example.com/MegaProxy.json"],
  "username": "reader",
  "password": "example",
  "intervalMinutes": 60,
  "enabled": true
}
```

Only `url` is required. Credentials and backups are optional. Import retains this
object and immediately checks it unless opted out. Both `proxy487` and `proxy487ctl`
check overdue subscriptions before running their command. Help and invalid invocations
do not fetch. There is no background service. Checks run at most once per hour across
both commands and concurrent processes; larger `intervalMinutes` is honored, smaller
values are clamped to 60. Failed attempts count too. `enabled: false` pauses checks.

```sh
proxy487 --no-config-sync curl https://example.com
proxy487 --no-config-sync COMMAND ARG
proxy487ctl --no-config-sync list
proxy487ctl --no-config-sync import MegaProxy.json
```

The flag must precede the command/subcommand. It is consumed by the utility; any
occurrence after the child command belongs to that child. `noproxy487` never syncs.
Changes are logged to stderr before execution: source index, counts of added/changed/
removed profiles, selection changes, local-network bypass and subscription-source
changes. Credentials, tokens, source URLs and response bodies are not logged. A failed
download, validation or save keeps the previous working configuration and reports an
error, then the requested command continues with saved settings.

Downloads follow inherited network/proxy environment settings. HTTPS certificate
verification is mandatory; redirects are rejected. The primary and up to seven
backups are tried in order, stopping after the first valid applied snapshot. Responses
must be HTTP 200, UTF-8 and at most 1 MiB; compression is not requested or accepted.
Requests use a 10-second socket timeout and a 20-second body budget checked between
reads. Headers identify `X-MegaProxy-Client: megaproxy_tools` and the development
application version `X-MegaProxy-Version: 0+unreleased`. Optional UTF-8 Basic Auth is
sent only as origin authentication, separately from proxy credentials.

A refresh replaces subscription-owned profiles and removes owned profiles absent
from the new snapshot. Separately imported local profiles remain. Profiles are
reconciled by stable MegaProxy IDs. A canonical ID colliding with a separate local
profile rejects that source. Selection is preserved while present; when removed,
the downloaded active profile is preferred, then the first compatible feed profile.
Password preservation follows the manual merge rules.

Importing a root subscription adopts that import's profiles into the subscription.
A manually edited config with no saved subscription state initially adopts its
profiles. Manual imports without `subscription` retain the subscription; explicit
null unsubscribes. An omitted subscription password is preserved only for the same
normalized primary URL and username. Downloaded documents may replace primary/backup
URLs, but retain local credentials, interval and pause state. Missing/null subscription
in a refresh keeps the source list. Use sources trusted to receive those credentials,
including any replacements supplied by the source operator.

Timestamps, owned IDs and last success/error are stored privately under
`$XDG_STATE_HOME/megaproxy-tools/config-sync-<config-path-hash>.json`, defaulting to
`~/.local/state/megaproxy-tools/`. Relative/empty `XDG_STATE_HOME` uses the default.
The state is separate from portable configuration. A configuration lock coordinates
imports, selection and refresh; interactive selection releases it while waiting.

## Running commands

`proxy487 [--no-config-sync] COMMAND [ARG ...]` assigns lowercase and uppercase HTTP_PROXY,
HTTPS_PROXY, ALL_PROXY, WS_PROXY and WSS_PROXY for the child only. Existing `no_proxy`
takes precedence over `NO_PROXY`, including empty values. Otherwise local bypass
(default true) includes localhost, loopback and 192.168/16; false uses an empty list.
CIDR support varies by client. WebSocket environment variables are not universal.

`noproxy487 [--] COMMAND [ARG ...]` clears these variables and NO_PROXY in every letter
case. It does not override application-specific files, OS settings, VPNs or transparent
proxies. Arguments, signals and the child exit status are preserved through exec.
The parent shell is unchanged. `proxy487ctl --help` and subcommand `--help` need no
user configuration. `proxy487` recognizes only the leading `--no-config-sync` option;
initialization and help belong to `proxy487ctl`.

A successful HTTPS request does not establish WebSocket support. Never paste proxy
URLs or environment dumps into issues. Never replace `https://` with `http://` unless
the endpoint actually serves plaintext HTTP.

## Optional environment defaults

`~/.config/megaproxy-tools/default.env` supplies local defaults for `proxy487`:

```dotenv
GODEBUG=http2client=0
```

Use literal `NAME=VALUE` lines; blank lines and whole-line `#` comments are ignored.
Whitespace around names and values is trimmed. Quotes, `export`, interpolation and
shell commands are not interpreted. Existing environment variables take precedence;
proxy URLs always come from the selected profile. Invalid entries fail before execution.
This file is not portable JSON and is not imported or loaded by `noproxy487`.
Keep it private with `chmod 600`.
