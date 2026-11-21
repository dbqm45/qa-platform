"""API step helpers and the HTTPX adapter (TASK-045..048); no network needed."""

from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from qa_execution.adapters import AdapterNotPreparedError, ExecutionContext
from qa_execution.http.adapter import HttpxAdapter, mask_headers
from qa_execution.http.config import HttpConfig
from qa_execution.http.steps import lookup, parse_path
from qa_schemas.plan import ExecutionSettings
from qa_schemas.project import Environment
from qa_schemas.specification import TestSpecification

ROOT = Path(__file__).parents[2]


@pytest.mark.parametrize(
    ("path", "tokens"),
    [
        ("status", ["status"]),
        ("order.total", ["order", "total"]),
        ("orders[0].product", ["orders", 0, "product"]),
        ("[1].id", [1, "id"]),
        ("matrix[0][2]", ["matrix", 0, 2]),
        ("errors[0]", ["errors", 0]),
    ],
)
def test_parse_path(path: str, tokens: list[str | int]) -> None:
    assert parse_path(path) == tokens


@pytest.mark.parametrize("path", ["", ".a", "a.", "a..b", "a[x]", "a[0", "a]0["])
def test_invalid_paths(path: str) -> None:
    with pytest.raises(ValueError, match="invalid field path"):
        parse_path(path)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("orders[1].product", (True, "plum")),
        ("orders[2]", (False, None)),
        ("orders[0].missing", (False, None)),
        ("count", (True, 0)),
        ("note", (True, None)),
        ("count.x", (False, None)),
    ],
)
def test_lookup(path: str, expected: tuple[bool, Any]) -> None:
    data = {"orders": [{"product": "pear"}, {"product": "plum"}], "count": 0, "note": None}
    assert lookup(data, parse_path(path)) == expected


def test_sensitive_headers_are_masked() -> None:
    headers = httpx.Headers(
        {
            "Authorization": "Bearer x",
            "Cookie": "s=1",
            "X-Api-Key": "k",
            "Accept": "application/json",
        }
    )
    assert mask_headers(headers) == {
        "authorization": "********",
        "cookie": "********",
        "x-api-key": "********",
        "accept": "application/json",
    }


def test_http_config() -> None:
    assert HttpConfig().service == "api"
    with pytest.raises(ValidationError):
        HttpConfig.model_validate({"service": "Not Valid"})
    with pytest.raises(ValidationError):
        HttpConfig.model_validate({"timeout": 5})


def _context(tmp_path: Path, **environment: Any) -> ExecutionContext:
    return ExecutionContext(
        execution_id="e",
        environment=Environment(name="local", **environment),
        settings=ExecutionSettings(step_timeout_seconds=7),
        evidence_dir=tmp_path,
    )


def _case() -> Any:
    spec = TestSpecification.model_validate_json(
        (ROOT / "tests/fixtures/login/login.spec.json").read_text()
    )
    return spec.test_cases[0]


def test_base_url_prefers_the_service(tmp_path: Path) -> None:
    adapter = HttpxAdapter()
    adapter.prepare(
        _context(tmp_path, base_url="http://web.local", services={"api": "http://api.local/v1/"})
    )
    adapter.start_test_case(_case())
    session = adapter.resource
    assert session.base_url == "http://api.local/v1"
    assert session.client.timeout.read == 7
    adapter.cleanup()


def test_base_url_falls_back_to_the_environment(tmp_path: Path) -> None:
    adapter = HttpxAdapter()
    adapter.prepare(_context(tmp_path, base_url="http://web.local"))
    adapter.start_test_case(_case())
    assert adapter.resource.base_url == "http://web.local"
    adapter.cleanup()


def test_each_test_case_gets_a_fresh_client(tmp_path: Path) -> None:
    adapter = HttpxAdapter()
    adapter.prepare(_context(tmp_path))
    adapter.start_test_case(_case())
    first = adapter.resource
    first.headers["Authorization"] = "Bearer abc"
    assert adapter.collect_evidence(_case()) == []  # no requests, no file

    adapter.start_test_case(_case())
    second = adapter.resource
    assert second is not first
    assert second.headers == {}
    assert first.client.is_closed
    adapter.cleanup()
    with pytest.raises(AdapterNotPreparedError):
        _ = adapter.resource
