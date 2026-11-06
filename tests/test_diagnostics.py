import contextlib
import copy
import io
import json
import os
import pathlib
import runpy
import sys
import tempfile
import types
import unittest
import unittest.mock as mock

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parents[1] / "lib/megaproxy-tools")
)

import megaproxy_tools as megaproxy

ROOT = pathlib.Path(__file__).resolve().parents[1]


def metrics(**values):
    return {
        "http_code": 200,
        "http_connect": 200,
        "http_version": "2",
        "ssl_verify_result": 0,
        "proxy_ssl_verify_result": 0,
        "time_namelookup": 0.01,
        "time_connect": 0.03,
        "time_pretransfer": 0.1,
        "time_starttransfer": 0.15,
        "time_total": 1,
    } | values


class Diagnostics(unittest.TestCase):
    def setUp(self):
        self.profile = {
            "id": "test",
            "proxy": {
                "type": "HTTPS",
                "host": "proxy.example",
                "port": 443,
                "username": "reader",
                "password": "private-secret",
            },
        }
        self.proxy = megaproxy.config.profile_url(self.profile)

    def test_request_hides_credentials_and_forces_route(self):
        calls = []

        def invoke(arguments, **kwargs):
            calls.append((arguments, kwargs))
            self.assertNotIn("private-secret", " ".join(arguments))
            self.assertEqual(arguments[1:4], ["--disable", "--config", "-"])
            self.assertNotIn("--location", arguments)
            self.assertFalse(
                any(
                    key.lower() in megaproxy.diagnostics.PROXY_KEYS
                    for key in kwargs["env"]
                )
            )
            path = pathlib.Path(arguments[arguments.index("--output") + 1])
            if os.name != "nt":
                self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
            path.write_bytes(b"ip=192.0.2.1\nloc=GB\n")
            return types.SimpleNamespace(
                returncode=0, stdout=json.dumps(metrics()), stderr="private-secret"
            )

        with (
            mock.patch.object(megaproxy.diagnostics.sp, "run", side_effect=invoke),
            mock.patch.dict(
                os.environ,
                {"HTTPS_PROXY": "wrong", "NO_PROXY": "*", "hTtP_PrOxY": "wrong"},
            ),
        ):
            data, body = megaproxy.diagnostics.request(
                "curl", self.proxy, "https://example.com/", "2"
            )
            self.assertEqual(data["http_code"], 200)
            self.assertIn(b"192.0.2.1", body)
            self.assertIn('proxy = "' + self.proxy, calls[-1][1]["input"])
            self.assertIn('noproxy = ""', calls[-1][1]["input"])
            megaproxy.diagnostics.request("curl", None, "https://example.com/", "1.1")
            self.assertIn('proxy = ""', calls[-1][1]["input"])
        self.assertFalse(
            pathlib.Path(calls[0][0][calls[0][0].index("--output") + 1]).exists()
        )

    def test_curl_capabilities_and_redacted_errors(self):
        version = types.SimpleNamespace(
            returncode=0, stdout="curl 8.7.1\nFeatures: HTTP2 HTTPS-proxy SSL\n"
        )
        with (
            mock.patch.object(
                megaproxy.diagnostics.shutil, "which", return_value="curl"
            ),
            mock.patch.object(megaproxy.diagnostics.sp, "run", return_value=version),
        ):
            self.assertEqual(
                megaproxy.diagnostics.curl_command("2", self.proxy), "curl"
            )
            version.stdout = "curl 8.3.0\nFeatures: HTTP2 HTTPS-proxy SSL\n"
            with self.assertRaisesRegex(ValueError, "8.4"):
                megaproxy.diagnostics.curl_command("auto", self.proxy)
            version.stdout = "curl 8.7.1\nFeatures: SSL\n"
            with self.assertRaisesRegex(ValueError, "HTTP/2"):
                megaproxy.diagnostics.curl_command("2", self.proxy)
        for code, data, expected in (
            (22, metrics(http_code=0, http_connect=407), "authentication rejected"),
            (60, metrics(http_code=0), "certificate"),
            (0, metrics(http_code=302), "HTTP 302"),
            (63, metrics(http_code=0), "size limit"),
        ):
            result = types.SimpleNamespace(
                returncode=code, stdout=json.dumps(data), stderr="private-secret"
            )
            with mock.patch.object(
                megaproxy.diagnostics.sp, "run", return_value=result
            ):
                with self.assertRaises(megaproxy.diagnostics.ProbeError) as failure:
                    megaproxy.diagnostics.request(
                        "curl", self.proxy, "https://example.com", "auto"
                    )
                self.assertIn(expected, str(failure.exception))
                self.assertNotIn("private-secret", str(failure.exception))

    def test_identity_uses_independent_proxied_fallbacks(self):
        self.assertIsNone(megaproxy.diagnostics.parse_ip("2001:db8::1%\x1b[31m"))
        calls = []

        def request(executable, proxy, url, version):
            self.assertEqual(proxy, self.proxy)
            calls.append(url)
            bodies = {
                megaproxy.diagnostics.TRACE_URL: b"ip=invalid\nloc=GB\ntls=TLSv1.3\n",
                megaproxy.diagnostics.IP_URLS[0]: b"bad IP",
                megaproxy.diagnostics.IP_URLS[1]: b"192.0.2.1\n",
            }
            return metrics(), bodies[url]

        with (
            mock.patch.object(megaproxy.diagnostics, "request", side_effect=request),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(
                megaproxy.diagnostics.identity("curl", self.proxy, "auto"),
                ("192.0.2.1", "GB", "TLSv1.3"),
            )
        self.assertEqual(len(calls), 3)
        with (
            mock.patch.object(
                megaproxy.diagnostics,
                "request",
                side_effect=megaproxy.diagnostics.ProbeError("failed"),
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            with self.assertRaisesRegex(
                megaproxy.diagnostics.ProbeError, "all external IP"
            ):
                megaproxy.diagnostics.identity("curl", self.proxy, "auto")

    def test_speed_has_bounded_sizes_correct_units_and_cleanup(self):
        transfers = []
        latencies = iter((0.03, 0.05, 0.09))

        def request(executable, proxy, url, version, **kwargs):
            self.assertEqual(proxy, self.proxy)
            if url.endswith("bytes=0"):
                return metrics(
                    time_pretransfer=0.01, time_starttransfer=next(latencies)
                ), b""
            if "upload" in kwargs:
                path = kwargs["upload"]
                transfers.append(path)
                self.assertEqual(path.stat().st_size, 10_000_000)
                with path.open("rb") as stream:
                    self.assertEqual(stream.read(32), bytes(32))
                return metrics(size_upload=10_000_000, time_total=4), b""
            self.assertEqual(kwargs["limit"], 10_000_000)
            self.assertIn("bytes=10000000", url)
            return metrics(size_download=10_000_000, time_total=2), b""

        with (
            mock.patch.object(megaproxy.diagnostics, "request", side_effect=request),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            result = megaproxy.diagnostics.speed("curl", self.proxy, "auto", 10)
        self.assertAlmostEqual(result["latency"], 40)
        self.assertEqual(result["download"], 40)
        self.assertEqual(result["upload"], 20)
        self.assertFalse(transfers[0].exists())

    def test_diagnose_default_comparison_failure_and_cancellation(self):
        self.profile["name"] = "Test \x1b[31m profile"
        before = copy.deepcopy(self.profile)
        output = io.StringIO()
        with (
            mock.patch.object(
                megaproxy.diagnostics, "curl_command", return_value="curl"
            ),
            mock.patch.object(
                megaproxy.diagnostics, "request", return_value=(metrics(), b"")
            ) as request,
            mock.patch.object(
                megaproxy.diagnostics,
                "identity",
                return_value=("192.0.2.1", "GB", "TLSv1.3"),
            ),
            mock.patch.object(megaproxy.diagnostics, "speed") as speed,
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(megaproxy.diagnostics.diagnose(self.profile), 0)
            speed.assert_not_called()
            self.assertEqual(request.call_args.args[1], self.proxy)
            self.assertNotIn("Direct:", output.getvalue())
            self.assertIn(
                'Active profile: "Test \\u001b[31m profile" ["test"] HTTPS://proxy.example:443',
                output.getvalue(),
            )
            self.assertNotIn("\x1b", output.getvalue())
            self.assertNotIn("private-secret", output.getvalue())
            self.assertEqual(
                megaproxy.diagnostics.diagnose(
                    self.profile, compare=True, measure_speed=True, megabytes=25
                ),
                0,
            )
            self.assertEqual(
                [call.args[1] for call in speed.call_args_list], [None, self.proxy]
            )
            request.side_effect = megaproxy.diagnostics.ProbeError(
                "proxy authentication rejected"
            )
            self.assertEqual(megaproxy.diagnostics.diagnose(self.profile), 1)
            request.side_effect = KeyboardInterrupt
            self.assertEqual(megaproxy.diagnostics.diagnose(self.profile), 130)
        self.assertEqual(self.profile, before)

    def test_control_dispatch_and_invalid_options(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": temporary}),
        ):
            folder = pathlib.Path(temporary) / "megaproxy-tools"
            megaproxy.config.atomic_write(
                folder / "config.json",
                {
                    "schema": megaproxy.config.SCHEMA_ID,
                    "version": 8,
                    "profiles": [self.profile],
                },
            )
            argv = [
                "proxy487ctl",
                "--no-config-sync",
                "diagnose",
                "--speed",
                "--megabytes",
                "25",
                "--compare",
                "--http-version",
                "1.1",
            ]
            with (
                mock.patch.object(sys, "argv", argv),
                mock.patch.object(
                    megaproxy.diagnostics, "diagnose", return_value=0
                ) as diagnose,
            ):
                with self.assertRaises(SystemExit) as status:
                    runpy.run_path(str(ROOT / "bin/proxy487ctl"), run_name="__main__")
                self.assertEqual(status.exception.code, 0)
                diagnose.assert_called_once_with(
                    self.profile,
                    measure_speed=True,
                    megabytes=25,
                    compare=True,
                    http_version="1.1",
                )
            for options in (("--megabytes", "500"), ("--http-version", "3")):
                with (
                    mock.patch.object(
                        sys, "argv", ["proxy487ctl", "diagnose", *options]
                    ),
                    contextlib.redirect_stderr(io.StringIO()),
                ):
                    with self.assertRaises(SystemExit) as status:
                        runpy.run_path(
                            str(ROOT / "bin/proxy487ctl"), run_name="__main__"
                        )
                    self.assertEqual(status.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
