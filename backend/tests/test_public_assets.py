"""Pure policy/transport and supervised-worker boundaries; no public HTTP in tests."""

import asyncio
import base64
import io
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.app.browser import asset_worker, assets
from backend.app.browser.asset_policy import asset_origin, asset_target, policy
from backend.app.browser.runner import validate_destination
from backend.app.core.config import Settings


@pytest.mark.parametrize(
    "url",
    [
        "http://static.example",
        "https://user@static.example",
        "https://static.example/private",
        "https://static.example?key=private",
        "https://static.example?",
        "https://static.example#fragment",
        "https://static.example:0",
        "https://static.example./",
        "https://accounts.google.com",
        "https://jobs.linkedin.com",
        "https://cdn.naukri.com",
        "https://bad_host.example",
        "https://127.0.0.1",
        "https://169.254.169.254",
        "https://localhost",
    ],
)
def test_asset_origin_configuration_rejects_ambiguous_or_restricted_scopes(url):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, ENVIRONMENT="development", BROWSER_ASSET_ORIGINS=[url])


def test_policy_is_bounded_normalized_and_invalidates_approval_on_change():
    first = Settings(
        _env_file=None,
        BROWSER_ASSET_ORIGINS=["https://STATIC.example/", "https://static.example:443"],
    )
    assert first.BROWSER_ASSET_ORIGINS == ["https://static.example:443"]
    assert policy(first)["credentials"] is False
    assert (
        policy(first)["digest"]
        != policy(
            first.model_copy(
                update={"BROWSER_ASSET_ORIGINS": ["https://other.example:443"]}
            )
        )["digest"]
    )
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            BROWSER_ASSET_ORIGINS=[f"https://static{i}.example" for i in range(9)],
        )
    assert (
        asset_origin("http://127.0.0.1:8769", testing=True) == "http://127.0.0.1:8769"
    )


@pytest.mark.parametrize(
    "url,kind",
    [
        ("https://static.example/form.js?name=private", "script"),
        ("https://static.example/form.js", "fetch"),
        ("https://static.example/login.html", "script"),
        ("https://static.example/../form.js", "script"),
        ("https://static.example/%2e%2e/form.js", "script"),
        ("https://static.example/%0d%0aform.js", "script"),
        ("https://static.example/form%3fprivate.js", "script"),
        ("https://static.example//other/form.js", "script"),
        ("https://static.example/form.js#private", "script"),
    ],
)
def test_asset_urls_do_not_become_generic_api_or_data_transports(url, kind):
    with pytest.raises(ValueError):
        asset_target(url, kind)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "address", ["127.0.0.1", "10.0.0.2", "169.254.169.254", "::1", "::ffff:127.0.0.1"]
)
async def test_asset_dns_rejects_private_or_mixed_answers(monkeypatch, address):
    async def resolve(*args, **kwargs):
        return [
            (None, None, None, None, ("8.8.8.8", 443)),
            (None, None, None, None, (address, 443)),
        ]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    settings = Settings(
        _env_file=None, BROWSER_ASSET_ORIGINS=["https://static.example"]
    )
    with pytest.raises(Exception) as error:
        await validate_destination(
            "https://static.example",
            settings,
            allowed_origins=settings.BROWSER_ASSET_ORIGINS,
        )
    assert error.value.status_code == 403


def test_invalid_asset_configuration_does_not_print_credentials_in_validation_errors():
    private_value = "fictional-private-credential-for-validation"
    with pytest.raises(ValidationError) as error:
        Settings(
            _env_file=None,
            JOB_AGENT_API_TOKEN=private_value,
            BROWSER_ASSET_ORIGINS=["https://user:" + private_value + "@static.example"],
        )
    assert private_value not in str(error.value) and "input_value=" not in str(
        error.value
    )


class Response:
    def __init__(
        self, *, status=200, body=b"const publicAsset = true;", headers=None, extra=None
    ):
        self.status = status
        self.body = io.BytesIO(body)
        self.headers = {
            "Content-Type": "application/javascript; charset=utf-8",
            **(headers or {}),
        }
        self.extra = extra or []

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def getheaders(self):
        return [*self.headers.items(), *self.extra]

    def read(self, size):
        return self.body.read(size)


def invoke(monkeypatch, response):
    calls = []
    connection = SimpleNamespace(
        request=lambda *args, **kwargs: calls.append((args, kwargs)),
        getresponse=lambda: response,
        close=lambda: calls.append("closed"),
    )

    def connect(host, address, port, **kwargs):
        assert (host, address, port, kwargs) == (
            "static.example",
            "8.8.8.8",
            443,
            {"tls": True},
        )
        return connection

    monkeypatch.setattr(asset_worker, "connect_pinned", connect)
    return lambda: asset_worker.fetch(
        {
            "url": "https://static.example/form.js",
            "kind": "script",
            "address": "8.8.8.8",
            "origin": "https://employer.example:443",
        }
    ), calls


