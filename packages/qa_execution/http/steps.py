"""API request and assertion steps (TASK-046, TASK-047).

Requests (precondition / action):

| Step                                              | Action               |
|---------------------------------------------------|----------------------|
| the client sends {word} {string}                  | ``api.send``         |
| the client sends {word} {string} with:  + JSON    | ``api.send-json``    |
| the client sets header {string} to {string}       | ``api.header``       |
| the client uses the token from {string}           | ``api.token-from``   |
| the client uses bearer token {string}             | ``api.bearer``       |

Assertions (expectation) on the last response:

| Step                                              | Action                  |
|---------------------------------------------------|-------------------------|
| the response status is {int}                      | ``api.status``          |
| the response header {string} is {string}          | ``api.header-is``       |
| the response header {string} contains {string}    | ``api.header-contains`` |
| the response field {string} is {string}           | ``api.field-is``        |
| the response field {string} exists                | ``api.field-exists``    |
| the response field {string} has {int} items       | ``api.field-count``     |
| the response body contains {string}               | ``api.body-contains``   |

Field paths: ``name``, ``order.total``, ``orders[0].product``, ``[1].id``.
Expected field values are read as JSON when possible (``4``, ``true``,
``null``, ``"4"``), otherwise as text (``pear``).
"""

import json
import re
from typing import Annotated, Any, Literal

import httpx
from pydantic import AfterValidator, Field

from qa_core.steps.registry import StepHandler, StepRegistry
from qa_execution.errors import ClassifiedError, StepFailure, TestDataError
from qa_execution.http.adapter import HttpSession
from qa_execution.runner import StepContext
from qa_execution.values import Url
from qa_schemas.enums import StepKind
from qa_schemas.project import SENSITIVE_HEADERS

CAPABILITY = "http"
_BODY_PREVIEW = 300
_PATH_TOKEN = re.compile(r"\[(\d+)\]|([^.\[\]]+)")
_HEADER_NAME = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]+$")

Method = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]


class NoResponseError(ClassifiedError):
    """An assertion ran before any request: the scenario is incomplete."""


def parse_path(path: str) -> list[str | int]:
    """``orders[0].product`` -> ``["orders", 0, "product"]``; raises ValueError if malformed."""
    tokens: list[str | int] = []
    position = 0
    for match in _PATH_TOKEN.finditer(path):
        gap = path[position : match.start()]
        if gap not in ("", ".") or (gap == "." and not tokens):
            raise ValueError(f"invalid field path {path!r}")
        index, name = match.groups()
        tokens.append(int(index) if index is not None else name)
        position = match.end()
    if not tokens or position != len(path):
        raise ValueError(f"invalid field path {path!r}")
    return tokens


def _check_path(value: str) -> str:
    parse_path(value)
    return value


def _check_json(value: str) -> str:
    try:
        json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"request body is not valid JSON: {exc.msg} (line {exc.lineno})") from None
    return value


def _check_header(value: str) -> str:
    if not _HEADER_NAME.match(value):
        raise ValueError(f"invalid header name {value!r}")
    return value


FieldPath = Annotated[str, AfterValidator(_check_path)]
JsonBody = Annotated[str, AfterValidator(_check_json)]
HeaderName = Annotated[str, AfterValidator(_check_header)]


# --- Requests ----------------------------------------------------------------


def send(context: StepContext, method: Method, url: Url) -> None:
    _session(context).send(method, url)


def send_json(context: StepContext, method: Method, url: Url, *, doc_string: JsonBody) -> None:
    try:
        body = json.loads(doc_string)  # secrets are resolved by now; re-check
    except json.JSONDecodeError as exc:
        raise TestDataError(
            f"request body is not valid JSON after resolving secrets: {exc.msg}"
        ) from None
    _session(context).send(method, url, json_body=body)


def set_header(context: StepContext, name: HeaderName, value: str) -> None:
    if name.lower() in SENSITIVE_HEADERS:
        context.mark_secret(value)
    _session(context).headers[name] = value


def use_token_from(context: StepContext, path: FieldPath) -> None:
    session = _session(context)
    found, value = lookup(_json(session), parse_path(path))
    if not found or not isinstance(value, str) or not value:
        raise StepFailure(f"response field {path!r} is not a non-empty string{_summary(session)}")
    context.mark_secret(value)
    session.headers["Authorization"] = f"Bearer {value}"


def use_bearer(context: StepContext, token: str) -> None:
    context.mark_secret(token)
    _session(context).headers["Authorization"] = f"Bearer {token}"


# --- Assertions --------------------------------------------------------------


