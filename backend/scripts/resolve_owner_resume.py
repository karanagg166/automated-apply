"""Resolve only the owner-supplied alias, with public DNS validation and TLS IP pinning."""

import http.client
import ipaddress
import json
import socket
import ssl
import subprocess
import sys
from urllib.parse import urljoin, urlsplit

START = "https://url-shortner-jet-rho.vercel.app/r2wL9UE"


def resolve():
    url, hops = START, []
    for _ in range(5):
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
            or not parsed.hostname
            or parsed.fragment
            or len(url) > 2048
        ):
            return dict(status="unresolved", reason="unsafe_destination", hops=hops)
        addresses = sorted(
            {
                item[4][0]
                for item in socket.getaddrinfo(
                    parsed.hostname, 443, type=socket.SOCK_STREAM
                )
            }
        )
        if not addresses or any(
            not ipaddress.ip_address(ip).is_global for ip in addresses
        ):
            return dict(status="unresolved", reason="nonpublic_dns", hops=hops)
        # Connect only to an address already validated; SNI and cert checking use the hostname.
        connection = http.client.HTTPSConnection(parsed.hostname, timeout=5)
        sock = socket.create_connection((addresses[0], 443), timeout=5)
        connection.sock = ssl.create_default_context().wrap_socket(
            sock, server_hostname=parsed.hostname
        )
        try:
            path = (parsed.path or "/") + ("?" + parsed.query if parsed.query else "")
            connection.request(
                "HEAD",
                path,
                headers={
                    "User-Agent": "AutomatedApply-OwnerLinkReview/1",
                    "Accept": "application/pdf",
                },
            )
            response = connection.getresponse()
            content_type = response.getheader("Content-Type", "").split(";")[0]
            hops.append(
                dict(url=url, status=response.status, content_type=content_type)
            )
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader("Location")
                if not location:
                    break
                url = urljoin(url, location)
            elif (
                response.status == 200
                and content_type == "application/pdf"
                and url != START
            ):
                return dict(status="resolved_public_pdf", destination=url, hops=hops)
            else:
                return dict(
                    status="unresolved",
                    reason="resume_destination_not_verified",
                    hops=hops,
                )
        finally:
            connection.close()
    return dict(
        status="unresolved", reason="redirect_limit_or_missing_location", hops=hops
    )


def main():
    if sys.argv[1:] == ["--bounded-worker"]:
        try:
            print(json.dumps(resolve(), indent=2))
        except (OSError, ValueError, http.client.HTTPException):
            print(
                json.dumps(
                    dict(
                        status="unresolved",
                        reason="bounded_network_check_failed",
                        short_url=START,
                    )
                )
            )
        return
    try:
        result = subprocess.run(
            [sys.executable, __file__, "--bounded-worker"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env={"PATH": "/usr/bin:/bin"},
        )
        if result.returncode or len(result.stdout) > 16000:
            raise ValueError("check_failed")
        print(json.dumps(json.loads(result.stdout), indent=2))
    except (subprocess.TimeoutExpired, ValueError):
        print(
            json.dumps(
                dict(
                    status="unresolved",
                    reason="bounded_check_timeout_or_failure",
                    short_url=START,
                )
            )
        )


if __name__ == "__main__":
    main()
