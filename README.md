# ntfyer

A CLI tool for sending, listening for, and requesting replies to
[ntfy.sh](https://ntfy.sh) / self-hosted [ntfy](https://docs.ntfy.sh/)
notifications.

> Working title — the name is subject to change. The whole codebase derives
> its name from a single constant (`PROG` in `src/ntfyer/meta.py`), so a
> rename is a one-line change plus a directory rename.

**Status:** all three modes (`send`, `listen`, `ask`) plus handler execution
are fully implemented.

**Note on flag placement:** global flags (`--ini`, `--profile`, `--log-file`,
`--syslog`/`--no-syslog`, `--verbose`, `--debug`, `--trace`) go **after** the
mode word, e.g. `ntfyer send --debug ...`, not `ntfyer --debug send ...` —
argparse's subparser handling silently drops shared flags placed before the
mode word, so ntfyer simply doesn't define them there. `--version` is the
only flag that works before the mode.

## Modes

- **`send`** — publish a single notification.
- **`listen`** — wait for messages on a topic and run a handler when one arrives.
- **`ask`** — send a message, then wait for a reply on the same topic and run a handler.

Sending logic is modular and shared between `send` and `ask`. Handler
execution is modular and shared between `listen` and `ask`.

## Install

```
pipx install .
```

(from a checkout of this repo; not yet published anywhere)

## Configuration

Config comes from an INI file and/or CLI arguments — **CLI arguments always
win**. The default config path is `~/.config/ntfyer/ntfyer.ini`; override it
per-invocation with `--ini PATH`.

Server connections are grouped into **profiles**, since you may want several
profiles even against the same server (different topics, different auth).
Each profile lives in its own `[profile:NAME]` section:

```ini
[default]
profile = home

[profile:home]
url      = https://ntfy.sh
topic    = my-default-topic

[profile:work-selfhosted]
url      = https://ntfy.example.com
topic    = alerts
username = myuser
password = mypassword
# or, instead of username/password:
# token  = tk_abc123...
```

- `[default] profile=` picks the profile used when `--profile` isn't given.
- A profile may use **either** username/password (basic auth) **or** a
  token, never both — ntfyer errors out on ambiguous auth rather than
  guessing which one you meant.
- With no profile configured at all, ntfyer talks to the public
  `https://ntfy.sh` with no auth.

### Environment variable overrides

Each profile field can be overridden by an environment variable, which
takes precedence over the INI file but loses to an explicit CLI flag:

| Field      | Env var             |
|------------|----------------------|
| profile    | `NTFYER_PROFILE`     |
| url        | `NTFYER_URL`         |
| topic      | `NTFYER_TOPIC`       |
| username   | `NTFYER_USERNAME`    |
| password   | `NTFYER_PASSWORD`    |
| token      | `NTFYER_TOKEN`       |

### Precedence summary

`CLI flag > env var > INI [profile:NAME] > built-in default`

## Logging

Logging is handled by a vendored copy of `AppLogger`
(`src/ntfyer/_vendor/applogger.py`, from `mattlib`; kept in sync manually).

- `--verbose` / `-v` — high-level steps and actions taken.
- `--debug` / `-d` — everything `--verbose` shows, plus full parsed
  arguments and data-structure dumps (more verbose than `--verbose`).
- `--trace` — everything `--debug` shows, plus raw request/response dumps.
- `--log-file PATH` — also write log output to PATH.
- `--syslog` / `--no-syslog` — **syslog logging is on by default**; disable
  with `--no-syslog`.

The INI file can also carry a `[logging]` section (`level=`, `logfile=`,
`syslog=`) as a fallback when the equivalent CLI flag isn't given — see
`applogger.py`'s docstring for details.

## Tag/emoji shortcodes

```
ntfyer --help-tags          # ~120 common shortcodes for notification use cases, grouped by category
ntfyer --help-tags-full     # the full ntfy shortcode table (~1800 entries) — pipe to grep to search it
```

Both print a category-grouped table (emoji, shortcode(s), description) to
stdout and exit immediately — no mode word needed, same as `--version`
(and for the same reason, neither works *after* a mode word, e.g. `ntfyer
send --help-tags` isn't valid — only before it).

The data is vendored from ntfy's own repo (`web/src/app/emojis.js`, itself
generated from [github/gemoji](https://github.com/github/gemoji)'s
`emoji.json`) as a packaged JSON file (`src/ntfyer/data/emojis.json`), not
fetched at runtime — works offline, doesn't depend on an external endpoint
staying up. `--help-tags`' shorter table is a curated subset of shortcode
names, filtered from that same real data rather than hand-typed separately,
so every entry it shows is verified to actually exist. Any alias listed for
an entry is a valid `--tags` value, not just the first one shown.

## Usage

### send

```
ntfyer send --priority urgent --tags warning,skull this is the message
```

- The message is every trailing word on the command line, joined with
  spaces. To read the message from stdin instead, pass `--stdin` or give a
  literal `-` as the message — stdin is **never** read implicitly. A single
  trailing newline from the piped input is stripped; everything else is
  sent as-is.
- Sending an empty notification is refused client-side: you need at least
  one of a message, `--title`, `--attach`, or `--attach-url`.
- `--topic TOPIC` overrides the active profile's default topic; one of
  `--topic` or a profile `topic=` is required.
- `--priority` accepts `min|low|default|high|urgent` or `1`-`5`.
- `--tags TAG,TAG,...` — a tag that exactly matches a known emoji shortcode
  (e.g. `warning`, `skull`) renders as that emoji; anything else shows as a
  plain text badge. See **Tag/emoji shortcodes** below to look shortcodes up.
- `--title TEXT`
- `--attach PATH` (upload a local file) or `--attach-url URL` (link an
  externally-hosted file) — mutually exclusive, ntfy supports exactly one
  attachment per message.
- `--email ADDRESS`, `--call PHONE` — additional ntfy delivery methods
  (both are subject to whatever the target server/plan allows — e.g. public
  ntfy.sh rejects anonymous `--call` with a clear error).

Publishing always uses ntfy's header-based publish API (one `POST` to
`{server}/{topic}`, fields as `X-*` headers) rather than the JSON endpoint —
one code path handles every combination, including a local `--attach`
upload (which occupies the request body, so `message` moves to the
`X-Message` header in that case only).

#### Action buttons

```
--action 'TYPE,LABEL,URL[,key=value...]'
```

Repeatable; `TYPE` is `view`, `http`, or `broadcast`, matching ntfy's own
action types. `view`/`http` require `URL` as the third field. Extra
`key=value` fields are type-specific:

- `http`: `method=`, `headers.HeaderName=value` (repeatable), `body=`
- `broadcast`: `intent=`, `extras.key=value` (repeatable)
- any type: `clear=true`

```
ntfyer send --topic alerts --action 'view,Open Dashboard,https://example.com' \
  --action 'http,Turn Off,https://api.example.com/off,method=PUT,body={"state":"off"}' \
  disk is full
```

A literal comma or semicolon inside a field (e.g. inside a JSON `body=`
value) needs a backslash escape (`\,`, `\;`), the same way ntfy's own raw
`X-Actions` header syntax does.

`--actions-json JSON` is an escape hatch that takes a raw JSON array of
ntfy action objects directly, and combines with `--action` if both are
given (structured actions first, then the JSON ones).

### listen

```
ntfyer listen --topic my-topic --handler '/path/to/script.sh %MESSAGE%'
```

- Subscribes via ntfy's JSON message stream (`/topic/json`). A dropped
  connection reconnects automatically; a hard failure on the initial
  connect (bad auth, unreachable host) fails immediately instead of
  retrying forever.
- Runs forever until Ctrl-C by default (exits 0 — this is a normal way to
  stop it, not an error). `--once` exits 0 after the first message;
  `--timeout SECONDS` gives up and exits non-zero if nothing arrives in
  time (checked as each line — including ntfy's periodic keepalives —
  comes in, so it's accurate to within about a keepalive interval).
- With no `--handler`, `listen` just prints each received message
  (`title: message`, or bare `message` with no title) — a plain "watch this
  topic" mode.
- `--handler CMD` — see **Handlers** below. A handler failure (bad command,
  non-zero exit) is logged and `listen` keeps running, unless `--once` is
  also given, in which case it exits right after regardless of how the
  handler went.

### ask

```
ntfyer ask --topic my-topic --priority high "reboot the server?" --handler '/path/to/script.sh %MESSAGE%'
```

Sends a message on the active topic, then opens a fresh subscription on that
same topic and treats the first message to arrive on it as the reply — since
the subscription is only opened *after* the send completes, the message
you just sent isn't redelivered; only genuinely new messages count.
Accepts every `send` flag plus every `listen`/wait flag (`--timeout`,
`--handler`, `--handler-input`). Exits 0 as soon as a reply is handled;
`--timeout` gives up and exits non-zero if nothing replies in time. This is
inherently racy in the same way any same-topic correlation is (a message
from something other than the intended replier would be taken as the
reply) — a dedicated reply topic was considered and rejected in favor of
simplicity, see the parking lot below if that tradeoff needs revisiting.

## Handlers

A handler is a single command run when `listen`/`ask` receives a message.
Only one handler per invocation (no chaining, for now).

```
--handler 'CMD'
--handler-input stdin|arg|env   # default: stdin
```

`CMD` can reference any of these placeholders, substituted from the
received message (empty string if that field isn't present on it):

| Placeholder  | Value                                    |
|--------------|-------------------------------------------|
| `%MESSAGE%`  | the message body                          |
| `%TITLE%`    | title                                     |
| `%TOPIC%`    | topic name                                |
| `%ID%`       | ntfy's message ID                         |
| `%PRIORITY%` | priority, `1`-`5` (empty if not set)      |
| `%TAGS%`     | raw tags, comma-joined (not emoji-rendered) |
| `%TIME%`     | unix timestamp the message was sent       |

`%TITLE%`/`%TOPIC%`/`%ID%`/`%PRIORITY%`/`%TAGS%`/`%TIME%` are **always**
substituted into `CMD`'s arguments when present, regardless of
`--handler-input` — so the message can be piped to stdin while `%TITLE%` is
still substituted into an argument, in the same invocation. `%MESSAGE%` is
the one exception: if `CMD` contains it, arg mode is used automatically for
the message *specifically* (and `--handler-input` doesn't need to be set);
otherwise the message is delivered per `--handler-input`, piped to stdin
(default) or exposed as `$MESSAGE`.

**Security model:** `CMD` is parsed once with `shlex.split()` — so quoting
behaves the way it would in a shell — and then each placeholder is
substituted as a literal substring *within each already-split token*. The
resulting argv list is executed with `subprocess.run(argv, shell=False)`.
Field content is never re-parsed as shell syntax, so a title or message
containing backticks, `;`, `$(...)`, or quotes cannot inject a second
command or otherwise escape its argument, no matter what it contains.

## Parking lot

Ideas noted for after the first round of features lands:

- A dedicated reply topic for `ask` (instead of same-topic correlation), to
  avoid picking up an unrelated message as the reply.
