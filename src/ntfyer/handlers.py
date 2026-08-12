"""
Handler execution shared by listen/ask.

Security model (locked, see README): `cmd` is parsed once with shlex.split()
so quoting behaves like a shell would, then the literal substring %MESSAGE%
is replaced within each already-split token with the message content. The
resulting argv list is run with subprocess.run(argv, shell=False) — the
message is never re-parsed as shell syntax, so it can't inject commands
regardless of its content.
"""

import os
import shlex
import subprocess


class HandlerError(Exception):
    pass


def run_handler(cmd: str, message: str, input_mode: str) -> int:
    tokens = shlex.split(cmd)
    if not tokens:
        raise HandlerError("--handler command is empty")

    has_placeholder = "%MESSAGE%" in cmd
    mode = "arg" if has_placeholder else input_mode
    if mode == "arg" and not has_placeholder:
        raise HandlerError("--handler-input arg requires %MESSAGE% in --handler")

    if mode == "arg":
        argv = [tok.replace("%MESSAGE%", message) for tok in tokens]
    else:
        argv = tokens

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
