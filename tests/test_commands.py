import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

BIN = pathlib.Path(__file__).resolve().parents[1] / "bin"
KEYS = ("http_proxy", "https_proxy", "all_proxy", "ws_proxy", "wss_proxy")


class Commands(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = pathlib.Path(self.temp.name)
        self.config = self.home / ".config" / "megaproxy-tools"
        self.config.mkdir(parents=True)
        self.env = dict(os.environ, HOME=str(self.home), NO_PROXY="internal.example")
        self.env.pop("no_proxy", None)
        self.env.pop("XDG_CONFIG_HOME", None)
        self.env.pop("XDG_STATE_HOME", None)

    def run_command(self, name, *args):
        return subprocess.run(
            [sys.executable, str(BIN / name), *args],
            env=self.env,
            text=True,
            capture_output=True,
        )

    def configure(self, *profiles, active=None):
        path = self.config / "config.json"
        path.write_text(json.dumps(self.portable(*profiles, active=active)))
        path.chmod(0o600)

    def probe(self, name):
        result = self.run_command(
            name,
            sys.executable,
            "-c",
            "import os,json; print(json.dumps(dict(os.environ)))",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_selection_environment_and_metadata(self):
        first = self.profile("first", host="first.example")
        second = self.profile(
            "second", host="second.example", username="user", password="p@ss"
        )
        second["name"] = "Second proxy"
        self.configure(first, second, active="second")
        env = self.probe("proxy487")

        for key in KEYS:
            self.assertEqual(env[key], "https://user:p%40ss@second.example:443")
            self.assertEqual(env[key.upper()], env[key])

        self.assertEqual(env["no_proxy"], "internal.example")

    def test_default_env(self):
        self.configure(self.profile("host", host="host.example"))
        defaults = self.config / "default.env"
        defaults.write_text(
            "# comment\n\nGODEBUG=http2client=0\nEMPTY=\nLITERAL=$(no-execution)=value\nhttp_proxy=http://wrong:80\n"
        )
        env = self.probe("proxy487")
        self.assertEqual(env["GODEBUG"], "http2client=0")
        self.assertEqual(env["EMPTY"], "")
        self.assertEqual(env["LITERAL"], "$(no-execution)=value")
        self.assertEqual(env["http_proxy"], "https://host.example:443")
        self.env["GODEBUG"] = "existing"
        self.assertEqual(self.probe("proxy487")["GODEBUG"], "existing")
        self.assertNotIn("LITERAL", self.probe("noproxy487"))
        defaults.write_text("BAD-NAME=secret\n")
        result = self.run_command("proxy487", "true")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("line 1", result.stderr)
        self.assertNotIn("secret", result.stderr)

    def test_clear_all_variants(self):
        for key in (*KEYS, "no_proxy"):
            self.env[key] = self.env[key.upper()] = "sentinel"

        env = self.probe("noproxy487")
        self.assertFalse(any(k.lower() in (*KEYS, "no_proxy") for k in env))

    def test_errors_and_no_secret_disclosure(self):
        for text in (
            "",
            "# comment\n",
            "https://user:secret@host:443",
            '{"password":"secret",',
            "[]",
        ):
            with self.subTest(text=text):
                (self.config / "config.json").write_text(text)
                result = self.run_command("proxy487", "true")
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("secret", result.stderr)
                self.assertNotIn("Traceback", result.stderr)

        self.configure(self.profile("host"), active="absent")
        self.assertNotEqual(self.run_command("proxy487", "true").returncode, 0)

    def test_init_is_private_and_preserves_config(self):
        self.config.rmdir()
        self.assertEqual(self.run_command("proxy487ctl", "init").returncode, 0)
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o700)
        self.configure(self.profile("host"))
        path = self.config / "config.json"
        before = path.read_bytes()
        self.assertEqual(self.run_command("proxy487ctl", "init").returncode, 0)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.read_bytes(), before)

    def test_xdg_configuration_location(self):
        self.configure(self.profile("default", host="default.example"))

        for value in ("", "relative/path"):
            self.env["XDG_CONFIG_HOME"] = value
            self.assertEqual(
                self.probe("proxy487")["https_proxy"], "https://default.example:443"
            )

        custom = self.home / "custom-config"
        self.env["XDG_CONFIG_HOME"] = str(custom)
        self.assertEqual(self.run_command("proxy487ctl", "init").returncode, 0)
        target = custom / "megaproxy-tools"
        self.assertEqual(target.stat().st_mode & 0o777, 0o700)
        self.assertFalse((target / "config.json").exists())
        self.assertNotEqual(self.run_command("proxy487", "true").returncode, 0)
        (target / "config.json").write_text(
            json.dumps(self.portable(self.profile("custom", host="custom.example")))
        )
        self.assertEqual(
            self.probe("proxy487")["https_proxy"], "https://custom.example:443"
        )

    def test_control_list_choose_and_init(self):
        self.assertEqual(self.run_command("proxy487ctl", "init").returncode, 0)
        self.configure(
            self.profile(
                "first", host="first.example", username="user", password="secret"
            ),
            self.profile("second", type="SOCKS5", host="second.example", port=1080),
        )
        result = self.run_command("proxy487ctl", "list")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("* 1 HTTPS://first.example:443", result.stdout)
        self.assertNotIn("user", result.stdout)
        self.assertNotIn("secret", result.stdout)

        for value in ("2", "second.example"):
            result = self.run_command("proxy487ctl", "choose", value)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                self.probe("proxy487")["https_proxy"], "socks5h://second.example:1080"
            )

        chosen = self.config / "config.json"
        self.assertEqual(chosen.stat().st_mode & 0o777, 0o600)

        for value in ("0", "3", "unknown", "https://user:secret@host:443"):
            result = self.run_command("proxy487ctl", "choose", value)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("secret", result.stderr)
            self.assertEqual(
                json.loads(chosen.read_text())["activeProfileId"],
                json.loads(chosen.read_text())["profiles"][1]["id"],
            )

        result = subprocess.run(
            [sys.executable, str(BIN / "proxy487ctl"), "choose"],
            input="1\n",
            env=self.env,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(chosen.read_text())["activeProfileId"],
            json.loads(chosen.read_text())["profiles"][0]["id"],
        )
        self.configure(
            self.profile("first", host="first.example"),
            self.profile("second", host="first.example", port=8443),
        )
        self.assertEqual(self.run_command("proxy487ctl", "choose", "2").returncode, 0)
        self.assertNotEqual(
            self.run_command("proxy487ctl", "choose", "first.example").returncode, 0
        )
        self.assertEqual(
            json.loads(chosen.read_text())["activeProfileId"],
            json.loads(chosen.read_text())["profiles"][1]["id"],
        )

        for args in (("unknown",), ("list", "extra"), ("choose", "1", "extra")):
            self.assertNotEqual(self.run_command("proxy487ctl", *args).returncode, 0)

    def import_text(self, data):
        text = data if isinstance(data, str) else json.dumps(data)
        return subprocess.run(
            [sys.executable, str(BIN / "proxy487ctl"), "import", "-"],
            input=text,
            env=self.env,
            text=True,
            capture_output=True,
        )

    def portable(self, *profiles, active=None):
        return {
            "schema": "net.megaproxy487.config",
            "version": 8,
            "profiles": list(profiles),
            "activeProfileId": active,
        }

    def profile(self, identifier, **proxy):
        return {
            "id": identifier,
            "proxy": {"type": "HTTPS", "host": "proxy.example", "port": 443} | proxy,
        }

    def test_megaproxy_json_import_and_percent_encoding(self):
        entry = self.profile("shared", username="u+ser", password="p@ss:word")
        entry |= {"name": "Тест", "countryCode": "GB"}
        document = self.portable(entry)
        result = self.import_text("\ufeff" + json.dumps(document, ensure_ascii=False))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("p@ss", result.stdout + result.stderr)
        stored = json.loads((self.config / "config.json").read_text())
        self.assertEqual(stored["profiles"][0]["name"], "Тест")
        self.assertEqual(
            self.probe("proxy487")["https_proxy"],
            "https://u%2Bser:p%40ss%3Aword@proxy.example:443",
        )
        document["schema"] = "dev.megaproxy.config"
        self.assertEqual(self.import_text(document).returncode, 0)
        self.assertEqual(
            len(json.loads((self.config / "config.json").read_text())["profiles"]), 1
        )

    def test_portable_merge_selection_order_and_secrets(self):
        a = self.profile("a", username="u", password="secret")
        b = self.profile("b", username="u", password="other")
        self.assertEqual(
            self.import_text(self.portable(a, b, active="b")).returncode, 0
        )
        incoming = self.portable(
            self.profile("b", username="u"), self.profile("c"), active="c"
        )
        incoming["routing"] = {"bypassLocalNetworks": False}
        result = self.import_text(incoming)
        self.assertEqual(result.returncode, 0, result.stderr)
        path = self.config / "config.json"
        config = json.loads(path.read_text())
        self.assertEqual([p["id"] for p in config["profiles"]], ["a", "b", "c"])
        self.assertEqual(config["activeProfileId"], "b")
        self.assertEqual(config["profiles"][1]["proxy"]["password"], "other")
        self.assertFalse(config["routing"]["bypassLocalNetworks"])
        self.assertEqual(self.import_text(incoming).returncode, 0)
        self.assertEqual(len(json.loads(path.read_text())["profiles"]), 3)
        self.assertEqual(
            self.import_text(
                self.portable(self.profile("b", username="u", password=""))
            ).returncode,
            0,
        )
        self.assertEqual(
            json.loads(path.read_text())["profiles"][1]["proxy"]["password"], ""
        )

        for key, value in (
            ("host", "different.example"),
            ("port", 8443),
            ("username", "other"),
            ("type", "SOCKS5"),
        ):
            self.assertEqual(self.import_text(self.portable(a)).returncode, 0)
            changed = self.profile("a", username="u")
            changed["proxy"][key] = value
            self.assertEqual(self.import_text(self.portable(changed)).returncode, 0)
            self.assertNotIn(
                "password", json.loads(path.read_text())["profiles"][0]["proxy"]
            )

        self.env.pop("NO_PROXY", None)
        # Restore a usable selected HTTPS profile, without resetting root routing preferences.
        self.assertEqual(self.import_text(self.portable(b)).returncode, 0)
        self.assertEqual(self.probe("proxy487")["no_proxy"], "")

    def test_import_preserves_implicit_first_selection(self):
        self.assertEqual(
            self.import_text(self.portable(self.profile("a"))).returncode, 0
        )
        self.assertEqual(
            self.import_text(self.portable(self.profile("b"), active="b")).returncode, 0
        )
        config = json.loads((self.config / "config.json").read_text())
        self.assertEqual(config["activeProfileId"], "a")

    def test_invalid_import_preserves_config_and_hides_secrets(self):
        valid = self.portable(self.profile("a", username="u", password="secret"))
        self.assertEqual(self.import_text(valid).returncode, 0)
        path = self.config / "config.json"
        original = path.read_bytes()
        invalid = [
            '{"password":"secret",',
            "https://u:secret@host:bad",
            {"data": [{"type": "https", "hostname": "host", "port": 443}]},
            {"schemaVersion": 2, "+proxy": {"profileType": "FixedProfile"}},
            [self.profile("a")],
            {"profiles": [self.profile("a")]},
            "# superproxy:proxylist:v1\nhttps://u:secret@host:443",
            "https://u:secret@host?title=%XX",
            "secret" * (1024 * 1024 // 6 + 1),
            self.portable(self.profile("a"), self.profile("a")),
            self.portable(self.profile("a"), active="missing"),
            self.portable(self.profile("a", password="secret\n")),
            self.portable(
                {"id": "a", "proxy": {"type": "HTTPS", "host": "host", "port": True}}
            ),
            self.portable(
                {
                    "id": "a",
                    "proxy": {"type": "HTTPS_JUMP", "host": "host", "port": 443},
                }
            ),
            {"schema": "other", "version": 8, "profiles": [self.profile("a")]},
            {
                "schema": "dev.megaproxy.config",
                "version": 1,
                "profiles": [{"proxy": {"type": []}}],
            },
            self.portable(
                {"id": "a", "proxy": {"type": "MASQUE", "host": "host", "port": 443}}
            ),
        ]

        for data in invalid:
            with self.subTest(data=str(data)[:80]):
                result = self.import_text(data)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("secret", result.stdout + result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertEqual(path.read_bytes(), original)

        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_unsupported_profiles_and_platform_settings_warn(self):
        data = self.portable(
            self.profile("a"),
            {"id": "masque", "proxy": {"type": "MASQUE", "host": "host", "port": 443}},
            {
                "id": "insecure",
                "proxy": {
                    "type": "HTTPS",
                    "host": "host",
                    "port": 443,
                    "allowInvalidProxyCertificate": True,
                },
            },
        )
        data["tls"] = {"fingerprint": "CUSTOM", "customJa3": "example"}
        data["browser"] = {"theme": "dark"}
        data["profiles"][0]["dns"] = {"provider": "CLOUDFLARE"}
        result = self.import_text(data)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Skipped 2", result.stderr)
        self.assertIn("discarded", result.stderr)
        config = json.loads((self.config / "config.json").read_text())
        self.assertEqual(len(config["profiles"]), 1)
        self.assertNotIn("tls", config)
        self.assertNotIn("dns", config["profiles"][0])

    def test_file_import_and_ipv6_socks(self):
        file = self.home / "input.json"
        entry = self.profile(
            "ipv6",
            type="SOCKS5",
            host="2001:db8::1",
            port=1080,
            username="u:name",
            password="p+ss",
        )
        document = self.portable(entry)
        file.write_text(json.dumps(document))
        result = self.run_command("proxy487ctl", "import", str(file))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.run_command("proxy487ctl", "choose", "ipv6").returncode, 0
        )
        self.assertEqual(
            self.probe("proxy487")["https_proxy"],
            "socks5h://u%3Aname:p%2Bss@[2001:db8::1]:1080",
        )

        for version in range(1, 8):
            document["version"] = version
            self.assertNotEqual(self.import_text(document).returncode, 0)

    def test_pinned_schema_integrity_and_optional_fields(self):
        folder = BIN.parent / "lib/megaproxy-tools/config-schema"
        lock = json.loads((folder / "schema-lock.json").read_text())
        self.assertEqual(len(lock["commit"]), 40)

        for name, digest in lock["files"].items():
            self.assertEqual(
                hashlib.sha256((folder / name).read_bytes()).hexdigest(), digest
            )

        for field, value in (
            ("routing", {"bypassLocalNetworks": "false"}),
            ("tls", {"fingerprint": "invalid"}),
            ("subscription", {"url": "http://example.com"}),
            ("browser", {"theme": 42}),
        ):
            data = self.portable(self.profile("a"))
            data[field] = value
            result = self.import_text(data)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((self.config / "config.json").exists())

    def test_control_argparse_help_and_errors(self):
        for command in ("init", "list", "choose", "import", "diagnose"):
            result = self.run_command("proxy487ctl", command, "--help")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("usage:", result.stdout)

        for args in (
            (),
            ("import",),
            ("unknown",),
            ("list", "extra"),
            ("choose", "1", "extra"),
            ("--no-config", "list"),
            ("list", "--no-config-sync"),
        ):
            result = self.run_command("proxy487ctl", *args)
            self.assertEqual(result.returncode, 2)
            self.assertIn("usage:", result.stderr)

        self.assertFalse((self.config / "config.json").exists())

    def test_usage_missing_config_exit_and_arguments(self):
        for name in ("proxy487", "noproxy487", "proxy487ctl"):
            self.assertEqual(self.run_command(name).returncode, 2)

        for name in ("noproxy487", "proxy487ctl"):
            self.assertEqual(self.run_command(name, "--help").returncode, 0)

        for flag in ("--help", "--init", "--", "--no-config", "--unknown"):
            self.assertNotEqual(self.run_command("proxy487", flag).returncode, 0)
            self.assertFalse((self.config / "config.json").exists())

        self.assertNotEqual(self.run_command("proxy487", "true").returncode, 0)
        self.configure(self.profile("local", host="localhost", port=8080))
        result = self.run_command(
            "proxy487",
            sys.executable,
            "-c",
            'import sys; assert sys.argv[1] == "a b"; sys.exit(23)',
            "a b",
        )
        self.assertEqual(result.returncode, 23)
        self.assertNotEqual(
            self.run_command("proxy487", "/nonexistent/command").returncode, 0
        )


if __name__ == "__main__":
    unittest.main()