def status_is(context: StepContext, code: Annotated[int, Field(ge=100, le=599)]) -> None:
    session = _session(context)
    response = _response(session)
    if response.status_code != code:
        raise StepFailure(f"expected status {code}{_summary(session)}")


def header_is(context: StepContext, name: HeaderName, value: str) -> None:
    session = _session(context)
    actual = _response(session).headers.get(name)
    if actual != value:
        raise StepFailure(f"header {name!r} is {actual!r}, expected {value!r}{_summary(session)}")


def header_contains(context: StepContext, name: HeaderName, part: str) -> None:
    session = _session(context)
    actual = _response(session).headers.get(name)
    if actual is None or part not in actual:
        raise StepFailure(f"header {name!r} is {actual!r}, expected it to contain {part!r}")


def field_is(context: StepContext, path: FieldPath, expected: str) -> None:
    session = _session(context)
    found, actual = lookup(_json(session), parse_path(path))
    wanted = _expected(expected)
    if not found:
        raise StepFailure(f"response field {path!r} does not exist{_summary(session)}")
    if actual != wanted or type(actual) is not type(wanted):
        raise StepFailure(
            f"response field {path!r} is {json.dumps(actual)}, expected {json.dumps(wanted)}"
        )


def field_exists(context: StepContext, path: FieldPath) -> None:
    session = _session(context)
    found, _ = lookup(_json(session), parse_path(path))
    if not found:
        raise StepFailure(f"response field {path!r} does not exist{_summary(session)}")


def field_has_items(
    context: StepContext, path: FieldPath, count: Annotated[int, Field(ge=0)]
) -> None:
    session = _session(context)
    found, actual = lookup(_json(session), parse_path(path))
    if not found:
        raise StepFailure(f"response field {path!r} does not exist{_summary(session)}")
    if not isinstance(actual, list | dict):
        raise StepFailure(f"response field {path!r} is {json.dumps(actual)}, not a list")
    if len(actual) != count:
        raise StepFailure(f"response field {path!r} has {len(actual)} items, expected {count}")


def body_contains(context: StepContext, text: str) -> None:
    session = _session(context)
    if text not in _response(session).text:
        raise StepFailure(f"response body does not contain {text!r}{_summary(session)}")


# --- Registration ------------------------------------------------------------


def register_api_steps(registry: StepRegistry) -> None:
    a, e = StepKind.ACTION, StepKind.EXPECTATION
    definitions: list[tuple[str, str, StepHandler, StepKind]] = [
        ("api.send", "the client sends {word} {string}", send, a),
        ("api.send-json", "the client sends {word} {string} with:", send_json, a),
        ("api.header", "the client sets header {string} to {string}", set_header, a),
        ("api.token-from", "the client uses the token from {string}", use_token_from, a),
        ("api.bearer", "the client uses bearer token {string}", use_bearer, a),
        ("api.status", "the response status is {int}", status_is, e),
        ("api.header-is", "the response header {string} is {string}", header_is, e),
        (
            "api.header-contains",
            "the response header {string} contains {string}",
            header_contains,
            e,
        ),
        ("api.field-is", "the response field {string} is {string}", field_is, e),
        ("api.field-exists", "the response field {string} exists", field_exists, e),
        ("api.field-count", "the response field {string} has {int} items", field_has_items, e),
        ("api.body-contains", "the response body contains {string}", body_contains, e),
    ]
    for step_id, pattern, handler, kind in definitions:
        registry.register(step_id, pattern, handler, kind=kind, capability=CAPABILITY)


# --- Internals ---------------------------------------------------------------


def lookup(data: Any, path: list[str | int]) -> tuple[bool, Any]:
    """Follow ``path`` into JSON data; ``(False, None)`` if any part is missing."""
    current = data
    for token in path:
        if isinstance(token, int):
            if not isinstance(current, list) or token >= len(current):
                return False, None
        elif not isinstance(current, dict) or token not in current:
            return False, None
        current = current[token]
    return True, current


def _session(context: StepContext) -> HttpSession:
    session: HttpSession = context.resource(CAPABILITY)
    return session


def _response(session: HttpSession) -> httpx.Response:
    if session.last_response is None:
        raise NoResponseError("no request has been sent in this test case yet")
    return session.last_response


def _json(session: HttpSession) -> Any:
    response = _response(session)
    try:
        return response.json()
    except ValueError:
        raise StepFailure(f"response is not JSON{_summary(session)}") from None


def _expected(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _summary(session: HttpSession) -> str:
    response = session.last_response
    if response is None:
        return ""
    body = response.text.strip().replace("\n", " ")
    if len(body) > _BODY_PREVIEW:
        body = body[:_BODY_PREVIEW] + "..."
    request = response.request
    return f" (got {response.status_code} from {request.method} {request.url}: {body})"
