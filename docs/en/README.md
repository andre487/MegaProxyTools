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

### Windows

Install or update from Windows PowerShell 5.1+ or PowerShell 7:

```powershell
irm https://raw.githubusercontent.com/andre487/MegaProxyTools/main/win/install.ps1 | iex
```

The loader downloads an archive, runs `install.cmd` and removes temporary files.
Repeat the command to update; settings are retained. For a persistent Git checkout:

```powershell
$env:INSTALL_FROM_GIT = '1'
irm https://raw.githubusercontent.com/andre487/MegaProxyTools/main/win/install.ps1 | iex
Remove-Item Env:INSTALL_FROM_GIT
```

This clones into `PREFIX\src\MegaProxyTools` and generates wrappers pointing there.
Repeated installation fetches `MEGAPROXY_TOOLS_REF` (default `main`) and updates
through fast-forward. Dirty, unrelated or diverged checkouts stop the update.
`MEGAPROXY_TOOLS_REF` also selects the ordinary archive version; use the same ref
in the loader URL when selecting a different version of the loader itself.

Download and extract the complete repository, or clone it. From PowerShell or cmd:

```powershell
.\install.cmd
# Optional: run directly from the current Git checkout
.\install.cmd --git
```

Python 3.10+ is required. The installer checks `python`, then `py -3`, and prints a
winget installation command if neither works. `--git` checks Git too; it does not
fetch or change the checkout. Ordinary installation copies the runtime and scripts;
`--git` generates wrappers pointing to this checkout, so local edits apply immediately.
Keep the checkout at the same path while using that mode.

The default root is `%LOCALAPPDATA%\MegaProxyTools`; set `PREFIX` to override it.
The installer adds its `bin` directory to the user PATH without administrator rights.
Reopen your terminal afterward. Python is resolved through PATH when each `.cmd`
command runs. PowerShell execution policy changes are not required.
Repeat installation to update or switch modes; configuration is preserved.
To uninstall, remove the installation directory and its user PATH entry.
Use `curl.exe` in PowerShell to avoid the Windows PowerShell `curl` alias.
POSIX permission modes such as 0600 are not Windows ACLs; keep configuration private
using Windows file permissions.

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

`proxy487` also defaults `NODE_USE_ENV_PROXY=1`. An inherited value or a value in
`default.env` takes precedence (for example, `NODE_USE_ENV_PROXY=0` disables it).
Node.js reads the flag on startup; explicitly configured agents/dispatchers can
override this behavior. `noproxy487` removes the flag along with the proxy variables.

| Runtime/client | Extra configuration |
| --- | --- |
| [Node.js](https://nodejs.org/en/learn/http/enterprise-network-configuration) | `NODE_USE_ENV_PROXY=1`: `fetch` on 22.21.0/24.0.0+, `http`/`https` on 22.21.0/24.5.0+. Older versions need application configuration. Built-in proxy support accepts HTTP/HTTPS proxies, not SOCKS. |
| [Python urllib](https://docs.python.org/3/library/urllib.request.html#urllib.request.ProxyHandler), [Requests](https://requests.readthedocs.io/en/latest/user/advanced/#proxies) | Read proxy variables by default; no extra flag. This does not apply to all Python HTTP clients. |
| [Go net/http](https://pkg.go.dev/net/http#DefaultTransport) | Default transport reads proxy variables; no extra flag. A custom transport can behave differently. |
| [Modern .NET HttpClient](https://learn.microsoft.com/en-us/dotnet/api/system.net.http.httpclient.defaultproxy) | Default proxy reads environment variables; no extra flag. Explicit handler settings can override it. |
| [Bun fetch](https://bun.com/docs/runtime/networking/fetch) | Reads proxy variables by default; no extra flag. |
| [Java](https://docs.oracle.com/en/java/javase/21/docs/api/java.base/java/net/doc-files/net-properties.html) | Usually requires JVM properties such as `http.proxyHost`/`https.proxyHost` or client configuration. `java.net.useSystemProxies=true` enables OS settings, not a general mapping of our environment variables. |

Protocol support, authentication and bypass rules depend on the individual client.
The wrapper cannot force a client that ignores proxy variables to use a proxy.

`noproxy487 [--] COMMAND [ARG ...]` clears these variables and NO_PROXY in every letter
case. It does not override application-specific files, OS settings, VPNs or transparent
proxies. Arguments, signals and the child exit status are preserved through exec.
The parent shell is unchanged. `proxy487ctl --help` and subcommand `--help` need no
user configuration. `proxy487` recognizes only the leading `--no-config-sync` option;
initialization and help belong to `proxy487ctl`.

A successful HTTPS request does not establish WebSocket support. Never paste proxy
URLs or environment dumps into issues. Never replace `https://` with `http://` unless
the endpoint actually serves plaintext HTTP.

## Diagnostics and optional speed measurement

```sh
proxy487ctl diagnose
proxy487ctl --no-config-sync diagnose
proxy487ctl diagnose --speed --megabytes 10
proxy487ctl diagnose --speed --megabytes 25 --compare
proxy487ctl diagnose --http-version 1.1
proxy487ctl diagnose --http-version 2
```

The active profile name, ID and credential-free endpoint are printed first.
The default checks only the selected proxy: an HTTPS request to example.com,
certificate verification, DNS/TCP/connection-setup timings, external IP and country.
HTTPS proxies must complete CONNECT; SOCKS5 uses proxy-side destination DNS.
Cloudflare trace is tried first; IP/country fallbacks match AndroidMegaProxy's
providers and are validated before display. Country lookup failure is nonfatal;
HTTPS or IP lookup failure gives exit status 1.

`--speed` adds three latency probes (median request TTFB after connection setup),
a download and an upload through Cloudflare. `--megabytes` selects 10, 25 or 50
**decimal MB per direction**, default 10. Without `--speed`, no bulk transfer runs.
`--compare` explicitly adds a direct route with inherited proxy settings disabled;
with speed enabled it transfers twice the per-route amount (40 MB total by default).
The selected profile and configuration are never changed by the measurements.
Usual startup subscription refresh still applies; use the global `--no-config-sync`
to skip it.

The system curl must be 8.4+ for bounded transfers, support TLS and, for HTTPS
profiles, HTTPS-proxy. HTTP/2 requires that curl feature. `--http-version 2` requests
HTTP/2 with curl's HTTP/1.1 fallback; default `auto` uses curl negotiation. Actual
HTTP/TLS versions are reported where observed. These checks use TCP HTTPS/SOCKS5;
there are no Android VPN, QUIC/HTTP3, UDP relay or TLS-fingerprint tests.

Credentials are supplied to curl through stdin, never command arguments. User
curlrc and inherited proxy/bypass variables are disabled so a successful check
cannot silently bypass the selected proxy. TLS verification stays enabled and
redirects are not followed. Normal responses are capped at 16 KiB; downloads must
match the selected size and uploads send exactly that many zero bytes. Requests
have a 10-second connect timeout and 10-second total limit (120 seconds per bulk
transfer). Temporary private files are removed after use. Raw curl errors and
response bodies are not printed; failures report only a sanitized category/status.
Exit status is 0 on success, 1 on a failed check, or 130 on interruption.

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
