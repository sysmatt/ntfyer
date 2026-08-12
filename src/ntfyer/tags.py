"""
ntfy emoji/tag shortcode reference, for --help-tags / --help-tags-full.

Data source: ntfy's own web/src/app/emojis.js (github.com/binwiederhier/ntfy,
Apache-2.0), itself generated from github/gemoji's emoji.json (MIT). Vendored
here as a packaged JSON data file (data/emojis.json) rather than fetched at
runtime, so this works offline and doesn't depend on an external endpoint.

Any alias in an entry's list is a valid --tags value that ntfy renders as
that emoji — not just the first one.
"""

import importlib.resources
import json

# A hand-picked common subset for the shorter --help-tags table: notification
# use cases (alerts, tech, time, comms, security, transport, money, misc).
# Each name is verified to exist in data/emojis.json (see the smoke test) —
# this is a filter over the real dataset, not a separately hand-typed one.
CURATED_ALIASES = frozenset({
    "warning", "rotating_light", "sos", "no_entry", "no_entry_sign", "stop_sign", "white_check_mark", "heavy_check_mark",
    "x", "heavy_multiplication_x", "question", "grey_question", "exclamation", "grey_exclamation", "bangbang", "triangular_flag_on_post",
    "checkered_flag", "computer", "desktop_computer", "iphone", "telephone_receiver", "phone", "satellite", "floppy_disk",
    "printer", "keyboard", "battery", "electric_plug", "robot", "alarm_clock", "stopwatch", "hourglass",
    "hourglass_flowing_sand", "calendar", "date", "sunny", "partly_sunny", "cloud", "cloud_with_rain", "zap",
    "fire", "droplet", "ocean", "tornado", "snowflake", "email", "envelope", "incoming_envelope",
    "speech_balloon", "thought_balloon", "loudspeaker", "mega", "bell", "no_bell", "lock", "unlock",
    "key", "closed_lock_with_key", "shield", "detective", "thumbsup", "thumbsdown", "clap", "wave",
    "eyes", "thinking", "muscle", "raised_hands", "pray", "car", "truck", "ambulance",
    "fire_engine", "police_car", "rocket", "airplane", "ship", "anchor", "moneybag", "dollar",
    "credit_card", "chart_with_upwards_trend", "chart_with_downwards_trend", "package", "mailbox", "house", "office", "factory",
    "gear", "wrench", "hammer", "hammer_and_wrench", "toolbox", "recycle", "skull", "skull_and_crossbones",
    "ghost", "bug", "poop", "boom", "sparkles", "tada", "confetti_ball", "trophy",
    "star", "star2", "heart", "broken_heart", "o", "pushpin", "round_pushpin", "bookmark",
    "label", "100", "negative_squared_cross_mark", "construction", "biohazard", "radioactive", "globe_with_meridians", "earth_americas",
})


def load_emojis() -> list[dict]:
    raw = importlib.resources.files("ntfyer.data").joinpath("emojis.json").read_text(encoding="utf-8")
    return json.loads(raw)


def format_table(entries: list[dict]) -> str:
    by_category: dict[str, list[dict]] = {}
    for e in entries:
        by_category.setdefault(e["category"], []).append(e)

    lines = []
    for category in sorted(by_category):
        lines.append(f"=== {category} ===")
        for e in sorted(by_category[category], key=lambda e: e["aliases"][0]):
            aliases = ", ".join(e["aliases"])
            lines.append(f"{e['emoji']}  {aliases} — {e['description']}")
        lines.append("")

    return "\n".join(lines).rstrip("\n")


def print_tags(*, full: bool = False) -> None:
    data = load_emojis()
    if not full:
        data = [e for e in data if any(a in CURATED_ALIASES for a in e["aliases"])]
    print(format_table(data))
