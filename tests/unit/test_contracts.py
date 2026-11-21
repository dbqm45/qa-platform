"""Checking responses against an OpenAPI contract (TASK-054)."""

import copy
import json
from typing import Any

import pytest

from qa_execution.contracts import (
    Contract,
    ContractError,
    ContractViolation,
    UndocumentedOperation,
)
from qa_execution.errors import classify

ORDER = {
    "type": "object",
    "required": ["id", "product", "quantity"],
    "properties": {
        "id": {"type": "integer"},
        "product": {"type": "string", "enum": ["apple", "pear", "plum"]},
        "quantity": {"type": "integer", "minimum": 1},
        "note": {"type": "string", "nullable": True},
    },
}


def _document(version: str = "3.0.3") -> dict[str, Any]:
    return {
        "openapi": version,
        "info": {"title": "Shop", "version": "1"},
        "paths": {
            "/orders": {
                "get": {"responses": {"200": {"content": {"application/json": {"schema": {
                    "type": "array", "items": {"$ref": "#/components/schemas/Order"}}}}}}},
                "post": {"responses": {
                    "201": {"content": {"application/json": {"schema": {
                        "$ref": "#/components/schemas/Order"}}}},
                    "4XX": {"description": "invalid"},
                }},
            },
            "/orders/new": {"get": {"responses": {"200": {"description": "form"}}}},
            "/orders/{id}": {"get": {"responses": {
                "200": {"content": {"application/json": {"schema": {
                    "$ref": "#/components/schemas/Order"}}}},
                "default": {"content": {"text/*": {}}},
            }}},
        },
        "components": {"schemas": {"Order": copy.deepcopy(ORDER)}},
    }  # fmt: skip


@pytest.fixture
def contract() -> Contract:
    return Contract.load("api", "http://shop/api/", _document())


def _check(contract: Contract, method: str, path: str, status: int, body: Any = None,
           content_type: str = "application/json") -> str:  # fmt: skip
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    return contract.check(method, f"http://shop/api{path}", status, content_type, raw)


GOOD = {"id": 1, "product": "pear", "quantity": 4, "note": None}


def test_matching_responses(contract: Contract) -> None:
    assert _check(contract, "GET", "/orders?page=2", 200, [GOOD]) == "GET /orders"
    assert _check(contract, "post", "/orders", 201, GOOD) == "POST /orders"
    assert _check(contract, "POST", "/orders", 422, {"errors": []}) == "POST /orders"  # 4XX
    assert _check(contract, "GET", "/orders/7", 200, GOOD) == "GET /orders/{id}"
    assert _check(contract, "GET", "/orders/new", 200, b"<form>", "text/html") == (
        "GET /orders/new"  # literal path wins over the template
    )
    assert _check(contract, "GET", "/orders/7", 404, b"gone", "text/plain") == "GET /orders/{id}"


@pytest.mark.parametrize(
    ("method", "path", "status", "body", "content_type", "message"),
    [
        ("GET", "/orders", 500, [], "application/json",
         "GET /orders: status 500 is not in the contract (documented: 200)"),
        ("GET", "/orders", 200, [{**GOOD, "quantity": 0}], "application/json",
         "GET /orders (200): the body does not match the contract at $[0].quantity: "
         "0 is less than the minimum of 1"),
        ("POST", "/orders", 201, {"id": 1, "product": "kiwi", "quantity": 1}, "application/json",
         "at $.product: 'kiwi' is not one of ['apple', 'pear', 'plum']"),
        ("POST", "/orders", 201, {"product": "pear", "quantity": 1}, "application/json",
         "at $: 'id' is a required property"),
        ("GET", "/orders/1", 200, GOOD, "text/html",
         "content type 'text/html' is not in the contract (documented: application/json)"),
        ("GET", "/orders/1", 200, b"{not json", "application/json", "the body is not valid JSON"),
    ],
)  # fmt: skip
def test_violations(
    contract: Contract, method: str, path: str, status: int, body: Any, content_type: str,
    message: str,
) -> None:  # fmt: skip
    with pytest.raises(ContractViolation) as info:
        _check(contract, method, path, status, body, content_type)
    assert message in str(info.value)
    assert classify(info.value)[1].value == "application_bug"
    assert classify(info.value)[0].value == "failed"


def test_undocumented_operation_is_requirement_ambiguity(contract: Contract) -> None:
    with pytest.raises(UndocumentedOperation, match="does not describe DELETE /orders/1") as info:
        _check(contract, "DELETE", "/orders/1", 204, b"")
    assert classify(info.value)[1].value == "requirement_ambiguity"


def test_openapi_30_nullable_and_31_null_types() -> None:
    v30 = Contract.load("api", "http://shop/api", _document("3.0.3"))
    _check(v30, "GET", "/orders/1", 200, GOOD)  # note: null allowed by nullable

    doc31 = _document("3.1.0")
    del doc31["components"]["schemas"]["Order"]["properties"]["note"]["nullable"]
    doc31["components"]["schemas"]["Order"]["properties"]["note"]["type"] = ["string", "null"]
    _check(Contract.load("api", "http://shop/api", doc31), "GET", "/orders/1", 200, GOOD)

    strict = _document("3.1.0")  # in 3.1 nullable means nothing: null is rejected
    with pytest.raises(ContractViolation, match=r"\$\.note: None is not of type 'string'"):
        _check(Contract.load("api", "http://shop/api", strict), "GET", "/orders/1", 200, GOOD)


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ({"swagger": "2.0", "paths": {"/a": {}}}, "openapi must be 3.0.x or 3.1.x"),
        ({"openapi": "3.1.0"}, "the document has no paths"),
    ],
)
def test_unusable_documents(document: dict[str, Any], message: str) -> None:
    with pytest.raises(ContractError, match=message):
        Contract.load("api", "http://shop", document)


def test_which_urls_a_contract_covers(contract: Contract) -> None:
    assert contract.handles("http://shop/api/orders")
    assert not contract.handles("http://shop/apiv2/orders")
