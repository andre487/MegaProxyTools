import base64
import concurrent.futures
import contextlib
import io
import json
import os
import pathlib
import runpy
import subprocess
import sys
import tempfile
import unittest
import unittest.mock as mock

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parents[1] / "lib/megaproxy-tools")
)

import megaproxy_tools as megaproxy
import megaproxy_tools.sync as sync

ROOT = pathlib.Path(__file__).resolve().parents[1]


def profile(identifier, host=None, **fields):
    return {
        "id": identifier,
        "name": identifier,
        "proxy": {
            "type": "HTTPS",
            "host": host or identifier + ".example",
            "port": 443,
            **fields,
        },
    }


def portable(*profiles, active=None, subscription=None):
    return {
        "schema": "net.megaproxy487.config",
        "version": 8,
        "profiles": list(profiles),
        "activeProfileId": active,
        **({"subscription": subscription} if subscription is not None else {}),
    }


class ConfigSync(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = pathlib.Path(self.temp.name) / "config"
        self.folder.mkdir()
        self.environment = mock.patch.dict(
            os.environ,
            {
                "HOME": self.temp.name,
                "XDG_STATE_HOME": str(pathlib.Path(self.temp.name) / "state"),
                "XDG_CONFIG_HOME": self.temp.name,
            },
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.settings = {
            "url": "https://config.example/feed",
            "username": "reader",
            "password": "feed-secret",
        }
        self.config = portable(
            profile("a", password="proxy-secret"),
            profile("b"),
            active="a",
            subscription=self.settings,
        )
        megaproxy.config.atomic_write(self.folder / "config.json", self.config)
        self.logs = io.StringIO()
        self.capture = contextlib.redirect_stderr(self.logs)
        self.capture.__enter__()
        self.addCleanup(self.capture.__exit__, None, None, None)

    def refresh(self, text, now=10000):
        body = text if isinstance(text, str) else json.dumps(text)

        with (
            mock.patch.object(sync, "download", return_value=body) as request,
            mock.patch.object(sync.time, "time", return_value=now),
        ):
            with sync.config_lock(self.folder):
                result = sync.sync_config(
                    self.folder, megaproxy.config.load_config(self.folder)
                )

        return result, request

    def test_hourly_success_failure_and_clock_rollback(self):
        body = portable(profile("a"), profile("b"))
        result, request = self.refresh(body)
        request.assert_called_once()
        self.assertEqual(result["profiles"][0]["proxy"]["password"], "proxy-secret")

        for now in (10001, 13599, 9000):
            _, request = self.refresh(body, now)
            request.assert_not_called()

        _, request = self.refresh("invalid HTML feed-secret", 13600)
        request.assert_called_once()
        _, request = self.refresh(body, 13601)
        request.assert_not_called()
        state = json.loads(sync.state_path(self.folder).read_text())
        self.assertEqual(state["lastSuccess"], 10000)
        self.assertIsNotNone(state["lastError"])
        self.assertEqual(megaproxy.config.load_config(self.folder), result)
        self.assertNotIn("feed-secret", self.logs.getvalue())
        self.assertNotIn("proxy-secret", self.logs.getvalue())
        if os.name != "nt":
            self.assertEqual(sync.state_path(self.folder).stat().st_mode & 0o777, 0o600)

    def test_concurrent_launches_share_throttle(self):
        def launch():
            with sync.config_lock(self.folder):
                return sync.sync_config(
                    self.folder, megaproxy.config.load_config(self.folder)
                )

        with mock.patch.object(
            sync,
            "download",
            return_value=json.dumps(portable(profile("a"), profile("b"))),
        ) as request:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: launch(), range(2)))

        request.assert_called_once()
        self.assertEqual(results[0], results[1])

    def test_snapshot_ownership_selection_and_source_replacement(self):
        current = megaproxy.config.merge(self.config, portable(profile("local")))
        state = {"ownedIds": ["a", "b"]}
        megaproxy.config.atomic_write(sync.state_path(self.folder), state)
        megaproxy.config.atomic_write(self.folder / "config.json", current)
        sources = {
            "url": "https://new.example/feed",
            "fallbackUrls": ["https://backup.example/feed"],
            "username": "untrusted",
            "password": "replace-secret",
            "enabled": False,
            "intervalMinutes": 1,
        }
        incoming = portable(
            profile("b"), profile("c"), active="c", subscription=sources
        )
        result, _ = self.refresh(incoming)
        self.assertEqual({p["id"] for p in result["profiles"]}, {"b", "c", "local"})
        self.assertEqual(result["activeProfileId"], "c")
        self.assertEqual(result["subscription"]["url"], sources["url"])
        self.assertEqual(result["subscription"]["password"], "feed-secret")
        self.assertNotIn("enabled", result["subscription"])
        self.assertNotIn("intervalMinutes", result["subscription"])
        self.assertIn("removed 1", self.logs.getvalue())
        self.assertIn("selected profile replaced", self.logs.getvalue())
        result, _ = self.refresh(
            portable(profile("b"), profile("c"), active="b"), 13600
        )
        self.assertEqual(result["activeProfileId"], "c")
        self.assertEqual(result["subscription"]["url"], sources["url"])

    def test_fallback_invalid_body_and_local_collision(self):
        self.config["subscription"]["fallbackUrls"] = ["https://backup.example/feed"]
        self.config = megaproxy.config.merge(self.config, portable(profile("local")))
        megaproxy.config.atomic_write(self.folder / "config.json", self.config)
        megaproxy.config.atomic_write(
            sync.state_path(self.folder), {"ownedIds": ["a", "b"]}
        )
        bodies = [
            json.dumps(portable(profile("local"))),
            json.dumps(portable(profile("a"), profile("b"))),
        ]

        with mock.patch.object(sync, "download", side_effect=bodies) as request:
            result = sync.sync_config(self.folder, self.config)

        self.assertEqual(request.call_count, 2)
        self.assertEqual({p["id"] for p in result["profiles"]}, {"a", "b", "local"})
        state = json.loads(sync.state_path(self.folder).read_text())
        self.assertEqual(state["successfulSource"], 2)
        self.assertIn("source 1 failed", self.logs.getvalue())

    def test_non_megaproxy_snapshot_keeps_working_config(self):
        before = (self.folder / "config.json").read_bytes()
        result, request = self.refresh("https://proxy.example:443")
        request.assert_called_once()
        self.assertEqual(result, self.config)
        self.assertEqual((self.folder / "config.json").read_bytes(), before)

    def test_subscription_manual_merge_validation_pause_and_interval(self):
        incoming = portable(
            profile("a"),
            subscription={"url": self.settings["url"], "username": "reader"},
        )
        result = megaproxy.config.merge(
            self.config, megaproxy.config.parse_import(json.dumps(incoming))
        )
        self.assertEqual(result["subscription"]["password"], "feed-secret")
        self.assertEqual(
            megaproxy.config.merge(result, portable(profile("c")))["subscription"],
            result["subscription"],
        )

        for changes in (
            {"url": "https://different.example/feed"},
            {"username": "other"},
        ):
            changed = {
                **incoming,
                "subscription": {**incoming["subscription"], **changes},
            }
            self.assertNotIn(
                "password",
                megaproxy.config.merge(
                    result, megaproxy.config.parse_import(json.dumps(changed))
                )["subscription"],
            )

        cleared = {
            **incoming,
            "subscription": {**incoming["subscription"], "password": ""},
        }
        self.assertEqual(
            megaproxy.config.merge(
                result, megaproxy.config.parse_import(json.dumps(cleared))
            )["subscription"]["password"],
            "",
        )
        self.assertIsNone(
            megaproxy.config.merge(result, {**incoming, "subscription": None})[
                "subscription"
            ]
        )
        invalid = [
            {"url": "http://config.example"},
            {"url": "https://user:secret@config.example"},
            {"url": "https://config.example/#fragment"},
            {"url": "https://config.example:0/"},
            {
                "url": "https://config.example/",
                "fallbackUrls": ["https://CONFIG.example:443/"],
            },
            {**self.settings, "username": "reader:bad"},
            {**self.settings, "password": "bad\n"},
        ]

        for settings in invalid:
            with self.assertRaises(ValueError):
                megaproxy.config.parse_import(
                    json.dumps(portable(profile("a"), subscription=settings))
                )

        self.config["subscription"]["enabled"] = False

        with mock.patch.object(sync, "download") as request:
            self.assertEqual(sync.sync_config(self.folder, self.config), self.config)
            request.assert_not_called()

        self.config["subscription"]["enabled"] = True
        self.config["subscription"]["intervalMinutes"] = 120
        megaproxy.config.atomic_write(self.folder / "config.json", self.config)
        self.refresh(portable(profile("a")))
        _, request = self.refresh(portable(profile("a")), 13600)
        request.assert_not_called()

    def test_bootstrap_import_subscription_and_unsubscribe(self):
        incoming = megaproxy.config.parse_import(
            json.dumps(portable(profile("feed"), subscription=self.settings))
        )
        current = portable(profile("local"))
        result = megaproxy.config.merge(current, incoming)
        sync.save_import(self.folder, current, incoming, result)
        state = json.loads(sync.state_path(self.folder).read_text())
        self.assertEqual(state["ownedIds"], ["feed"])
        updated, _ = self.refresh(portable(profile("next")))
        self.assertEqual({p["id"] for p in updated["profiles"]}, {"local", "next"})
        incoming = {"profiles": [profile("next")], "subscription": None}
        result = megaproxy.config.merge(updated, incoming)
        sync.save_import(self.folder, updated, incoming, result)
        self.assertEqual(
            json.loads(sync.state_path(self.folder).read_text())["ownedIds"], []
        )
        self.assertIsNone(megaproxy.config.load_config(self.folder)["subscription"])

    def test_download_auth_headers_limits_and_redirect_rejection(self):
        response = io.BytesIO(b'{"profiles":[]}')
        response.status = 200
        response.headers = {}
        opener = mock.Mock()
        opener.open.return_value = response

        with mock.patch.object(
            sync.urllib.request, "build_opener", return_value=opener
        ) as build:
            self.assertEqual(
                sync.download(self.settings["url"], self.settings), '{"profiles":[]}'
            )

        request = opener.open.call_args.args[0]
        self.assertEqual(
            request.get_header("Authorization"),
            "Basic " + base64.b64encode(b"reader:feed-secret").decode(),
        )
        self.assertEqual(request.get_header("X-megaproxy-client"), "megaproxy_tools")
        self.assertEqual(request.get_header("X-megaproxy-version"), "0+unreleased")
        self.assertIsInstance(build.call_args.args[0], sync.NoRedirect)
        self.assertIsNone(
            build.call_args.args[0].redirect_request(
                None, None, 302, "", {}, "https://evil.example"
            )
        )

        for body, status in (
            (b"x" * (megaproxy.config.LIMIT + 1), 200),
            (b"bad", 304),
            (b"\xff", 200),
        ):
            response = io.BytesIO(body)
            response.status, response.headers = status, {}
            opener.open.return_value = response

            with (
                mock.patch.object(
                    sync.urllib.request, "build_opener", return_value=opener
                ),
                self.assertRaises(ValueError),
            ):
                sync.download(self.settings["url"], self.settings)

    def test_failed_state_commit_rolls_back_profiles(self):
        original = (self.folder / "config.json").read_bytes()
        real_write = megaproxy.config.atomic_write

        def fail_status(path, document):
            if path == sync.state_path(self.folder) and "lastSuccess" in document:
                raise OSError("simulated persistence failure")

            return real_write(path, document)

        with (
            mock.patch.object(
                sync, "download", return_value=json.dumps(portable(profile("new")))
            ),
            mock.patch.object(
                megaproxy.config, "atomic_write", side_effect=fail_status
            ),
        ):
            result = sync.sync_config(self.folder, self.config)

        self.assertEqual(result, self.config)
        self.assertEqual((self.folder / "config.json").read_bytes(), original)

    def test_cli_sync_logs_before_command_and_opt_out(self):
        folder = pathlib.Path(self.temp.name) / "megaproxy-tools"
        folder.mkdir()
        megaproxy.config.atomic_write(folder / "config.json", self.config)
        marker = []

        def child(command, args, environment):
            marker.append(environment["https_proxy"])
            self.assertIn("Config sync:", self.logs.getvalue())
            self.assertNotIn("--no-config-sync", args)

        with mock.patch.object(
            sync, "download", return_value=json.dumps(portable(profile("new")))
        ) as request:
            with (
                mock.patch.object(sys, "argv", ["proxy487", "child", "argument"]),
                mock.patch("os.execvpe", side_effect=child),
                mock.patch(
                    "subprocess.call",
                    side_effect=lambda args, env: child(args[0], args, env),
                ),
            ):
                with self.assertRaises(SystemExit) as exit_status:
                    runpy.run_path(str(ROOT / "bin/proxy487"), run_name="__main__")

            self.assertIn(exit_status.exception.code, (None, 0))
            request.assert_called_once()

        self.assertEqual(marker, ["https://new.example:443"])

        for command in ("proxy487", "proxy487ctl"):
            args = (
                ["--no-config-sync", "list"]
                if command.endswith("ctl")
                else [
                    "--no-config-sync",
                    sys.executable,
                    "-c",
                    'import sys; assert sys.argv[1:] == ["--no-config-sync"]',
                    "--no-config-sync",
                ]
            )
            result = subprocess.run(
                [sys.executable, str(ROOT / "bin" / command), *args],
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("Config sync", result.stderr)
        # A due ctl launch performs the same check and preserves a surviving selection.
        state = json.loads(sync.state_path(folder).read_text())
        state["lastAttempt"] = 0
        megaproxy.config.atomic_write(sync.state_path(folder), state)

        with (
            mock.patch.object(
                sync, "download", return_value=json.dumps(portable(profile("new")))
            ) as request,
            mock.patch.object(sys, "argv", ["proxy487ctl", "list"]),
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ):
            with self.assertRaises(SystemExit):
                runpy.run_path(str(ROOT / "bin/proxy487ctl"), run_name="__main__")

            request.assert_called_once()
        # The subsequent ctl launch shares the timestamp and does not fetch again.
        with (
            mock.patch.object(sync, "download") as request,
            mock.patch.object(sys, "argv", ["proxy487ctl", "list"]),
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ):
            with self.assertRaises(SystemExit):
                runpy.run_path(str(ROOT / "bin/proxy487ctl"), run_name="__main__")

            request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
