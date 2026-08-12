"""
Received-attachment download and safe local storage, shared by listen/ask.

attachment.name comes from the message sender — untrusted. Filenames are
built from os.path.basename() only, with an extra check that the resolved
path still lands inside save_dir, as defense in depth against path
traversal (e.g. a crafted name like "../../etc/cron.d/evil").
"""

import os
import secrets

from . import ntfy_api
from .config import Profile

MAX_ATTACHMENT_BYTES = 100 * 1024 * 1024  # 100 MiB
MAX_FILENAME_ATTEMPTS = 10


class AttachmentError(Exception):
    pass


def sanitize_filename(name: str) -> str:
    name = os.path.basename((name or "").strip())
    if not name or name in (".", ".."):
        return "attachment"
    return name


def save_attachment(profile: Profile, msg: dict, save_dir: str) -> str | None:
    """
    Download msg's attachment (if any) into save_dir. Returns the local
    path, or None if the message has no attachment. Raises AttachmentError
    on failure (network, HTTP, size limit, filesystem) — save_dir isn't
    checked for existence here, that's the caller's job upfront.
    """
    attachment = msg.get("attachment")
    if not attachment or not attachment.get("url"):
        return None

    name = sanitize_filename(attachment.get("name") or "attachment")
    stem, ext = os.path.splitext(name)
    save_dir_real = os.path.realpath(save_dir)

    for attempt in range(MAX_FILENAME_ATTEMPTS):
        candidate = name if attempt == 0 else f"{stem}-{secrets.token_hex(4)}{ext}"
        dest_path = os.path.join(save_dir, candidate)

        if os.path.dirname(os.path.realpath(dest_path)) != save_dir_real:
            raise AttachmentError(f"refusing to write outside --save-attachment dir: {candidate!r}")

        try:
            fd = os.open(dest_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            continue

        try:
            with os.fdopen(fd, "wb") as f:
                ntfy_api.download_attachment(
                    profile, attachment["url"], f, max_bytes=MAX_ATTACHMENT_BYTES,
                )
        except ntfy_api.DownloadError as e:
            os.unlink(dest_path)
            raise AttachmentError(str(e)) from e
        except OSError as e:
            os.unlink(dest_path)
            raise AttachmentError(f"could not write {dest_path!r}: {e}") from e
        except BaseException:
            if os.path.exists(dest_path):
                os.unlink(dest_path)
            raise

        return dest_path

    raise AttachmentError(
        f"could not allocate a unique filename for {name!r} after {MAX_FILENAME_ATTEMPTS} attempts"
    )
