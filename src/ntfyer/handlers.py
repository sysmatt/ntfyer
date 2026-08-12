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

%ATTACHMENT% is the one placeholder that does NOT follow the "absent field
substitutes as empty string" rule above, when it appears as its own
standalone token (not embedded in a larger argument): with no attachment,
that token is omitted from argv entirely, rather than becoming a stray ''
argument — a zero-length argument is enough to break many argparse-based
handler tools. With attachment_arg also given, both the flag name and the
path are included together (as two argv entries) when there's a file, or
neither when there isn't — never just one or the other. A %ATTACHMENT%
embedded inside a larger token (e.g. "file=%ATTACHMENT%") can't be omitted
without leaving the surrounding text dangling, so that case still falls
back to plain substitution (empty string if absent) — pair a literal flag
directly with a bare %ATTACHMENT% token via attachment_arg, not by hand,
if you want the omit-when-absent behavior for both.

At --debug, the fully-substituted argv is logged via shlex.join() right
before it runs — quoted the way a shell would, so an empty-string argument
or one containing spaces is visually unambiguous in the log line.
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
    log,
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
        # %ATTACHMENT% as a standalone token: with a file, expand to
        # (attachment_arg, path) or just (path); with no file, omit the
        # token from argv entirely instead of leaving a stray '' argument.
        if tok == "%ATTACHMENT%":
            if attachment_path:
                if attachment_arg:
                    argv.append(attachment_arg)
                argv.append(attachment_path)
            continue
        for key, val in subs.items():
            tok = tok.replace(key, val)
        argv.append(tok)

    if not argv:
        raise HandlerError(
            "--handler resolved to no command (its only token was %ATTACHMENT%, and this message has no attachment)"
        )

    message = subs["%MESSAGE%"]
    kwargs = {}
    if mode == "stdin":
        kwargs["input"] = message.encode("utf-8")
    elif mode == "env":
        env = os.environ.copy()
        env["MESSAGE"] = message
        kwargs["env"] = env

    log.debug(f"handler command ({mode} mode): {shlex.join(argv)}")

    try:
        result = subprocess.run(argv, shell=False, **kwargs)
    except OSError as e:
        raise HandlerError(f"could not run handler {argv[0]!r}: {e}") from e

    return result.returncode
