"""`listen` mode: wait for messages on a topic and run a handler."""

import argparse

from . import handlers, ntfy_api
from .config import Profile


def check_handler_args(args: argparse.Namespace) -> str | None:
    """Return an error message if --handler/--handler-input are inconsistent, else None."""
    if args.handler and args.handler_input == "arg" and "%MESSAGE%" not in args.handler:
        return "--handler-input arg requires %MESSAGE% in --handler"
    return None


def handle_message(msg: dict, args: argparse.Namespace, log, *, label: str = "received") -> int:
    """Log a received message and run the configured handler, if any. Returns the handler's exit code (0 if none)."""
    text = msg.get("message", "")
    title = msg.get("title")
    log.info(f"{label}: {title}: {text}" if title else f"{label}: {text}")
    log.verbose(f"id={msg.get('id')} time={msg.get('time')} tags={msg.get('tags')}")
    log.trace(f"full message: {msg}")

    if not args.handler:
        return 0

    try:
        rc = handlers.run_handler(args.handler, msg, args.handler_input)
        log.verbose(f"handler exited {rc}")
        if rc != 0:
            log.warning(f"handler exited non-zero: {rc}")
        return rc
    except handlers.HandlerError as e:
        log.error(f"handler failed: {e}")
        return 1


def run_listen(args: argparse.Namespace, profile: Profile, log) -> int:
    topic = args.topic or profile.topic
    if not topic:
        log.error("no topic specified (use --topic, or set topic= in the active profile)")
        return 2

    err = check_handler_args(args)
    if err:
        log.error(err)
        return 2

    log.verbose(
        f"listening on '{topic}' via {profile.url} (profile '{profile.name}')"
        + (f", timeout {args.timeout}s" if args.timeout else "")
        + (", once" if args.once else "")
    )

    received_any = False
    try:
        for msg in ntfy_api.stream_json(profile, topic, timeout=args.timeout):
            received_any = True
            handle_message(msg, args, log)
            if args.once:
                break
    except KeyboardInterrupt:
        log.verbose("interrupted, stopping")
        return 0
    except ntfy_api.SubscribeError as e:
        log.error(f"listen failed: {e}")
        return 1

    if not received_any:
        if args.timeout:
            log.error(f"timed out after {args.timeout}s waiting for a message")
        else:
            log.error("stopped without receiving a message")
        return 1

    return 0
