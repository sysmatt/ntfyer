"""
Handler execution shared by listen/ask.

Security model (locked, see README): `cmd` is parsed once with shlex.split()
so quoting behaves like a shell would, then each %KEY% placeholder is
replaced within each already-split token with the corresponding field's
content. The resulting argv list is run with subprocess.run(argv,
shell=False) — field content is never re-parsed as shell syntax, so it
can't inject commands regardless of what it contains.

%MESSAGE%'s presence is special: it's the only placeholder that decides how
the message body is *delivered* (arg/stdin/env, via --handler-input). Every
other placeholder (%TITLE%, %TOPIC%, %ID%, %PRIORITY%, %TAGS%, %TIME%,
%ATTACHMENT%) is always substituted into the command's arguments if
present, regardless of --handler-input — so e.g. the message can go via
stdin while %TITLE% is still substituted into an argument in the same
invocation. A field absent on a given message (e.g. no title, no
attachment, or --save-attachment wasn't given) substitutes as an empty
string.

%ATTACHMENT% has one more wrinkle: when it appears as its own standalone
token (not embedded in a larger argument) and attachment_arg is given, it
expands to *two* argv entries (attachment_arg, path) instead of one —
but only when there's actually a file to pass; with no attachment it still
just collapses to an empty string, same as every other placeholder.
"""

import os
import shlex
import subprocess


class HandlerError(Exception):
    pass


def _placeholders(msg: dict, attachment_path: str | None) -> dict:
    priority = msg.get("priority")
    time_ = msg.get("time")
    return {
        "%MESSAGE%": msg.get("message", ""),
        "%TITLE%": msg.get("title") or "",
        "%TOPIC%": msg.get("topic") or "",
        "%ID%": msg.get("id") or "",
        "%PRIORITY%": str(priority) if priority is not None else "",
        "%TAGS%": ",".join(msg.get("tags") or []),
        "%TIME%": str(time_) if time_ is not None else "",
        "%ATTACHMENT%": attachment_path or "",
    }


def run_handler(
    cmd: str,
    msg: dict,
    input_mode: str,
    *,
    attachment_path: str | None = None,
    attachment_arg: str | None = None,
) -> int:
    tokens = shlex.split(cmd)
    if not tokens:
        raise HandlerError("--handler command is empty")

    subs = _placeholders(msg, attachment_path)

    has_message_placeholder = "%MESSAGE%" in cmd
    mode = "arg" if has_message_placeholder else input_mode
    if mode == "arg" and not has_message_placeholder:
        raise HandlerError("--handler-input arg requires %MESSAGE% in --handler")

    argv = []
    for tok in tokens:
        # %ATTACHMENT% as a standalone token expands to two argv entries
        # (attachment_arg, path) when there's actually a file to pass —
        # otherwise it falls through to plain substitution like every other
        # placeholder (path, or "" if there's no attachment).
        if tok == "%ATTACHMENT%" and attachment_path and attachment_arg:
            argv.append(attachment_arg)
            argv.append(attachment_path)
            continue
        for key, val in subs.items():
            tok = tok.replace(key, val)
        argv.append(tok)

    message = subs["%MESSAGE%"]
    kwargs = {}
    if mode == "stdin":
        kwargs["input"] = message.encode("utf-8")
    elif mode == "env":
        env = os.environ.copy()
        env["MESSAGE"] = message
        kwargs["env"] = env

    try:
        result = subprocess.run(argv, shell=False, **kwargs)
    except OSError as e:
        raise HandlerError(f"could not run handler {argv[0]!r}: {e}") from e

    return result.returncode
