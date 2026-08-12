"""`send` mode: publish a single notification."""

import argparse
import json
import os
import sys

from . import ntfy_api
from .config import Profile

ACTION_TYPES = ("view", "http", "broadcast")


def resolve_message(args: argparse.Namespace) -> str:
    if args.stdin or args.message == ["-"]:
        text = sys.stdin.read()
        return text[:-1] if text.endswith("\n") else text
    return " ".join(args.message)


def _split_action_fields(raw: str) -> list[str]:
    """Split on unescaped commas; \\, and \\\\ are unescaped in each resulting field."""
    fields = []
    current = []
    escape = False
    for ch in raw:
        if escape:
            current.append(ch)
            escape = False
        elif ch == "\\":
            escape = True
        elif ch == ",":
            fields.append("".join(current))
            current = []
        else:
            current.append(ch)
    fields.append("".join(current))
    return [f.strip() for f in fields]


def parse_action(raw: str) -> dict:
    """Parse one --action 'type,label,url[,key=value...]' string into ntfy's action dict shape."""
    parts = _split_action_fields(raw)
    if len(parts) < 2:
        raise ValueError(f"--action needs at least type,label: {raw!r}")

    kind, label, *rest = parts
    kind = kind.lower()
    if kind not in ACTION_TYPES:
        raise ValueError(
            f"--action type must be one of {', '.join(ACTION_TYPES)}, got {kind!r} in {raw!r}"
        )

    action = {"action": kind, "label": label}

    if kind in ("view", "http"):
        if not rest:
            raise ValueError(f"--action {kind} requires a url as the third field: {raw!r}")
        action["url"] = rest.pop(0)

    for extra in rest:
        if "=" not in extra:
            raise ValueError(f"--action extra field must be key=value, got {extra!r} in {raw!r}")
        key, val = (x.strip() for x in extra.split("=", 1))
        if key == "method":
            action["method"] = val
        elif key.startswith("headers."):
            action.setdefault("headers", {})[key[len("headers."):]] = val
        elif key == "body":
            action["body"] = val
        elif key.startswith("extras."):
            action.setdefault("extras", {})[key[len("extras."):]] = val
        elif key == "intent":
            action["intent"] = val
        elif key == "clear":
            action["clear"] = val.lower() in ("1", "true", "yes")
        else:
            raise ValueError(f"--action unknown field {key!r} in {raw!r}")

    return action


def parse_actions(args: argparse.Namespace) -> list[dict]:
    actions = [parse_action(raw) for raw in (args.action or [])]

    if args.actions_json:
        extra = json.loads(args.actions_json)
        if not isinstance(extra, list):
            raise ValueError("--actions-json must be a JSON array of action objects")
        actions.extend(extra)

    return actions


def validate_send_args(args: argparse.Namespace, message: str) -> str | None:
    """Return an error message if args/message can't be sent, else None."""
    if not message and not args.attach and not args.attach_url and not args.title:
        return (
            "refusing to send an empty notification "
            "(provide a message, --title, --attach, or --attach-url)"
        )
    if args.attach and not os.path.isfile(args.attach):
        return f"--attach file not found: {args.attach}"
    return None


def build_publish_kwargs(args: argparse.Namespace, message: str, actions: list[dict]) -> dict:
    tags = [t.strip() for t in args.tags.split(",")] if args.tags else None
    return dict(
        message=message,
        title=args.title,
        priority=args.priority,
        tags=tags,
        attach_path=args.attach,
        attach_url=args.attach_url,
        actions=actions or None,
        email=args.email,
        call=args.call,
    )


def run_send(args: argparse.Namespace, profile: Profile, log) -> int:
    topic = args.topic or profile.topic
    if not topic:
        log.error("no topic specified (use --topic, or set topic= in the active profile)")
        return 2

    message = resolve_message(args)

    err = validate_send_args(args, message)
    if err:
        log.error(err)
        return 2

    try:
        actions = parse_actions(args)
    except (ValueError, json.JSONDecodeError) as e:
        log.error(f"invalid action definition: {e}")
        return 2

    kwargs = build_publish_kwargs(args, message, actions)

    log.verbose(f"sending to '{topic}' via {profile.url} (profile '{profile.name}')")
    log.debug(f"publish kwargs: {kwargs}")

    try:
        result = ntfy_api.publish(profile, topic, **kwargs)
    except ntfy_api.PublishError as e:
        log.error(f"publish failed: {e}")
        return 1

    log.info(f"sent to '{topic}'")
    log.verbose(f"message id: {result.get('id')}")
    log.trace(f"full response: {result}")
    return 0
