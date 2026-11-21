"""Mocked service responses (TASK-051).

A mock file describes the responses of one service, e.g. ``mocks/api.yaml``::

    version: 1
    responses:
      - request: GET /orders
        json: [{"product": "apple", "quantity": 3}]
      - request: POST /orders
        status: 201
        json: {"id": 1, "product": "pear"}
      - request: GET /health
        body: ok
        headers: {Content-Type: text/plain}
"""

from typing import Annotated, Any, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from qa_schemas.base import SchemaModel, find_duplicates

MOCK_SCHEMA_VERSION: Literal[1] = 1

MockRequest = Annotated[
    str, StringConstraints(pattern=r"^(GET|HEAD|OPTIONS|POST|PUT|PATCH|DELETE) /\S*$")
]
"""``METHOD /path``, relative to the service's URL; the query string is ignored."""


class MockResponse(SchemaModel):
    request: MockRequest
    status: Annotated[int, Field(ge=100, le=599)] = 200
    headers: dict[str, str] = Field(default_factory=dict)
    json_body: Any = Field(default=None, alias="json")
    """Response body as JSON (sets ``Content-Type: application/json``)."""
    body: str | None = None
    """Response body as text."""

    @model_validator(mode="after")
    def _one_body(self) -> Self:
        if self.json_body is not None and self.body is not None:
            raise ValueError("give either json or body, not both")
        return self

    @property
    def method(self) -> str:
        return self.request.split(" ", 1)[0]

    @property
    def path(self) -> str:
        return self.request.split(" ", 1)[1]


class MockDefinition(SchemaModel):
    version: Literal[1] = MOCK_SCHEMA_VERSION
    responses: Annotated[tuple[MockResponse, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def _unique_requests(self) -> Self:
        if duplicates := find_duplicates(r.request for r in self.responses):
            raise ValueError(f"duplicate requests: {duplicates}")
        return self
