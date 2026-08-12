import os

# Single source of truth for the tool's name. Change this to rename the
# whole tool — prog name, config path, and env var prefix all derive from it.
PROG = "ntfyer"

VERSION = "0.1.0"

ENV_PREFIX = PROG.upper()

DEFAULT_CONFIG_PATH = os.path.expanduser(f"~/.config/{PROG}/{PROG}.ini")


def env_var(suffix: str) -> str:
    return f"{ENV_PREFIX}_{suffix}"
