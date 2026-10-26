"""Credential-free, pinned public static GET. Never executes asset contents."""

import base64
import http.client
import ipaddress
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from backend.app.browser.asset_policy import (
    MAX_ASSET_BYTES,
    MIMES,
    asset_origin,
    asset_target,
)
from backend.app.core.pinned_http import connect_pinned

SAFE_HEADERS = {
    "access-control-allow-origin",
    "access-control-allow-credentials",
    "cross-origin-resource-policy",
    "cross-origin-embedder-policy",
    "content-security-policy",
    "x-content-type-options",
}


class AssetError(Exception):
    """Fixed categories only; never a URL, header value or remote body."""


def fetch(data):
    try:
        testing = data.get("testing") is True
        _, parsed = asset_target(data["url"], data["kind"], testing=testing)
        address = ipaddress.ip_address(data["address"])
        if not address.is_global and not (
            testing and str(address) == parsed.hostname == "127.0.0.1"
        ):
            raise ValueError()
        headers = {
            "Accept-Encoding": "identity",
            "User-Agent": "AutomatedApply-PublicAssets/1",
        }
        if data.get("origin"):
            approved = asset_origin(data["origin"], testing=testing)
            source = urlsplit_origin(approved)
            headers["Origin"] = source
    except (ValueError, KeyError, TypeError):
        raise AssetError("invalid_asset") from None
    connection = connect_pinned(
        parsed.hostname,
        str(address),
        parsed.port or (443 if parsed.scheme == "https" else 80),
        tls=parsed.scheme == "https",
    )
    try:
        connection.request("GET", parsed.path, headers=headers)
        response = connection.getresponse()
        if response.status != 200:
            raise AssetError("asset_unavailable_or_requires_manual_access")
        content_type = response.getheader("Content-Type", "")
        mime = content_type.split(";")[0].lower().strip()
        if mime not in MIMES[data["kind"]]:
            raise AssetError("unsupported_asset_type")
        if len(content_type) > 256 or any(
            ord(c) < 32 or ord(c) == 127 for c in content_type
        ):
            raise AssetError("unsupported_asset_headers")
        if response.getheader("Content-Encoding", "identity").lower() != "identity":
            raise AssetError("unsupported_asset_encoding")
        length = response.getheader("Content-Length")
        if length is not None and (
            not length.isdigit() or int(length) > MAX_ASSET_BYTES
        ):
            raise AssetError("asset_too_large")
        result_headers = {"content-type": content_type, "cache-control": "no-store"}
        for name, value in response.getheaders():
            if name.lower() in SAFE_HEADERS:
                if (
                    name.lower() in result_headers
                    or len(value) > 4096
                    or any(ord(c) < 32 or ord(c) == 127 for c in value)
                ):
                    raise AssetError("unsupported_asset_headers")
                result_headers[name.lower()] = value
        body, deadline = bytearray(), time.monotonic() + 8
        while True:
            if time.monotonic() > deadline:
                raise AssetError("asset_timeout")
            chunk = response.read(min(65536, MAX_ASSET_BYTES + 1 - len(body)))
            if not chunk:
                break
            body.extend(chunk)
            if len(body) > MAX_ASSET_BYTES:
                raise AssetError("asset_too_large")
        if length is not None and len(body) != int(length):
            raise AssetError("incomplete_asset")
        return {
            "body": base64.b64encode(body).decode("ascii"),
            "headers": result_headers,
        }
    finally:
        connection.close()


def urlsplit_origin(value):
    from urllib.parse import urlsplit

    source = urlsplit(value)
    default = 443 if source.scheme == "https" else 80
    return f"{source.scheme}://{source.hostname}" + (
        f":{source.port}" if source.port != default else ""
    )


def main():
    try:
        data = json.loads(sys.stdin.buffer.read(8192))
        output = fetch(data)
    except AssetError as error:
        output = {"error": str(error)}
    except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException):
        output = {"error": "asset_network_unavailable"}
    sys.stdout.write(json.dumps(output))


if __name__ == "__main__":
    main()
