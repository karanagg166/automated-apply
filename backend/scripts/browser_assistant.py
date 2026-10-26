"""Narrow local orchestration for AGY. Business logic stays behind the authenticated API."""

import argparse
import json
import os
import sys
from urllib.parse import urlsplit
from uuid import UUID

import httpx

OPERATIONS = {
    "get_browser_policy": ("GET", "/policy"),
    "prepare_application": ("POST", ""),
    "open_application": ("POST", "/{packet_id}/open"),
    "analyze_application": ("POST", "/{packet_id}/actions", "analyze"),
    "fill_application": ("POST", "/{packet_id}/actions", "fill"),
    "preview_application": ("GET", "/{packet_id}"),
    "get_application_status": ("GET", "/{packet_id}"),
    "get_browser_operation": ("GET", "/{packet_id}/operation"),
    "review_submission": ("POST", "/{packet_id}/submission-preview"),
    "submit_approved_application": ("POST", "/{packet_id}/submit"),
    "recover_submission": ("POST", "/{packet_id}/recover-submission"),
    "take_over_application": ("POST", "/{packet_id}/actions", "take_over"),
    "cancel_application": ("POST", "/{packet_id}/actions", "cancel"),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=OPERATIONS)
    parser.add_argument("--packet-id", type=UUID)
    parser.add_argument("--revision", type=int)
    parser.add_argument("--origin", default="http://127.0.0.1:8000")
    parser.add_argument("--reviewed-values", action="store_true")
    parser.add_argument("--confirmed-page-context", action="store_true")
    parser.add_argument("--include-private-answers", action="store_true")
    args = parser.parse_args()
    target = urlsplit(args.origin)
    if (
        target.scheme != "http"
        or target.hostname != "127.0.0.1"
        or target.username
        or target.password
        or target.path
        or target.query
        or target.fragment
    ):
        parser.error("Only a loopback FastAPI origin is permitted")
    token = os.environ.get("JOB_AGENT_API_TOKEN", "")
    if not token:
        parser.error(
            "Set the existing JOB_AGENT_API_TOKEN in the private process environment"
        )
    operation = OPERATIONS[args.operation]
    method, path = operation[:2]
    if "{packet_id}" in path and not args.packet_id:
        parser.error("--packet-id is required")
    path = path.format(packet_id=args.packet_id)
    payload = None
    if args.operation in {
        "prepare_application",
        "open_application",
        "review_submission",
        "submit_approved_application",
    }:
        # Owner inputs from stdin, never from a website, command line secret or arbitrary file read.
        raw = sys.stdin.read(65537)
        if len(raw) > 65536:
            parser.error("Input exceeds 64 KiB")
        try:
            payload = json.loads(raw)
        except ValueError:
            parser.error("Provide JSON on stdin")
    elif args.operation == "recover_submission":
        payload = {}
    elif method == "POST":
        if args.revision is None:
            parser.error("--revision is required")
        payload = {
            "expected_revision": args.revision,
            "action": operation[2],
            "confirm_reviewed_values": args.reviewed_values,
            "confirm_page_context": args.confirmed_page_context,
        }
    try:
        with httpx.Client(
            timeout=60, trust_env=False, follow_redirects=False
        ) as client:
            if args.operation == "cancel_application":
                control = client.get(
                    args.origin
                    + "/api/v1/browser-applications"
                    + path.removesuffix("/actions")
                    + "/operation",
                    headers={"Authorization": "Bearer " + token},
                )
                if control.status_code >= 400:
                    print(
                        json.dumps(
                            {
                                "ok": False,
                                "status": control.status_code,
                                "detail": "Cannot inspect local browser operation",
                            }
                        )
                    )
                    return 1
                active = control.json().get("active_operation")
                payload["operation_id"] = active["id"] if active else None
            response = client.request(
                method,
                args.origin + "/api/v1/browser-applications" + path,
                headers={"Authorization": "Bearer " + token},
                json=payload,
            )
        if response.status_code >= 400:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "status": response.status_code,
                        "detail": response.json().get("detail", "Request failed"),
                    }
                )
            )
            return 1
        data = response.json()
        if args.include_private_answers or args.operation == "get_browser_policy":
            print(json.dumps(data))
        else:
            packet = data.get("packet", data)
            print(
                json.dumps(
                    {
                        "ok": True,
                        "packet_id": packet.get("id")
                        or data.get("packet_id")
                        or (str(args.packet_id) if args.packet_id else None),
                        "attempt_id": data.get("attempt_id"),
                        "submission_state": data.get("state"),
                        "revision": packet.get("revision", data.get("packet_revision")),
                        "active_operation": data.get("active_operation"),
                        "cancellation_pending": data.get("cancellation_pending", False),
                        "lifecycle_state": packet.get("lifecycle_state"),
                        "connected": data.get("connected"),
                        "diagnostic": (data.get("analysis") or {}).get("diagnostic"),
                        "automated_submission_enabled": False,
                    }
                )
            )
        return 0
    except (httpx.HTTPError, ValueError):
        print(
            json.dumps(
                {
                    "ok": False,
                    "detail": "Local operation unavailable; inspect status before retrying",
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
