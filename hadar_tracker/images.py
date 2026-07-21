from __future__ import annotations

import os

import requests

IMAGE_BASE = "https://www.sponser.co.il/ForumFiles/"

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def download_image(msg_file_name: str, images_dir: str, timeout: int = 30) -> str:
    """Download an attached picture to images_dir and return its local path.

    Plain HTTP GET of https://www.sponser.co.il/ForumFiles/{msg_file_name}.
    Raises for HTTP errors so a missing/blocked file surfaces loudly.

    msg_file_name comes from externally-sourced, scraped data, so the local
    destination path is derived from its basename only (the remote URL still
    uses the original value to fetch the correct file). If the basename is
    empty or still contains path separators/"..", a ValueError is raised
    instead of writing outside images_dir.
    """
    safe_name = os.path.basename(msg_file_name)
    if not safe_name or safe_name in (os.curdir, os.pardir) or "/" in safe_name or "\\" in safe_name or ".." in safe_name:
        raise ValueError(f"Unsafe msg_file_name for local path: {msg_file_name!r}")

    os.makedirs(images_dir, exist_ok=True)
    response = requests.get(
        IMAGE_BASE + msg_file_name,
        headers={"User-Agent": _USER_AGENT},
        timeout=timeout,
    )
    response.raise_for_status()
    dest = os.path.join(images_dir, safe_name)
    with open(dest, "wb") as handle:
        handle.write(response.content)
    return dest
