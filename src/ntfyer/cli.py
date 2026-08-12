import argparse
import sys

from . import ask, config, listen, meta, send, tags
from ._vendor.applogger import AppLogger
from .ntfy_api import PRIORITY_WORDS


def parse_priority(value: str) -> str:
    if value.lower() in PRIORITY_WORDS:
        return value.lower()
    if value in {"1", "2", "3", "4", "5"}:
        return value
    raise argparse.ArgumentTypeError(
        f"invalid priority {value!r}: expected one of "
        f"{', '.join(PRIORITY_WORDS)} or 1-5"
    )


class _PrintTagsAction(argparse.Action):
    """Print the ntfy tag/emoji shortcode table and exit, like --version does."""

    def __init__(self, option_strings, dest, full=False, nargs=0, **kwargs):
        self._full = full
        super().__init__(option_strings, dest, nargs=nargs, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        tags.print_tags(full=self._full)
        parser.exit()


def build_common_parent() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument(
        "--ini", metavar="PATH",
        help=f"Use PATH instead of the default config file ({meta.DEFAULT_CONFIG_PATH})",
    )
    p.add_argument(
        "--profile", metavar="NAME",
        help="Config profile to use (overrides [default] profile= in the INI file, "
             f"and ${meta.env_var('PROFILE')})",
    )
    p.add_argument(
        "--log-file", dest="logfile", metavar="PATH",
        help="Also write log output to PATH",
    )
    p.add_argument(
        "--syslog", dest="syslog", default=True, action=argparse.BooleanOptionalAction,
        help="Log to syslog (default: on; use --no-syslog to disable)",
    )
    p.add_argument(
        "--verbose", "-v", action="store_true",
        help="Print high-level steps and actions taken",
    )
    p.add_argument(
        "--debug", "-d", action="store_true",
        help="Print verbose progress, full parsed arguments, and data structure dumps",
    )
    p.add_argument(
        "--trace", action="store_true",
        help="Print everything --debug does plus raw request/response dumps",
    )
    return p


def build_topic_parent() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument(
        "--topic", metavar="TOPIC",
        help="ntfy topic (default: the active profile's topic=)",
    )
    return p


def build_sending_parent() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--title", metavar="TEXT", help="Notification title")
    p.add_argument(
        "--priority", "-p", type=parse_priority, metavar="PRIORITY",
        help=f"One of {', '.join(PRIORITY_WORDS)}, or 1-5",
    )
    p.add_argument(
        "--tags", metavar="TAG,TAG,...",
        help="Comma-separated tags/emoji shortcodes",
    )

    attach_group = p.add_mutually_exclusive_group()
    attach_group.add_argument(
        "--attach", metavar="PATH",
        help="Upload PATH as the notification's attachment",
    )
    attach_group.add_argument(
        "--attach-url", metavar="URL",
        help="Attach an externally-hosted file by URL instead of uploading",
    )

    p.add_argument(
        "--action", action="append", metavar="TYPE,LABEL,URL[,...]",
        help="Add an action button, e.g. 'view,Open Site,https://example.com'. "
             "Repeatable.",
    )
    p.add_argument(
        "--actions-json", metavar="JSON",
        help="Raw ntfy actions JSON array, for anything --action can't express. "
             "Combines with --action if both given.",
    )
    p.add_argument("--email", metavar="ADDRESS", help="Also deliver via email")
    p.add_argument(
        "--call", metavar="PHONE",
        help="Also deliver via phone call to PHONE (requires ntfy server/plan support)",
    )
    return p


def build_waiting_parent() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument(
        "--timeout", type=float, metavar="SECONDS",
        help="Give up waiting for a message after SECONDS (default: wait forever)",
    )
    p.add_argument(
        "--handler", metavar="CMD",
        help="Command to run when a message arrives. %%TITLE%%, %%TOPIC%%, %%ID%%, "
             "%%PRIORITY%%, %%TAGS%%, and %%TIME%% are always substituted into CMD's "
             "arguments if present (empty string if the message lacks that "
             "field). %%MESSAGE%% is special: if CMD contains it, the message "
             "is substituted there too; otherwise the message is delivered "
             "per --handler-input, independent of the other placeholders — "
             "e.g. the message can arrive on stdin while %%TITLE%% is still "
             "substituted into an argument. CMD is parsed with shell-style "
             "quoting but never executed through a shell, so field content "
             "can't inject additional commands.",
    )
    p.add_argument(
        "--handler-input", choices=["stdin", "arg", "env"], default="stdin",
        help="How the message reaches the handler when %%MESSAGE%% isn't used "
             "in --handler (default: stdin). env exposes it as $MESSAGE.",
    )
    return p


def build_parser() -> argparse.ArgumentParser:
    common = build_common_parent()
    topic = build_topic_parent()
    sending = build_sending_parent()
    waiting = build_waiting_parent()

    p = argparse.ArgumentParser(
        prog=meta.PROG,
        description="Send, listen for, and request replies to ntfy notifications.",
    )
    # Shared flags (--ini, --debug, etc.) live only on the subparsers, not here —
    # argparse's subparsers action parses into a fresh namespace and then copies
    # it over the parent's, so a flag defined on both would have its value from
    # before the mode word silently clobbered by the subparser's default. This
    # means global flags go after the mode: `ntfyer send --debug`, not
    # `ntfyer --debug send`.
    p.add_argument(
        "--version", action="version", version=f"{meta.PROG} {meta.VERSION}",
    )
    p.add_argument(
        "--help-tags", action=_PrintTagsAction, full=False,
        help="Print a table of common ntfy tag/emoji shortcodes (for --tags) and exit",
    )
    p.add_argument(
        "--help-tags-full", action=_PrintTagsAction, full=True,
        help="Print the full ntfy tag/emoji shortcode table (~1800 entries) and exit",
    )
    sub = p.add_subparsers(dest="mode", required=True)

    send_p = sub.add_parser(
        "send", parents=[common, sending, topic],
        help="Publish a notification",
    )
    send_p.add_argument(
        "--stdin", action="store_true",
        help="Read the message body from stdin (also triggered by a lone '-' message)",
    )
    send_p.add_argument(
        "message", nargs=argparse.REMAINDER,
        help="Message text (remaining words are joined with spaces). "
             "Use '-' or --stdin to read the body from stdin instead.",
    )

    listen_p = sub.add_parser(
        "listen", parents=[common, topic, waiting],
        help="Wait for messages on a topic and run a handler",
    )
    listen_p.add_argument(
        "--once", action="store_true",
        help="Exit after the first message (default: run until Ctrl-C)",
    )

    ask_p = sub.add_parser(
        "ask", parents=[common, sending, topic, waiting],
        help="Send a message, then wait for a reply on the same topic",
    )
    ask_p.add_argument(
        "--stdin", action="store_true",
        help="Read the message body from stdin (also triggered by a lone '-' message)",
    )
    ask_p.add_argument(
        "message", nargs=argparse.REMAINDER,
        help="Message text (remaining words are joined with spaces). "
             "Use '-' or --stdin to read the body from stdin instead.",
    )

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        cfg = config.load_ini(args.ini)
    except config.ConfigError as e:
        print(f"{meta.PROG}: {e}", file=sys.stderr)
        return 2

    log = AppLogger.from_args(args, meta.PROG, cfg=cfg)
    log.debug(f"parsed args: {vars(args)}")

    try:
        profile = config.resolve_profile(
            cfg,
            profile_name=args.profile,
            overrides={"topic": getattr(args, "topic", None)},
        )
    except config.ConfigError as e:
        log.error(str(e))
        return 2

    log.verbose(f"using profile '{profile.name}' ({profile.url}), mode '{args.mode}'")

    dispatch = {"send": send.run_send, "listen": listen.run_listen, "ask": ask.run_ask}
    try:
        return dispatch[args.mode](args, profile, log)
    except NotImplementedError as e:
        log.error(f"{args.mode}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
