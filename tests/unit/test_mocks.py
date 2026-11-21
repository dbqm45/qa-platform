"""Matching requests against a mock file (TASK-051)."""

import httpx
import pytest
from pydantic import ValidationError

from qa_execution.mocks import MockingTransport, MockMissError, MockService
from qa_schemas.mock import MockDefinition

DEFINITION = MockDefinition.model_validate(
    {"responses": [
        {"request": "GET /orders", "json": [1]},
        {"request": "GET /", "body": "root"},
        {"request": "DELETE /orders/1", "status": 204},
    ]}
)  # fmt: skip
API = MockService(name="api", base_url="http://shop/api", definition=DEFINITION)


@pytest.mark.parametrize(
    ("url", "handled"),
    [
        ("http://shop/api", True),
        ("http://shop/api/orders", True),
        ("http://shop/api?x=1", True),
        ("http://shop/apiv2/orders", False),  # a prefix of the path is not enough
        ("http://shop/other", False),
        ("https://shop/api/orders", False),
    ],
)
def test_which_urls_a_mock_handles(url: str, handled: bool) -> None:
    assert API.handles(url) is handled


@pytest.mark.parametrize(
    ("method", "url", "expected"),
    [
        ("GET", "http://shop/api/orders?page=2", "GET /orders"),  # query ignored
        ("get", "http://shop/api/orders", "GET /orders"),
        ("GET", "http://shop/api", "GET /"),
        ("DELETE", "http://shop/api/orders/1", "DELETE /orders/1"),
    ],
)
def test_matching_response(method: str, url: str, expected: str) -> None:
    assert API.answer(method, url).request == expected


def test_unknown_request_names_what_the_mock_knows() -> None:
    with pytest.raises(MockMissError, match=r"no response for POST /orders \(it knows: GET"):
        API.answer("POST", "http://shop/api/orders")


def test_transport_answers_mocks_and_passes_the_rest_through() -> None:
    real = httpx.MockTransport(lambda request: httpx.Response(200, text="real"))
    with httpx.Client(transport=MockingTransport({"api": API}, real)) as client:
        mocked = client.get("http://shop/api/orders")
        other = client.get("http://shop/elsewhere")
        empty = client.delete("http://shop/api/orders/1")
    assert (mocked.json(), mocked.headers["x-qa-mock"]) == ([1], "api")
    assert mocked.headers["content-type"] == "application/json"
    assert other.text == "real" and "x-qa-mock" not in other.headers
    assert (empty.status_code, empty.content) == (204, b"")


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"responses": []}, "at least 1 item"),
        ({"responses": [{"request": "GET orders"}]}, "request"),
        ({"responses": [{"request": "GET /a", "json": 1, "body": "x"}]}, "either json or body"),
        ({"responses": [{"request": "GET /a"}, {"request": "GET /a"}]}, "duplicate requests"),
        ({"version": 2, "responses": [{"request": "GET /a"}]}, "version"),
        ({"responses": [{"request": "GET /a", "delay": 1}]}, "Extra inputs"),
    ],
)
def test_invalid_mock_files(data: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        MockDefinition.model_validate(data)
