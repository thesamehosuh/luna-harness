# SPDX-License-Identifier: Apache-2.0
# Attribution and inherited MIT notices: OPENCODE_NOTICES.txt
"""Translate explicit chat image attachments to native OpenCode file references."""
from __future__ import annotations

import base64
import hashlib
import os
import re
import tempfile
import urllib.parse

from luna_core.opencode_install import runtime_root


def prompt_parts(content) -> tuple[str, list[dict]]:
    if content is None:
        return "", []
    if isinstance(content, str):
        return content, []
    if not isinstance(content, list):
        raise ValueError("Unsupported message content for OpenCode.")
    texts, files = [], []
    for part in content:
        kind = part.get("type") if isinstance(part, dict) else None
        if kind in {"text", "input_text"}:
            texts.append(str(part.get("text", "")))
            continue
        if kind not in {"image_url", "input_image"}:
            raise ValueError("This attachment type is unavailable in the OpenCode engine.")
        image = part.get("image_url", "")
        uri = image.get("url", "") if isinstance(image, dict) else image
        if not isinstance(uri, str):
            raise ValueError("Malformed OpenCode image attachment.")
        if uri.startswith("data:"):
            match = re.fullmatch(r"data:(image/(?:png|jpeg|webp|gif));base64,([A-Za-z0-9+/=\r\n]+)", uri)
            if not match or len(uri) > 48 * 1024 * 1024:
                raise ValueError("Unsupported or oversized image attachment.")
            data = base64.b64decode(re.sub(r"\s", "", match[2]), validate=True)
            extension = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}[match[1]]
            directory = runtime_root() / "attachments"
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            path = directory / (hashlib.sha256(data).hexdigest() + extension)
            descriptor, temporary = tempfile.mkstemp(prefix=".image-", dir=directory)
            try:
                with os.fdopen(descriptor, "wb") as output:
                    output.write(data)
                try:
                    os.link(temporary, path)
                except FileExistsError:
                    if path.is_symlink() or not path.is_file():
                        raise ValueError("The image snapshot path is not a regular file.")
            finally:
                os.unlink(temporary)
            path.touch()  # A reused snapshot starts a fresh retention window.
            uri = path.resolve().as_uri()
        elif urllib.parse.urlparse(uri).scheme not in {"http", "https"}:
            # Never let a message-supplied file:// URI read an arbitrary host file.
            raise ValueError("Images must be attached bytes or an HTTP(S) image URL.")
        files.append({"name": f"image-{len(files) + 1}", "uri": uri})
    return "\n".join(texts), files
