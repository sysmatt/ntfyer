"""`listen` mode: wait for messages on a topic and run a handler."""

import argparse
import os

from . import attachments, handlers, ntfy_api
from .config import Profile


def check_receive_args(args: argparse.Namespace) -> str | None:
    """Return an error message if --handler/--handler-input/--save-attachment/etc. are inconsistent, else None."""
    if args.handler and args.handler_input == "arg" and "%MESSAGE%" not in args.handler:
        return "--handler-input arg requires %MESSAGE% in --handler"
    if args.handler and "%ATTACHMENT%" in args.handler and not args.save_attachment:
        return "--handler references %ATTACHMENT% but --save-attachment wasn't given"
    if args.save_attachment and not os.path.isdir(args.save_attachment):
        return f"--save-attachment directory does not exist: {args.save_attachment}"
    if args.purge_attachment and not args.save_attachment:
        return "--purge-attachment requires --save-attachment"
    if args.purge_attachment and not args.handler:
        return "--purge-attachment requires --handler (downloading just to immediately delete it is a no-op)"
    if args.handler_attachment_arg and not args.save_attachment:
        return "--handler-attachment-arg requires --save-attachment"
    if args.handler_attachment_arg and not args.handler:
        return "--handler-attachment-arg requires --handler"
    if args.handler_attachment_arg and args.handler and "%ATTACHMENT%" not in args.handler:
        return "--handler-attachment-arg requires %ATTACHMENT% in --handler"
    return None


def handle_message(
    msg: dict, args: argparse.Namespace, profile: Profile, log, *, label: str = "received",
) -> int:
    """Log a received message, save its attachment if configured, and run the handler, if any. Returns the handler's exit code (0 if none)."""
    text = msg.get("message", "")
    title = msg.get("title")
    log.info(f"{label}: {title}: {text}" if title else f"{label}: {text}")
    log.verbose(f"id={msg.get('id')} time={msg.get('time')} tags={msg.get('tags')}")
    log.trace(f"full message: {msg}")

    attachment_path = None
    if args.save_attachment:
        try:
            attachment_path = attachments.save_attachment(profile, msg, args.save_attachment)
            if attachment_path:
                log.verbose(f"saved attachment to {attachment_path}")
        except attachments.AttachmentError as e:
            log.error(f"attachment download failed: {e}")

    if not args.handler:
        return 0

    try:
        rc = handlers.run_handler(
            args.handler, msg, args.handler_input, log,
            attachment_path=attachment_path, attachment_arg=args.handler_attachment_arg,
        )
        log.verbose(f"handler exited {rc}")
        if rc != 0:
            log.warning(f"handler exited non-zero: {rc}")
        return rc
    except handlers.HandlerError as e:
        log.error(f"handler failed: {e}")
        return 1
    finally:
        if args.purge_attachment and attachment_path:
            try:
                os.remove(attachment_path)
                log.verbose(f"purged attachment {attachment_path}")
            except OSError as e:
                log.warning(f"could not purge attachment {attachment_path!r}: {e}")


def run_listen(args: argparse.Namespace, profile: Profile, log) -> int:
    topic = args.topic or profile.topic
    if not topic:
        log.error("no topic specified (use --topic, or set topic= in the active profile)")
        return 2

    err = check_receive_args(args)
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
            handle_message(msg, args, profile, log)
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
