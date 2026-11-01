"""Chrome length-prefixed stdin protocol. stdout contains protocol frames only."""
import json
import select
import struct
import sys
import time
from pathlib import Path

import httpx
from pydantic import ValidationError

from backend.app.local_agent.contracts import (
    NAUKRI_QUEUE_OPERATIONS,
    PROFILE_OPERATIONS,
    Command,
    Result,
)

MAX_MESSAGE_BYTES = 262144
HOST_NAME = "com.automated_apply.agent"
# These operations execute only local database transactions. Never infer a
# rollback from an HTTP status, timeout or disconnected native pipe.
ROLLBACK_RETRY_OPERATIONS = PROFILE_OPERATIONS | NAUKRI_QUEUE_OPERATIONS | {
    "get_application_task", "open_application_task", "update_application_task",
    "inspect_form", "prepare_form_answers",
}


def read_exact(stream, count):
    value = bytearray()
    while len(value) < count:
        # Chrome may keep a partial frame open. Bound each read, including pipe input.
        if hasattr(stream, "fileno"):
            try:
                if not select.select([stream], [], [], 10)[0]:
                    raise ValueError("native_read_timeout")
            except (OSError, TypeError):
                pass
        chunk = stream.read(count - len(value))
        if not chunk:
            raise ValueError("native_truncated_message")
        value.extend(chunk)
    return bytes(value)


def read_message(stream):
    length = struct.unpack("<I", read_exact(stream, 4))[0]
    if not 0 < length <= MAX_MESSAGE_BYTES:
        raise ValueError("native_message_size")
    # Keep transport timeout/truncation distinct from malformed JSON. Reading
    # inside the validation try block used to mask both as native_invalid_message.
    payload = read_exact(stream, length)
    try:
        return Command.model_validate_json(payload)
    except (ValidationError, UnicodeError, ValueError):
        raise ValueError("native_invalid_message") from None


def write_message(stream, value):
    payload = json.dumps(value, separators=(",", ":")).encode()
    if len(payload) > MAX_MESSAGE_BYTES:
        raise ValueError("native_response_size")
    stream.write(struct.pack("<I", len(payload)) + payload)
    stream.flush()


def forward(command, settings, client=None):
    if command.command not in PROFILE_OPERATIONS | NAUKRI_QUEUE_OPERATIONS | {"health", "connection_status", "get_agent_capabilities", "preview_application_url", "observe_platform_session", "inspect_form", "prepare_form_answers", "authorize_form", "record_form_fill", "open_application_task", "get_application_task", "update_application_task", "ask_form_questions"}:
        raise ValueError("native_capability_denied")
    token = settings.JOB_AGENT_API_TOKEN
    if not token or not settings.CHROME_NATIVE_MESSAGING_ENABLED or not settings.CHROME_EXTENSION_ID:
        raise ValueError("native_not_configured")
    headers = {"Authorization": "Bearer " + token.get_secret_value(), "X-Agent-Client": settings.CHROME_EXTENSION_ID}
    payload = command.model_dump(mode="json")
    # SecretStr stays redacted in logs/audit; unwrap only for the authenticated host transport.
    if command.profile_secret:
        payload["profile_secret"] = command.profile_secret.get_secret_value()
    try:
        with httpx.Client(timeout=40, follow_redirects=False, trust_env=False) if client is None else client as transport:
            deadline = time.monotonic() + 35
            for attempt in range(3):
                with transport.stream("POST", settings.LOCAL_AGENT_ENDPOINT + "/api/v1/local-agent/chrome",
                        json=payload, headers=headers, timeout=max(0.1, deadline - time.monotonic())) as response:
                    from uuid import UUID

                    from backend.app.core.logging import logger
                    backend_id = response.headers.get("X-Request-ID")
                    try:
                        backend_id = str(UUID(backend_id)) if backend_id else None
                    except ValueError:
                        backend_id = None
                    logger.info("native_backend_trace native_request_id=%s native_command_id=%s backend_request_id=%s attempt=%s",
                                command.request_id, command.chrome_command_id, backend_id, attempt + 1)
                    if response.status_code != 200:
                        rolled_back = (
                            response.status_code == 503
                            and response.headers.get("X-Automated-Apply-Transaction") == "rolled-back"
                            and command.command in ROLLBACK_RETRY_OPERATIONS
                        )
                        if rolled_back and attempt < 2 and time.monotonic() + 1 < deadline:
                            pass  # Close the error stream without retaining its body.
                        else:
                            raise ValueError(
                                "backend_authentication_failed" if response.status_code in {401, 403}
                                else "backend_transaction_rolled_back" if rolled_back
                                else "backend_not_ready"
                            )
                    else:
                        content = bytearray()
                        for chunk in response.iter_bytes():
                            content.extend(chunk)
                            if len(content) > MAX_MESSAGE_BYTES:
                                raise ValueError("native_response_size")
                        result = Result.model_validate_json(bytes(content))
                        if result.request_id != command.request_id:
                            raise ValueError("native_request_id_mismatch")
                        return result.model_dump(mode="json")
                time.sleep(0.2 * (attempt + 1))
    except httpx.TimeoutException:
        raise ValueError("backend_timeout") from None
    except httpx.TransportError:
        raise ValueError("backend_offline") from None
    except ValidationError:
        raise ValueError("backend_invalid_response") from None


def main():
    from backend.app.operations.configuration import load_settings
    command = None
    # Wrapper passes the private env path; Chrome supplies origin as the next argument.
    try:
        env_path, origin = sys.argv[1:3]
        path = Path(env_path)
        if not path.is_absolute() or path.is_symlink() or path.stat().st_mode & 0o077:
            raise ValueError("native_private_configuration_required")
        settings = load_settings(str(path))
        if origin != f"chrome-extension://{settings.CHROME_EXTENSION_ID}/":
            raise ValueError("native_origin_denied")
        # Use the unbuffered pipe: BufferedReader can prefetch the payload while
        # reading its header, making select() incorrectly time out on Chrome's
        # still-open stdin even though bytes remain in the Python buffer.
        command = read_message(sys.stdin.buffer.raw)
        output = forward(command, settings)
    except Exception as exc:
        # Only controlled fixed codes; never echo HTTP exception, config or message text.
        allowed = {
            "native_origin_denied", "native_message_size", "native_invalid_message", "native_truncated_message",
            "native_read_timeout", "native_capability_denied", "native_not_configured", "backend_offline",
            "backend_timeout", "backend_authentication_failed", "backend_not_ready", "backend_invalid_response",
            "backend_transaction_rolled_back",
            "native_response_size", "native_request_id_mismatch", "native_private_configuration_required",
        }
        code = str(exc) if isinstance(exc, ValueError) and str(exc) in allowed else "native_configuration_error"
        output = {"version": 1, "ok": False, "error_code": code}
        if command is not None:
            output["request_id"] = str(command.request_id)
    write_message(sys.stdout.buffer, output)


if __name__ == "__main__":
    main()
