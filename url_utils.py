"""URL validation helpers used before browser redirects."""

from __future__ import annotations

from urllib.parse import urlsplit


def safe_next_url(target: str | None) -> str:
    """Return a same-origin path, or an empty string for unsafe redirects."""
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return ""
    try:
        parsed = urlsplit(target)
    except ValueError:
        return ""
    if parsed.scheme or parsed.netloc:
        return ""
    return target
