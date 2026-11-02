# Proxy transport audit — 2026-11-02

## Confirmed locally

- Original wrappers crashed without arguments; an empty file became an empty proxy URL.
  Validation now fails before exec, without echoing credentials.
- HTTP and HTTPS assignments were consistent: an `https://` proxy URL is correct for a TLS
  CONNECT proxy. Renaming it to `http://` would change the transport and can expose credentials.
- Explicit WebSocket proxy variables were not overwritten or removed, allowing stale WS_PROXY /
  WSS_PROXY to disagree with HTTP_PROXY. Both wrappers now handle them in both cases.
- The original proxy wrapper replaced the caller's bypass list. It now preserves explicit lists.
  NO_PROXY CIDR interpretation is client-dependent; loopback literals are included in defaults.
- `gh repo list` through the current HTTPS proxy returned a malformed HTTP response containing
  HTTP/2 frame bytes. The same request with `GODEBUG=http2client=0` succeeded. This isolates a
  protocol interoperability issue on that path, not an invalid GitHub token. Use this scoped
  workaround for gh diagnostics; the wrapper deliberately does not disable HTTP/2 globally.
- Local MegaProxyServer GOST templates advertise `alpn: [h2, http/1.1]`. That is a candidate
  to investigate against the deployed listener, not proof that this exact template is deployed
  or that advertising h2 alone is incorrect. No server configuration was changed.
- Codex daemon logs contained repeated `failed to connect to Responses WebSocket` with
  `stage=Unknown`. They do not identify TLS, CONNECT, authentication or Upgrade as the cause.

## Codex: what is and is not established

The [official advanced configuration guide](https://learn.chatgpt.com/docs/config-file/config-advanced)
explains provider configuration. Current upstream
[WebSocket connector](https://github.com/openai/codex/blob/main/codex-rs/websocket-client/src/lib.rs)
uses application-resolved outbound proxy policy. Do not assume every Codex version consults
WS_PROXY/WSS_PROXY, or that an environment change reaches an already-running daemon.

Start a new process under `proxy487`; restart persistent app/daemon processes through their
normal lifecycle before comparing. Check the installed version and its proxy policy.
A successful HTTPS request does not test a WebSocket Upgrade. Compare the same destination
with TLS-to-proxy HTTP/1.1 and h2, then test authenticated CONNECT and WebSocket Upgrade with
that client's supported diagnostics. A 401 from an unauthenticated endpoint only proves
reachability, not a successful authenticated WebSocket session.

The HTTP/2 failure is reproducible; the causal link to Codex reconnect / HTTPS fallback remains
unconfirmed. An end-to-end authenticated Codex session and deployed proxy logs are still needed.
Do not disable TLS verification, downgrade proxy encryption or force HTTPS fallback as a generic fix.
