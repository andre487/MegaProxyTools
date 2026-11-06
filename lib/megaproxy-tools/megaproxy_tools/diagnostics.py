"""Bounded HTTPS/SOCKS diagnostics and opt-in Cloudflare speed measurements."""

import ipaddress
import json
import math
import os
import pathlib
import re
import shutil
import statistics
import subprocess as sp
import tempfile

from . import config as configuration

TRACE_URL = "https://speed.cloudflare.com/cdn-cgi/trace"
SPEED_ORIGIN = "https://h3.speed.cloudflare.com"
IP_URLS = ("https://ifconfig.me/ip", "https://api.ipify.org/", "https://icanhazip.com/")
COUNTRY_URLS = (
    "https://ifconfig.co/country-iso",
    "https://ipapi.co/country_code/",
    "https://api.country.is/",
)
PROXY_KEYS = {
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
    "ws_proxy",
    "wss_proxy",
}


class ProbeError(ValueError):
    def __init__(self, message: str, metrics: dict | None = None):
        super().__init__(message)
        self.metrics = metrics or {}


def curl_command(http_version: str, proxy: str | None) -> str:
    executable = shutil.which("curl")

    if executable is None:
        raise ValueError("Diagnostics require curl 8.4 or newer")

    result = sp.run(
        [executable, "--disable", "--version"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    version = re.match(r"curl (\d+)\.(\d+)\.(\d+)", result.stdout)

    if (
        result.returncode
        or not version
        or tuple(map(int, version.groups())) < (8, 4, 0)
    ):
        raise ValueError("Diagnostics require curl 8.4 or newer for bounded transfers")

    features = next(
        (
            line.split()[1:]
            for line in result.stdout.splitlines()
            if line.startswith("Features:")
        ),
        [],
    )

    if http_version == "2" and "HTTP2" not in features:
        raise ValueError("This curl build does not support HTTP/2")

    if proxy and proxy.startswith("https://") and "HTTPS-proxy" not in features:
        raise ValueError("This curl build does not support HTTPS proxies")

    return executable


def number(metrics: dict, key: str) -> float:
    value = metrics.get(key, 0)

    if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ProbeError("curl returned invalid measurement data")

    return float(value)


def request(
    executable: str,
    proxy: str | None,
    url: str,
    http_version: str,
    *,
    limit: int = 16 * 1024,
    read_body: bool = True,
    upload: pathlib.Path | None = None,
    timeout: int = 10,
) -> tuple[dict, bytes]:
    # Credentials go only through stdin, never process arguments, output or curlrc.
    escaped = (proxy or "").replace("\\", "\\\\").replace('"', '\\"')
    settings = f'proxy = "{escaped}"\nnoproxy = ""\n'
    env = {
        key: value for key, value in os.environ.items() if key.lower() not in PROXY_KEYS
    }

    with tempfile.TemporaryDirectory(prefix="megaproxy-diagnostics-") as temporary:
        output = pathlib.Path(temporary) / "response"
        arguments = [
            executable,
            "--disable",
            "--config",
            "-",
            "--silent",
            "--show-error",
            "--fail",
            "--proto",
            "=https",
            "--connect-timeout",
            "10",
            "--max-time",
            str(timeout),
            "--max-filesize",
            str(limit),
            "--header",
            "Accept-Encoding: identity",
            "--user-agent",
            "MegaProxyTools diagnostics",
            "--output",
            str(output) if read_body else os.devnull,
            "--write-out",
            "%{json}",
            "--url",
            url,
        ]

        match http_version:
            case "1.1":
                arguments.append("--http1.1")
            case "2":
                arguments.append("--http2")

        if upload is not None:
            arguments.extend(
                [
                    "--upload-file",
                    str(upload),
                    "--request",
                    "POST",
                    "--header",
                    "Content-Type: application/octet-stream",
                ]
            )

        try:
            result = sp.run(
                arguments,
                input=settings,
                env=env,
                text=True,
                capture_output=True,
                timeout=timeout + 5,
            )
        except sp.TimeoutExpired:
            raise ProbeError("request timed out") from None

        try:
            metrics = json.loads(result.stdout)
        except ValueError:
            raise ProbeError("curl returned invalid measurement data") from None

        if not isinstance(metrics, dict):
            raise ProbeError("curl returned invalid measurement data")

        status = int(number(metrics, "http_code"))
        connect = int(number(metrics, "http_connect"))

        if result.returncode or not 200 <= status < 300:
            if connect == 407:
                reason = "proxy authentication rejected (HTTP 407)"
            elif connect and connect != 200:
                reason = f"proxy CONNECT returned HTTP {connect}"
            elif number(metrics, "proxy_ssl_verify_result"):
                reason = "proxy TLS certificate verification failed"
            elif number(metrics, "ssl_verify_result"):
                reason = "destination TLS certificate verification failed"
            elif status >= 300:
                reason = (
                    f"destination returned HTTP {status} (redirects are not followed)"
                )
            else:
                reason = {
                    5: "proxy DNS lookup failed",
                    6: "destination DNS lookup failed",
                    7: "TCP connection failed",
                    28: "request timed out",
                    35: "TLS handshake failed",
                    60: "TLS certificate verification failed",
                    63: "response exceeded size limit",
                    67: "authentication rejected",
                    97: "SOCKS handshake failed",
                }.get(result.returncode, "proxy or HTTPS transport failed")
            raise ProbeError(reason, metrics)

        if number(metrics, "ssl_verify_result") or number(
            metrics, "proxy_ssl_verify_result"
        ):
            raise ProbeError("TLS certificate verification failed", metrics)

        if read_body:
            with output.open("rb") as stream:
                body = stream.read(limit + 1)

            if len(body) > limit:
                raise ProbeError("response exceeded size limit", metrics)
        else:
            body = b""

    return metrics, body


def parse_ip(value: str) -> str | None:
    if "%" in value:
        return None

    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def parse_country(value: str) -> str | None:
    value = value.strip().upper()
    return value if re.fullmatch(r"[A-Z]{2}", value) else None


def identity(
    executable: str, proxy: str | None, http_version: str
) -> tuple[str, str | None, str | None]:
    ip = country = tls = None
    print("  Exit identity: checking Cloudflare trace...", flush=True)

    try:
        _, body = request(executable, proxy, TRACE_URL, http_version)
        trace = dict(
            line.split("=", 1)
            for line in body.decode("utf-8").splitlines()
            if "=" in line
        )
        ip, country = parse_ip(trace.get("ip", "")), parse_country(trace.get("loc", ""))
        tls = trace.get("tls") if trace.get("tls") in ("TLSv1.2", "TLSv1.3") else None
    except (ProbeError, UnicodeError):
        pass

    if ip is None:
        for index, url in enumerate(IP_URLS, 1):
            print(f"  Exit IP: trying fallback provider {index}...", flush=True)

            try:
                _, body = request(executable, proxy, url, http_version)
                ip = parse_ip(body.decode("utf-8"))
            except (ProbeError, UnicodeError):
                continue

            if ip is not None:
                break

    if country is None:
        for index, url in enumerate(COUNTRY_URLS, 1):
            print(f"  Country: trying fallback provider {index}...", flush=True)

            try:
                _, body = request(executable, proxy, url, http_version)
                value = body.decode("utf-8")
                if url == "https://api.country.is/":
                    value = json.loads(value).get("country", "")
                country = parse_country(value)
            except (ProbeError, ValueError, AttributeError):
                continue

            if country is not None:
                break

    if ip is None:
        raise ProbeError("all external IP providers failed")

    return ip, country, tls


def speed(
    executable: str, proxy: str | None, http_version: str, megabytes: int
) -> dict:
    latencies = []

    for _ in range(3):
        metrics, _ = request(
            executable,
            proxy,
            SPEED_ORIGIN + "/__down?bytes=0",
            http_version,
            limit=1024,
            read_body=False,
        )
        latencies.append(
            max(
                0,
                number(metrics, "time_starttransfer")
                - number(metrics, "time_pretransfer"),
            )
            * 1000
        )

    result = {"latency": statistics.median(latencies)}
    print(
        f"  Request latency: {result['latency']:.1f} ms (median of 3, connection setup excluded)",
        flush=True,
    )
    size = megabytes * 1_000_000
    print(f"  Download: measuring {megabytes} MB...", flush=True)
    metrics, _ = request(
        executable,
        proxy,
        f"{SPEED_ORIGIN}/__down?bytes={size}",
        http_version,
        limit=size,
        read_body=False,
        timeout=120,
    )

    if number(metrics, "size_download") != size or number(metrics, "time_total") <= 0:
        raise ProbeError("download size or timing mismatch")

    result["download"] = size * 8 / number(metrics, "time_total") / 1_000_000
    print(f"  Download: {result['download']:.2f} Mbps", flush=True)
    print(f"  Upload: measuring {megabytes} MB...", flush=True)

    with tempfile.TemporaryDirectory(prefix="megaproxy-speed-") as temporary:
        upload = pathlib.Path(temporary) / "zeros"
        with upload.open("wb") as stream:
            stream.truncate(size)
        metrics, _ = request(
            executable,
            proxy,
            SPEED_ORIGIN + "/__up",
            http_version,
            upload=upload,
            read_body=False,
            timeout=120,
        )

    if number(metrics, "size_upload") != size or number(metrics, "time_total") <= 0:
        raise ProbeError("upload size or timing mismatch")

    result["upload"] = size * 8 / number(metrics, "time_total") / 1_000_000
    print(f"  Upload: {result['upload']:.2f} Mbps", flush=True)
    return result


def show_timings(metrics: dict) -> None:
    dns = number(metrics, "time_namelookup")
    tcp = max(0, number(metrics, "time_connect") - dns)
    setup = number(metrics, "time_pretransfer")
    print(
        f"  DNS: {dns * 1000:.1f} ms; TCP: {tcp * 1000:.1f} ms; "
        f"connection setup: {setup * 1000:.1f} ms",
        flush=True,
    )


def diagnose(
    profile: dict,
    *,
    measure_speed: bool = False,
    megabytes: int = 10,
    compare: bool = False,
    http_version: str = "auto",
) -> int:
    if megabytes not in (10, 25, 50) or http_version not in ("auto", "1.1", "2"):
        raise ValueError("Invalid diagnostic options")

    endpoint = profile["proxy"]
    host = endpoint["host"]
    host = f"[{host}]" if ":" in host else host
    label = json.dumps(profile.get("name") or "Unnamed", ensure_ascii=True)
    identifier = json.dumps(profile["id"], ensure_ascii=True)
    print(
        f"Active profile: {label} [{identifier}] {endpoint['type']}://{host}:{endpoint['port']}",
        flush=True,
    )

    proxy = configuration.profile_url(profile)
    executable = curl_command(http_version, proxy)
    routes = [("Proxy", proxy)]

    if compare:
        routes.insert(0, ("Direct", None))

    if measure_speed:
        print(
            f"Speed test enabled: {megabytes} MB download + {megabytes} MB upload per route.",
            flush=True,
        )

    failed = False
    try:
        for label, route in routes:
            print(f"{label}: checking HTTPS...", flush=True)
            try:
                metrics, _ = request(
                    executable,
                    route,
                    "https://example.com/",
                    http_version,
                    read_body=False,
                )
                protocol = metrics.get("http_version", "unknown")
                protocol = (
                    protocol if protocol in ("1.0", "1.1", "2", "3") else "unknown"
                )
                print(
                    f"  HTTPS: OK (HTTP/{protocol}, certificates verified)", flush=True
                )
                show_timings(metrics)

                if route and route.startswith("https://"):
                    if number(metrics, "http_connect") != 200:
                        raise ProbeError("HTTPS proxy CONNECT was not confirmed")
                    print("  Proxy TLS and CONNECT: OK", flush=True)
                ip, country, tls = identity(executable, route, http_version)
                print(
                    f"  Exit IP: {ip}; country: {country or 'unavailable'}"
                    + (f"; TLS: {tls}" if tls else ""),
                    flush=True,
                )
                if measure_speed:
                    speed(executable, route, http_version, megabytes)
            except ProbeError as error:
                failed = True
                print(f"  FAILED: {error}", flush=True)

                if error.metrics:
                    show_timings(error.metrics)
    except KeyboardInterrupt:
        print("Diagnostics interrupted", flush=True)
        return 130

    return 1 if failed else 0
