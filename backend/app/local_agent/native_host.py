"""Chrome length-prefixed stdin protocol. stdout contains protocol frames only."""
import json
import select
import struct
import sys
from pathlib import Path

import httpx
from pydantic import ValidationError

from backend.app.local_agent.contracts import Command, Result

MAX_MESSAGE_BYTES = 16384
HOST_NAME = "com.automated_apply.agent"


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
    if command.command not in {"health", "connection_status", "get_agent_capabilities", "preview_application_url", "observe_platform_session"}:
        raise ValueError("native_capability_denied")
    token = settings.JOB_AGENT_API_TOKEN
    if not token or not settings.CHROME_NATIVE_MESSAGING_ENABLED or not settings.CHROME_EXTENSION_ID:
        raise ValueError("native_not_configured")
    headers = {"Authorization": "Bearer " + token.get_secret_value(), "X-Agent-Client": settings.CHROME_EXTENSION_ID}
    try:
        with httpx.Client(timeout=40, follow_redirects=False, trust_env=False) if client is None else client as transport:
            with transport.stream("POST", settings.LOCAL_AGENT_ENDPOINT + "/api/v1/local-agent/chrome",
                    json=command.model_dump(mode="json"), headers=headers) as response:
                if response.status_code != 200:
                    raise ValueError("backend_authentication_failed" if response.status_code in {401, 403} else "backend_not_ready")
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > MAX_MESSAGE_BYTES:
                        raise ValueError("native_response_size")
                result = Result.model_validate_json(bytes(content))
                if result.request_id != command.request_id:
                    raise ValueError("native_request_id_mismatch")
                return result.model_dump(mode="json")
    except httpx.TimeoutException:
        raise ValueError("backend_timeout") from None
    except httpx.TransportError:
        raise ValueError("backend_offline") from None
    except ValidationError:
        raise ValueError("backend_invalid_response") from None


def main():
    from backend.app.operations.configuration import load_settings
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
            "native_response_size", "native_request_id_mismatch", "native_private_configuration_required",
        }
        code = str(exc) if isinstance(exc, ValueError) and str(exc) in allowed else "native_configuration_error"
        output = {"version": 1, "ok": False, "error_code": code}
    write_message(sys.stdout.buffer, output)


if __name__ == "__main__":
    main()
