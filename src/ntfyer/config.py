import configparser
import dataclasses
import os

from . import meta


class ConfigError(Exception):
    pass


@dataclasses.dataclass
class Profile:
    name: str
    url: str = "https://ntfy.sh"
    topic: str | None = None
    username: str | None = None
    password: str | None = None
    token: str | None = None

    @property
    def auth_type(self) -> str:
        if self.token:
            return "token"
        if self.username or self.password:
            return "basic"
        return "none"


def load_ini(ini_path: str | None) -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()

    if ini_path:
        if not os.path.isfile(ini_path):
            raise ConfigError(f"--ini path does not exist: {ini_path}")
        cfg.read(ini_path)
    elif os.path.isfile(meta.DEFAULT_CONFIG_PATH):
        cfg.read(meta.DEFAULT_CONFIG_PATH)

    return cfg


def _section_for_profile(cfg: configparser.ConfigParser, name: str) -> str:
    return f"profile:{name}"


def resolve_profile(
    cfg: configparser.ConfigParser,
    *,
    profile_name: str | None = None,
    overrides: dict | None = None,
) -> Profile:
    """
    Resolve the active profile's connection settings.

    Precedence (highest first): explicit `overrides` (CLI args) > env vars >
    ini [profile:NAME] section > built-in defaults.

    profile_name precedence: overrides['profile'] > $NTFYER_PROFILE >
    ini [default] profile= > None (synthetic no-auth ntfy.sh profile).
    """
    overrides = overrides or {}

    name = (
        overrides.get("profile")
        or os.environ.get(meta.env_var("PROFILE"))
        or cfg.get("default", "profile", fallback=None)
    )

    values = {"url": "https://ntfy.sh", "topic": None, "username": None,
              "password": None, "token": None}

    if name:
        section = _section_for_profile(cfg, name)
        if not cfg.has_section(section):
            raise ConfigError(f"profile '{name}' not found (expected INI section [{section}])")
        for key in values:
            values[key] = cfg.get(section, key, fallback=values[key])
    else:
        name = "default"

    for key in ("url", "topic", "username", "password", "token"):
        env_val = os.environ.get(meta.env_var(key.upper()))
        if env_val is not None:
            values[key] = env_val

    for key in ("url", "topic", "username", "password", "token"):
        if overrides.get(key) is not None:
            values[key] = overrides[key]

    profile = Profile(name=name, **values)

    has_basic = bool(profile.username or profile.password)
    if profile.token and has_basic:
        raise ConfigError(
            f"profile '{name}' has both a token and username/password set — "
            "ambiguous auth, remove one"
        )
    if has_basic and not (profile.username and profile.password):
        raise ConfigError(
            f"profile '{name}' has only one of username/password set — both are required for basic auth"
        )

    return profile
