"""ntfy publish/subscribe HTTP layer, shared by send/listen/ask."""

import json
import os
import time

import requests

from .config import Profile

PRIORITY_WORDS = {"min": 1, "low": 2, "default": 3, "high": 4, "urgent": 5}

DEFAULT_TIMEOUT = (10, 30)  # connect, read — seconds

# ntfy sends a keepalive line roughly every 30-45s on the JSON stream; this
# needs comfortable margin above that so a normal quiet period between
# messages never trips a spurious read timeout.
STREAM_CONNECT_TIMEOUT = 10
STREAM_READ_TIMEOUT = 90
RECONNECT_BACKOFF = 2


class PublishError(Exception):
    pass


class SubscribeError(Exception):
    pass


def _auth(profile: Profile) -> tuple[dict, tuple | None]:
    if profile.auth_type == "token":
        return {"Authorization": f"Bearer {profile.token}"}, None
    if profile.auth_type == "basic":
        return {}, (profile.username, profile.password)
    return {}, None


def _escape_action_field(value) -> str:
    s = str(value)
    return s.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;")


def action_to_header(action: dict) -> str:
    """Serialize one internal action dict into ntfy's X-Actions header grammar."""
    kind = action["action"]
    parts = [kind, action.get("label", "")]

    if kind in ("view", "http"):
        parts.append(action.get("url", ""))
    if kind == "http":
        if "method" in action:
            parts.append(f"method={action['method']}")
        for key, val in (action.get("headers") or {}).items():
            parts.append(f"headers.{key}={val}")
        if "body" in action:
            parts.append(f"body={action['body']}")
    if kind == "broadcast":
        if "intent" in action:
            parts.append(f"intent={action['intent']}")
        for key, val in (action.get("extras") or {}).items():
            parts.append(f"extras.{key}={val}")

    if action.get("clear"):
        parts.append("clear=true")

    return ", ".join(_escape_action_field(p) for p in parts)


def publish(
    profile: Profile,
    topic: str,
    *,
    message: str = "",
    title: str | None = None,
    priority: str | None = None,
    tags: list[str] | None = None,
    attach_path: str | None = None,
    attach_url: str | None = None,
    actions: list[dict] | None = None,
    email: str | None = None,
    call: str | None = None,
) -> dict:
    """
    Publish a message to profile.url/topic via ntfy's header-based publish API
    (https://docs.ntfy.sh/publish/). Raises PublishError on any failure —
    network, HTTP, or attachment read.
    """
    if not topic:
        raise PublishError("topic is required")

    url = f"{profile.url.rstrip('/')}/{topic}"
    auth_headers, basic_auth = _auth(profile)
    headers = dict(auth_headers)

    if title:
        headers["X-Title"] = title
    if priority:
        headers["X-Priority"] = str(priority)
    if tags:
        headers["X-Tags"] = ",".join(tags)
    if actions:
        headers["X-Actions"] = "; ".join(action_to_header(a) for a in actions)
    if email:
        headers["X-Email"] = email
    if call:
        headers["X-Call"] = call

    if attach_path:
        try:
            with open(attach_path, "rb") as f:
                body = f.read()
        except OSError as e:
            raise PublishError(f"could not read attachment {attach_path!r}: {e}") from e
        headers["X-Filename"] = os.path.basename(attach_path)
        if message:
            headers["X-Message"] = message
    else:
        if attach_url:
            headers["X-Attach"] = attach_url
        body = message.encode("utf-8")

    try:
        resp = requests.post(
            url, data=body, headers=headers, auth=basic_auth, timeout=DEFAULT_TIMEOUT,
        )
    except requests.RequestException as e:
        raise PublishError(f"request to {url} failed: {e}") from e

    if not resp.ok:
        detail = resp.text.strip()
        try:
            detail = resp.json().get("error", detail)
        except ValueError:
            pass
        raise PublishError(f"server returned {resp.status_code}: {detail}")

    try:
        return resp.json()
    except ValueError:
        return {"raw": resp.text}


def stream_json(profile: Profile, topic: str, *, timeout: float | None = None):
    """
    Yield decoded JSON dicts for each 'message' event on profile.url/topic/json.
    'open'/'keepalive' events are consumed silently. A dropped connection
    reconnects automatically; a hard failure on the *initial* connect (bad
    auth, unreachable host) raises SubscribeError immediately instead of
    retrying forever. If `timeout` is given, stops yielding (returns) once
    that many seconds have passed since the call started, whether or not
    anything arrived.
    """
    if not topic:
        raise SubscribeError("topic is required")

    url = f"{profile.url.rstrip('/')}/{topic}/json"
    auth_headers, basic_auth = _auth(profile)
    deadline = time.monotonic() + timeout if timeout else None

    while True:
        if deadline and time.monotonic() >= deadline:
            return

        if deadline:
            read_timeout = min(STREAM_READ_TIMEOUT, max(deadline - time.monotonic(), 1))
        else:
            read_timeout = STREAM_READ_TIMEOUT

        try:
            resp = requests.get(
                url, headers=auth_headers, auth=basic_auth, stream=True,
                timeout=(STREAM_CONNECT_TIMEOUT, read_timeout),
            )
            resp.raise_for_status()
        except requests.HTTPError as e:
            raise SubscribeError(f"server returned {e.response.status_code} for {url}") from e
        except requests.RequestException as e:
            raise SubscribeError(f"could not connect to {url}: {e}") from e

        try:
            for line in resp.iter_lines(decode_unicode=True):
                if deadline and time.monotonic() >= deadline:
                    return
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if data.get("event") == "message":
                    yield data
        except requests.RequestException:
            pass  # dropped mid-stream — fall through and reconnect
        finally:
            resp.close()

        if deadline and time.monotonic() >= deadline:
            return
        time.sleep(min(RECONNECT_BACKOFF, max(deadline - time.monotonic(), 0)) if deadline else RECONNECT_BACKOFF)
