"""Contract mode: API responses checked against OpenAPI (TASK-054).

In ``qa test --mode contract`` every response of a service that has a
contract (``environments[].contracts``) is checked against its OpenAPI
document: the operation must be documented, the status code and content type
must be documented for it, and a JSON body must match the schema.

- a response that breaks the contract is ``failed`` / ``application_bug``;
- a request the contract does not describe is ``error`` /
  ``requirement_ambiguity``: either the test or the contract is wrong.

Paths in the document are matched below the service URL (``servers`` is
ignored). OpenAPI 3.1 schemas are JSON Schema 2020-12; for 3.0, ``nullable``
is translated. Requests themselves are not validated.
"""

import copy
import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry
from referencing.jsonschema import DRAFT202012

from qa_execution.errors import RequirementAmbiguityError, StepFailure

METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
_URI = "urn:qa-platform:contract"


class ContractError(ValueError):
    """The OpenAPI document itself cannot be used."""


class ContractViolation(StepFailure):
    """The service answered differently than its contract says."""


class UndocumentedOperation(RequirementAmbiguityError):
    """A request the contract does not describe."""


@dataclass(frozen=True)
class _Operation:
    method: str
    template: str
    pattern: re.Pattern[str]
    pointer: str
    """JSON pointer of the operation in the document."""
    responses: Mapping[str, Any]


@dataclass(frozen=True)
class Contract:
    service: str
    base_url: str
    """The service URL the paths are relative to, without a trailing slash."""
    document: Mapping[str, Any]
    _operations: tuple[_Operation, ...] = field(default=(), repr=False)
    _registry: Registry[Any] = field(default_factory=Registry, repr=False)

    @classmethod
    def load(cls, service: str, base_url: str, document: Mapping[str, Any]) -> "Contract":
        version = str(document.get("openapi", ""))
        if not re.match(r"^3\.[01]\.\d+$", version):
            raise ContractError(f"openapi must be 3.0.x or 3.1.x, got {version or 'nothing'!r}")
        paths = document.get("paths")
        if not isinstance(paths, Mapping) or not paths:
            raise ContractError("the document has no paths")
        resolved = _from_openapi_30(document) if version.startswith("3.0") else document
        operations = []
        for template, item in paths.items():
            if not isinstance(item, Mapping):
                continue
            for method in METHODS:
                operation = item.get(method)
                if isinstance(operation, Mapping):
                    operations.append(
                        _Operation(
                            method=method.upper(),
                            template=str(template),
                            pattern=_path_pattern(str(template)),
                            pointer=f"/paths/{_escape(str(template))}/{method}",
                            responses=operation.get("responses") or {},
                        )
                    )
        # literal paths before templated ones: /orders/new before /orders/{id}
        operations.sort(key=lambda o: (o.template.count("{"), -len(o.template)))
        registry: Registry[Any] = Registry().with_resource(
            _URI, DRAFT202012.create_resource(resolved)
        )
        return cls(service, base_url.rstrip("/"), resolved, tuple(operations), registry)

    def handles(self, url: str) -> bool:
        return (
            url == self.base_url
            or url.startswith(self.base_url + "/")
            or url.startswith(self.base_url + "?")
        )

    def check(self, method: str, url: str, status: int, content_type: str, body: bytes) -> str:
        """Check one response; returns the operation (``GET /orders/{id}``) it matched."""
        path = urlsplit(url[len(self.base_url) :] or "/").path or "/"
        method = method.upper()
        operation = next(
            (o for o in self._operations if o.method == method and o.pattern.match(path)), None
        )
        if operation is None:
            raise UndocumentedOperation(
                f"contract {self.service!r} does not describe {method} {path}"
            )
        name = f"{operation.method} {operation.template}"
        key = next(
            (k for k in (str(status), f"{status // 100}XX", "default") if k in operation.responses),
            None,
        )
        if key is None:
            documented = ", ".join(str(k) for k in operation.responses) or "none"
            raise ContractViolation(
                f"{name}: status {status} is not in the contract (documented: {documented})"
            )
        response = operation.responses[key] or {}
        content = response.get("content") if isinstance(response, Mapping) else None
        if not content:
            return name  # nothing documented about the body
        media = content_type.split(";", 1)[0].strip().lower()
        media_key = _media_key(content, media)
        if media_key is None:
            raise ContractViolation(
                f"{name} ({status}): content type {media or 'none'!r} is not in the contract "
                f"(documented: {', '.join(content)})"
            )
        schema = (content[media_key] or {}).get("schema")
        if schema is None or not _is_json(media):
            return name
        try:
            data = json.loads(body)
        except ValueError:
            raise ContractViolation(f"{name} ({status}): the body is not valid JSON") from None
        pointer = (
            f"{operation.pointer}/responses/{_escape(key)}/content/{_escape(media_key)}/schema"
        )
        if error := _first_error(self._registry, pointer, data):
            raise ContractViolation(
                f"{name} ({status}): the body does not match the contract at "
                f"{_location(error)}: {error.message}"
            )
        return name


def _first_error(registry: Registry[Any], pointer: str, data: Any) -> ValidationError | None:
    validator = Draft202012Validator({"$ref": f"{_URI}#{pointer}"}, registry=registry)
    errors: Iterator[ValidationError] = validator.iter_errors(data)
    return min(errors, key=lambda e: (len(e.absolute_path), str(e.message)), default=None)


def _location(error: ValidationError) -> str:
    location = "$"
    for part in error.absolute_path:
        location += f"[{part}]" if isinstance(part, int) else f".{part}"
    return location


def _media_key(content: Mapping[str, Any], media: str) -> str | None:
    if media in content:
        return media
    family = media.split("/", 1)[0] + "/*"
    for key in (family, "*/*"):
        if key in content:
            return key
    return None


def _is_json(media: str) -> bool:
    return media == "application/json" or media.endswith("+json")


def _path_pattern(template: str) -> re.Pattern[str]:
    parts = re.split(r"(\{[^}/]+\})", template)
    regex = "".join("[^/]+" if p.startswith("{") else re.escape(p) for p in parts)
    return re.compile(f"^{regex}/?$")


def _escape(token: str) -> str:
    """JSON pointer escaping (RFC 6901)."""
    return token.replace("~", "~0").replace("/", "~1")


def _from_openapi_30(document: Mapping[str, Any]) -> dict[str, Any]:
    """OpenAPI 3.0 schemas as JSON Schema: ``nullable: true`` allows ``null``."""
    converted = copy.deepcopy(dict(document))

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.pop("nullable", False) is True:
                if "type" in node:
                    types = node["type"] if isinstance(node["type"], list) else [node["type"]]
                    node["type"] = [*types, "null"]
                elif "$ref" in node or "allOf" in node or "oneOf" in node or "anyOf" in node:
                    inner = {
                        k: node.pop(k)
                        for k in list(node)
                        if k in ("$ref", "allOf", "oneOf", "anyOf")
                    }
                    node["anyOf"] = [inner, {"type": "null"}]
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(converted)
    return converted


def find(contracts: Mapping[str, Contract], url: str) -> Contract | None:
    return next((c for c in contracts.values() if c.handles(url)), None)