def test_worker_forwards_no_browser_credentials_and_preserves_cors_without_setting_cookies(
    monkeypatch,
):
    call, requests = invoke(
        monkeypatch,
        Response(
            headers={
                "Set-Cookie": "do-not-forward=fixture",
                "Access-Control-Allow-Origin": "https://employer.example",
                "Content-Security-Policy": "default-src 'none'",
            }
        ),
    )
    result = call()
    assert base64.b64decode(result["body"]) == b"const publicAsset = true;"
    assert result["headers"]["content-type"] == "application/javascript; charset=utf-8"
    assert (
        result["headers"]["access-control-allow-origin"] == "https://employer.example"
    )
    assert result["headers"]["content-security-policy"] == "default-src 'none'"
    assert "set-cookie" not in result["headers"]
    headers = requests[0][1]["headers"]
    assert set(headers) == {"User-Agent", "Accept-Encoding", "Origin"}
    assert headers["Origin"] == "https://employer.example" and requests[-1] == "closed"


@pytest.mark.parametrize(
    "response,error",
    [
        (
            Response(
                status=302, headers={"Location": "https://unapproved.example/form.js"}
            ),
            "asset_unavailable",
        ),
        (Response(status=401), "asset_unavailable"),
        (Response(status=403), "asset_unavailable"),
        (Response(status=429), "asset_unavailable"),
        (Response(headers={"Content-Type": "text/html"}), "unsupported_asset_type"),
        (Response(headers={"Content-Encoding": "gzip"}), "unsupported_asset_encoding"),
        (
            Response(headers={"Content-Length": str(4 * 1024 * 1024 + 1)}),
            "asset_too_large",
        ),
        (Response(headers={"Content-Length": "4000"}), "incomplete_asset"),
        (
            Response(
                headers={"Content-Security-Policy": "default-src 'self'"},
                extra=[("Content-Security-Policy", "default-src 'none'")],
            ),
            "unsupported_asset_headers",
        ),
        (
            Response(
                headers={"Access-Control-Allow-Origin": "*"},
                extra=[("Access-Control-Allow-Origin", "https://employer.example")],
            ),
            "unsupported_asset_headers",
        ),
    ],
)
def test_unsafe_or_failed_assets_close_the_connection_without_redirect_or_retry(
    monkeypatch, response, error
):
    call, requests = invoke(monkeypatch, response)
    with pytest.raises(asset_worker.AssetError, match=error):
        call()
    assert len(requests) == 2 and requests[-1] == "closed"


@pytest.mark.asyncio
async def test_late_worker_birth_is_stopped_without_sending_a_request_or_inheriting_secrets(
    monkeypatch,
):
    entered, release = asyncio.Event(), asyncio.Event()
    child = SimpleNamespace(returncode=None, killed=False, reaped=False)

    class Process:
        returncode = None

        async def communicate(self, payload):
            pytest.fail("A late worker must never receive a request after sealing")

        def kill(self):
            child.killed, self.returncode = True, -9

        async def wait(self):
            child.reaped = True

    process = Process()

    async def create(*args, **kwargs):
        assert kwargs["env"] == {"PATH": "/usr/bin:/bin"}
        assert args[0] == assets.sys.executable
        assert not any("https://" in str(arg) for arg in args)
        entered.set()
        await release.wait()
        return process

    monkeypatch.setattr(assets.asyncio, "create_subprocess_exec", create)
    relay = assets.PublicAssets({"https://static.example:443": ["8.8.8.8"]})
    task = asyncio.create_task(relay.fetch("https://static.example/form.js", "script"))
    await entered.wait()
    cleanup = asyncio.create_task(relay.close())
    await asyncio.sleep(0)
    release.set()
    with pytest.raises(assets.AssetUnavailable):
        await task
    await cleanup
    assert child.killed and child.reaped and not relay.inflight and not relay.processes


@pytest.mark.asyncio
async def test_request_and_byte_budgets_do_not_spawn_another_worker(monkeypatch):
    async def forbidden(*args, **kwargs):
        pytest.fail("No worker admission after a resource budget is exhausted")

    monkeypatch.setattr(assets.asyncio, "create_subprocess_exec", forbidden)
    relay = assets.PublicAssets({"https://static.example:443": ["8.8.8.8"]})
    relay.requests = assets.MAX_REQUESTS
    with pytest.raises(assets.AssetUnavailable):
        await relay.fetch("https://static.example/form.js", "script")
    relay.requests, relay.bytes = 0, assets.MAX_TOTAL_BYTES
    with pytest.raises(assets.AssetUnavailable):
        await relay.fetch("https://static.example/form.js", "script")


@pytest.mark.asyncio
async def test_worker_timeout_kills_and_reaps_without_a_late_response(monkeypatch):
    class Process:
        returncode = None
        killed = reaped = False

        async def communicate(self, payload):
            assert set(json.loads(payload)) == {
                "url",
                "kind",
                "address",
                "testing",
                "origin",
            }
            await asyncio.Event().wait()

        def kill(self):
            self.killed, self.returncode = True, -9

        async def wait(self):
            self.reaped = True

    child = Process()

    async def create(*args, **kwargs):
        return child

    monkeypatch.setattr(assets.asyncio, "create_subprocess_exec", create)
    monkeypatch.setattr(assets, "FETCH_TIMEOUT", 0.01)
    relay = assets.PublicAssets({"https://static.example:443": ["8.8.8.8"]})
    with pytest.raises(assets.AssetUnavailable):
        await relay.fetch("https://static.example/form.js", "script")
    assert child.killed and child.reaped and not relay.inflight
