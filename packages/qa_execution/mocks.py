"""Mocked services (TASK-051).

A mocked service is answered in-process by the adapters, from its mock file,
instead of over the network: the HTTP adapter through an ``httpx`` transport,
the browser by intercepting the page's requests. Requests to other URLs go
out unchanged. A request to the mocked service that the file does not
describe is a ``dependency_error``, never a made-up response.

Only requests the test or the browser sends can be mocked: calls the
application under test makes from its own servers are out of reach.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from qa_execution.errors import DependencyError, RootCause
from qa_schemas.mock import MockDefinition, MockResponse

MOCK_HEADER = "x-qa-mock"
"""Added to every mocked response, so evidence shows which responses were mocked."""


class MockMissError(DependencyError, RootCause):
    """A request to a mocked service that its mock file does not describe."""


@dataclass(frozen=True)
class MockService:
    name: str
    base_url: str
    """The real service URL that is replaced, without a trailing slash."""
    definition: MockDefinition

    def handles(self, url: str) -> bool:
        return (
            url == self.base_url
            or url.startswith(self.base_url + "/")
            or (url.startswith(self.base_url + "?"))
        )

    def answer(self, method: str, url: str) -> MockResponse:
        """The response for a request this service ``handles``."""
        path = urlsplit(url[len(self.base_url) :] or "/").path or "/"
        if not path.startswith("/"):
            path = "/" + path
        method = method.upper()
        for response in self.definition.responses:
            if response.method == method and response.path == path:
                return response
        known = ", ".join(r.request for r in self.definition.responses[:5])
        raise MockMissError(
            f"mock {self.name!r} has no response for {method} {path} (it knows: {known}"
            f"{', ...' if len(self.definition.responses) > 5 else ''})"
        )


def encode(service: MockService, response: MockResponse) -> tuple[int, dict[str, str], bytes]:
    """Status, headers and body bytes of a mocked response."""
    headers = {name.lower(): value for name, value in response.headers.items()}
    if response.json_body is not None:
        body = json.dumps(response.json_body).encode()
        headers.setdefault("content-type", "application/json")
    else:
        body = (response.body or "").encode()
        if response.body is not None:
            headers.setdefault("content-type", "text/plain; charset=utf-8")
    headers[MOCK_HEADER] = service.name
    headers.setdefault("access-control-allow-origin", "*")  # pages on another origin
    return response.status, headers, body


PREFLIGHT_HEADERS = {
    "access-control-allow-origin": "*",
    "access-control-allow-methods": "GET, HEAD, POST, PUT, PATCH, DELETE, OPTIONS",
    "access-control-allow-headers": "*",
}
"""Answer to a browser's CORS preflight that the mock file does not describe."""


def find(mocks: Mapping[str, MockService], url: str) -> MockService | None:
    return next((m for m in mocks.values() if m.handles(url)), None)


class MockingTransport(httpx.BaseTransport):
    """Answers requests for mocked services; sends everything else with ``real``."""

    def __init__(self, mocks: Mapping[str, MockService], real: httpx.BaseTransport) -> None:
        self._mocks = mocks
        self._real = real

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        service = find(self._mocks, url)
        if service is None:
            return self._real.handle_request(request)
        status, headers, body = encode(service, service.answer(request.method, url))
        return httpx.Response(status, headers=headers, content=body, request=request)

    def close(self) -> None:
        self._real.close()
