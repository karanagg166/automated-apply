"""Credential-free pinned public HTML/robots reader; never renders or follows links."""

import http.client
import ipaddress
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from backend.app.browser.company_source_html import extract
from backend.app.browser.company_source_policy import (
    AGENT,
    MAX_HTML,
    MAX_ROBOTS,
    robots_permit,
    source_url,
)
from backend.app.core.pinned_http import connect_pinned


def fetch(data):
    testing = data.get("testing") is True
    url = source_url(data["url"], testing=testing)
    parsed = urlsplit(url)
    address = ipaddress.ip_address(data["address"])
    if not address.is_global and not (
        testing and str(address) == parsed.hostname == "127.0.0.1"
    ):
        raise ValueError("invalid_source_address")
    deadline = time.monotonic() + 10

    def read(path, maximum, mimes, *, robots=False):
        connection = connect_pinned(
            parsed.hostname,
            str(address),
            parsed.port,
            tls=parsed.scheme == "https",
            timeout=4,
        )
        try:
            connection.request(
                "GET",
                path,
                headers={
                    "User-Agent": AGENT + "/1",
                    "Accept-Encoding": "identity",
                    "Accept": ", ".join(mimes),
                },
            )
            response = connection.getresponse()
            if robots and response.status == 404:
                return ""
            if response.status != 200:
                raise ValueError("source_requires_manual_access")
            types = response.headers.get_all("Content-Type", [])
            lengths = response.headers.get_all("Content-Length", [])
            if (
                len(types) != 1
                or types[0].split(";")[0].strip().lower() not in mimes
                or len(lengths) > 1
                or (lengths and (not lengths[0].isdigit() or int(lengths[0]) > maximum))
                or response.getheader("Content-Encoding", "identity").casefold()
                != "identity"
                or (
                    "charset=" in types[0].casefold()
                    and not types[0]
                    .casefold()
                    .rstrip()
                    .endswith(("charset=utf-8", 'charset="utf-8"'))
                )
            ):
                raise ValueError("unsupported_source_response")
            body = bytearray()
            while True:
                if time.monotonic() > deadline:
                    raise ValueError("source_timeout")
                chunk = response.read(min(32768, maximum + 1 - len(body)))
                if not chunk:
                    break
                body.extend(chunk)
                if len(body) > maximum:
                    raise ValueError("source_too_large")
            if lengths and len(body) != int(lengths[0]):
                raise ValueError("incomplete_source")
            return body.decode("utf-8-sig", errors="strict")
        finally:
            connection.close()

    robots = read("/robots.txt", MAX_ROBOTS, ["text/plain"], robots=True)
    if not robots_permit(robots, parsed.path):
        raise ValueError("source_robots_requires_manual_reading")
    text = read(parsed.path, MAX_HTML, ["text/html"])
    if re.search(
        r"captcha|verify (?:that )?you are human|checking your browser|access denied|sign in to continue|one-time-code|type\s*=\s*['\"]?password",
        text,
        re.I,
    ):
        raise ValueError("source_requires_manual_access")
    return {**extract(text, data["company_name"]), "source_url": url}


def main():
    try:
        raw = sys.stdin.buffer.read(8193)
        if len(raw) > 8192:
            raise ValueError()
        result = fetch(json.loads(raw))
    except (
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        OSError,
        http.client.HTTPException,
    ):
        # Never reflect URL paths, response bodies or exception text to logs/API.
        result = {
            "error": "Public company source unavailable or unsupported; read it manually"
        }
    sys.stdout.write(json.dumps(result))


if __name__ == "__main__":
    main()
