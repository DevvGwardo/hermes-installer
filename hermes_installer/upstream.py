from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


UPSTREAM_REPO = "NousResearch/hermes-agent"
UPSTREAM_DEFAULT_REF = "main"
UPSTREAM_RAW_BASE = f"https://raw.githubusercontent.com/{UPSTREAM_REPO}"
UPSTREAM_RELEASE_API = f"https://api.github.com/repos/{UPSTREAM_REPO}/releases/latest"


@dataclass(frozen=True)
class ResolvedRef:
    ref: str
    source: str


def latest_release_ref(timeout: float = 5.0) -> ResolvedRef:
    request = Request(
        UPSTREAM_RELEASE_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "hermes-installer",
        },
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return ResolvedRef(ref=UPSTREAM_DEFAULT_REF, source="fallback")

    tag_name = payload.get("tag_name")
    if not tag_name:
        return ResolvedRef(ref=UPSTREAM_DEFAULT_REF, source="fallback")
    return ResolvedRef(ref=tag_name, source="release")


def script_url(ref: str, script_name: str) -> str:
    return f"{UPSTREAM_RAW_BASE}/{ref}/scripts/{script_name}"

