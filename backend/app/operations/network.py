"""Script-scoped network accounting. Offline mode denies every real HTTP transport."""

from urllib.parse import urlsplit

import httpx

PUBLIC_HOSTS = {
    "hn.algolia.com",
    "www.arbeitnow.com",
    "remotive.com",
    "boards-api.greenhouse.io",
}


class NetworkAudit:
    def __init__(self, allowed_hosts=()):
        self.allowed_hosts = set(allowed_hosts)
        self.attempted = 0
        self.responses = 0
        self.sources = set()

    def __enter__(self):
        self.original = httpx.AsyncHTTPTransport.handle_async_request
        self.sync_original = httpx.HTTPTransport.handle_request
        audit = self

        async def request(transport, request):
            host = urlsplit(str(request.url)).hostname
            if host not in audit.allowed_hosts or (host in PUBLIC_HOSTS and request.method != "GET"):
                raise RuntimeError("external_http_forbidden_by_operation_mode")
            audit.attempted += 1
            audit.sources.add(host)
            response = await audit.original(transport, request)
            audit.responses += 1
            return response

        def sync_request(*args, **kwargs):
            raise RuntimeError("synchronous_http_forbidden_by_operation_mode")

        httpx.AsyncHTTPTransport.handle_async_request = request
        httpx.HTTPTransport.handle_request = sync_request
        return self

    def __exit__(self, *args):
        httpx.AsyncHTTPTransport.handle_async_request = self.original
        httpx.HTTPTransport.handle_request = self.sync_original

    def output(self):
        return dict(
            actual_external_calls=self.attempted > 0,
            http_requests_attempted=self.attempted,
            http_responses_received=self.responses,
            contacted_hosts=sorted(self.sources),
        )
