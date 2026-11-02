"""Hourly HTTPS configuration snapshots; no background process or external packages."""

import base64
import contextlib
import fcntl
import hashlib
import http.client
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

from . import config as configuration


@contextlib.contextmanager
def config_lock(folder):
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)

    with os.fdopen(
        os.open(folder / "config.lock", os.O_RDWR | os.O_CREAT, 0o600), "r+"
    ) as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def state_path(folder):
    base = pathlib.Path(
        os.environ.get("XDG_STATE_HOME") or pathlib.Path.home() / ".local/state"
    )

    if not base.is_absolute():
        base = pathlib.Path.home() / ".local/state"

    key = hashlib.sha256(str(folder.resolve()).encode()).hexdigest()[:16]
    return base / "megaproxy-tools" / f"config-sync-{key}.json"


def load_state(folder, config):
    try:
        state = json.loads(configuration.read_text(state_path(folder)))
    except FileNotFoundError:
        return {
            "ownedIds": [p["id"] for p in config["profiles"]]
            if config.get("subscription")
            else []
        }

    if (
        not isinstance(state, dict)
        or not isinstance(state.get("ownedIds"), list)
        or any(not isinstance(i, str) for i in state["ownedIds"])
        or type(state.get("lastAttempt", 0)) not in (int, float)
        or not 0 <= state.get("lastAttempt", 0) < float("inf")
    ):
        raise ValueError("Invalid configuration sync state")

    return state


def commit(folder, previous, updated, state):
    path = folder / "config.json"
    existed = path.exists()
    configuration.atomic_write(path, updated)

    try:
        configuration.atomic_write(state_path(folder), state)
    except (OSError, ValueError):
        if existed:
            configuration.atomic_write(path, previous)
        else:
            path.unlink()

        raise


def save_import(folder, current, incoming, result):
    if "subscription" not in incoming:
        configuration.atomic_write(folder / "config.json", result)
        return

    state = load_state(folder, current)
    state["ownedIds"] = (
        [p["id"] for p in incoming["profiles"]] if incoming["subscription"] else []
    )
    commit(folder, current, result, state)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


def download(url, settings):
    headers = {
        "X-MegaProxy-Client": "megaproxy_tools",
        "X-MegaProxy-Version": "0+unreleased",
        "Accept": "application/json, text/plain",
        "Accept-Encoding": "identity",
    }

    if "username" in settings or "password" in settings:
        credentials = (
            f"{settings.get('username', '')}:{settings.get('password', '')}".encode(
                "utf-8"
            )
        )
        headers["Authorization"] = "Basic " + base64.b64encode(credentials).decode(
            "ascii"
        )
    # Use ordinary inherited network/proxy settings; never inject subscription auth into proxy auth.
    with urllib.request.build_opener(NoRedirect()).open(
        urllib.request.Request(url, headers=headers), timeout=10
    ) as response:
        if (
            response.status != 200
            or response.headers.get("Content-Encoding", "identity").lower()
            != "identity"
        ):
            raise ValueError("Unsupported subscription response")

        data = bytearray()
        deadline = time.monotonic() + 20

        while len(data) <= configuration.LIMIT:
            if time.monotonic() > deadline:
                raise ValueError("Subscription download timed out")

            chunk = response.read1(min(65536, configuration.LIMIT + 1 - len(data)))

            if not chunk:
                break

            data.extend(chunk)

    if len(data) > configuration.LIMIT:
        raise ValueError("Subscription exceeds 1 MiB")

    return data.decode("utf-8-sig")


def snapshot(current: dict, incoming: dict, owned: set[str]) -> tuple[dict, list[str]]:
    incoming = {**incoming, "profiles": [{**p} for p in incoming["profiles"]]}
    previous = {p["id"]: p for p in current["profiles"]}
    ids = {p["id"] for p in incoming["profiles"]}

    if any(i in previous and i not in owned for i in ids):
        raise ValueError("Subscription profile ID conflicts with a local profile")

    selected = configuration.active_profile(current)["id"]
    retained = {
        **current,
        "profiles": [
            p for p in current["profiles"] if p["id"] not in owned or p["id"] in ids
        ],
    }

    if selected not in {p["id"] for p in retained["profiles"]}:
        retained["activeProfileId"] = None
    # Downloaded definitions replace sources only; local auth, pause and interval stay local.
    sources = incoming.get("subscription")
    settings = current["subscription"]
    incoming["subscription"] = {**settings}

    if sources is not None:
        incoming["subscription"]["url"] = sources["url"]
        incoming["subscription"]["fallbackUrls"] = sources.get("fallbackUrls", [])

    result = configuration.merge(retained, incoming)
    present = {p["id"] for p in result["profiles"]}
    result["activeProfileId"] = (
        selected
        if selected in present
        else incoming.get("activeProfileId") or incoming["profiles"][0]["id"]
    )
    configuration.validate(result)
    configuration.profile_url(configuration.active_profile(result))
    return result, [p["id"] for p in incoming["profiles"]]


def sync_config(folder: pathlib.Path, config: dict) -> dict:
    settings = config.get("subscription")

    if not settings or not settings.get("enabled", True):
        return config

    try:
        state = load_state(folder, config)
        now = time.time()
        # Failed attempts count too; a clock moving backwards must not trigger repeated downloads.
        if "lastAttempt" in state and now - state["lastAttempt"] < max(
            3600, settings.get("intervalMinutes", 60) * 60
        ):
            return config

        state["lastAttempt"] = now
        configuration.atomic_write(state_path(folder), state)
    except (OSError, ValueError, RecursionError):
        configuration.warn(
            "Configuration sync state unavailable; keeping local configuration"
        )
        return config

    for index, url in enumerate(
        [settings["url"], *settings.get("fallbackUrls", [])], 1
    ):
        try:
            text = download(url, settings)
            incoming = configuration.parse_import(text)
            updated, owned = snapshot(config, incoming, set(state["ownedIds"]))
            completed = {
                **state,
                "ownedIds": owned,
                "lastSuccess": time.time(),
                "successfulSource": index,
                "lastError": None,
            }
            commit(folder, config, updated, completed)
        except (
            OSError,
            ValueError,
            urllib.error.URLError,
            http.client.HTTPException,
            RecursionError,
        ):
            configuration.warn(
                f"Configuration source {index} failed; keeping local configuration and trying next source if available"
            )
            continue

        previous = {p["id"]: p for p in config["profiles"]}
        following = {p["id"]: p for p in updated["profiles"]}
        added = len(following.keys() - previous.keys())
        removed = len(previous.keys() - following.keys())
        changed = sum(
            previous[i] != following[i] for i in previous.keys() & following.keys()
        )
        print(
            f"Config sync: source {index}; added {added}, changed {changed}, removed {removed}",
            file=sys.stderr,
        )

        if (
            configuration.active_profile(updated)["id"]
            != configuration.active_profile(config)["id"]
        ):
            print("Config sync: selected profile replaced", file=sys.stderr)

        if config.get("routing") != updated.get("routing"):
            print("Config sync: local-network bypass updated", file=sys.stderr)

        if config.get("subscription") != updated.get("subscription"):
            print("Config sync: subscription sources updated", file=sys.stderr)

        return updated

    configuration.warn("Configuration sync failed; using saved configuration")
    state["lastError"] = "All configuration sources failed"

    try:
        configuration.atomic_write(state_path(folder), state)
    except (OSError, ValueError):
        pass

    return config
