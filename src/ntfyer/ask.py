"""`ask` mode: send a message, then wait for a reply on the same topic."""

import argparse
import json

from . import listen, ntfy_api, send
from .config import Profile


def run_ask(args: argparse.Namespace, profile: Profile, log) -> int:
    topic = args.topic or profile.topic
    if not topic:
        log.error("no topic specified (use --topic, or set topic= in the active profile)")
        return 2

    err = listen.check_receive_args(args)
    if err:
        log.error(err)
        return 2

    message = send.resolve_message(args)

    err = send.validate_send_args(args, message)
    if err:
        log.error(err)
        return 2

    try:
        actions = send.parse_actions(args)
    except (ValueError, json.JSONDecodeError) as e:
        log.error(f"invalid action definition: {e}")
        return 2

    kwargs = send.build_publish_kwargs(args, message, actions)

    log.verbose(f"asking on '{topic}' via {profile.url} (profile '{profile.name}')")
    log.debug(f"publish kwargs: {kwargs}")

    try:
        result = ntfy_api.publish(profile, topic, **kwargs)
    except ntfy_api.PublishError as e:
        log.error(f"publish failed: {e}")
        return 1

    log.info(f"sent to '{topic}'")
    log.verbose(f"message id: {result.get('id')}")

    log.verbose(
        f"waiting for a reply on '{topic}'" + (f", timeout {args.timeout}s" if args.timeout else "")
    )

    try:
        for msg in ntfy_api.stream_json(profile, topic, timeout=args.timeout):
            listen.handle_message(msg, args, profile, log, label="reply")
            return 0
    except KeyboardInterrupt:
        log.verbose("interrupted, stopping")
        return 0
    except ntfy_api.SubscribeError as e:
        log.error(f"listen for reply failed: {e}")
        return 1

    if args.timeout:
        log.error(f"timed out after {args.timeout}s waiting for a reply")
    else:
        log.error("stopped without receiving a reply")
    return 1
