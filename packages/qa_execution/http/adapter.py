"""HTTPX adapter: provides the ``http`` capability (TASK-045, TASK-048).

A fresh client per test case (no shared cookies, tokens or headers). Every
request/response exchange is recorded and written per test case to
``<evidence dir>/<test case id>/http.json`` with sensitive headers masked and
the whole file passed through the execution's redactor.
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

import httpx
from pydantic import ValidationError

from qa_core.redaction import MASK, MissingSecretError, Redactor
from qa_execution.adapters import (
    AdapterNotPreparedError,
    ExecutionContext,
    TestAdapter,
    evidence_folder,
)
from qa_execution.errors import TestEnvironmentError
from qa_execution.http.config import HttpConfig
from qa_execution.protection import ALLOW_HINT, SAFE_METHODS, ProtectedEnvironmentError
from qa_schemas.evidence import EvidenceReference
from qa_schemas.project import SENSITIVE_HEADERS
from qa_schemas.specification import TestCase


@dataclass
class HttpSession:
    """The ``http`` resource handed to step implementations."""

    client: httpx.Client
    config: HttpConfig
    redactor: Redactor
    base_url: str | None
    headers: dict[str, str] = field(default_factory=dict)
    """Extra headers sent with every following request of this test case."""
    last_response: httpx.Response | None = None
    exchanges: list[dict[str, Any]] = field(default_factory=list)
    read_only: bool = False
    """The environment is protected: write methods are refused (TASK-056)."""
    environment: str = ""

    def send(
        self, method: str, url: str, *, json_body: Any = None, raw_body: str | None = None
    ) -> httpx.Response:
        if self.read_only and method.upper() not in SAFE_METHODS:
            raise ProtectedEnvironmentError(
                f"{method.upper()} {url} was not sent: environment {self.environment!r} "
                f"is protected (read-only); {ALLOW_HINT}"
            )
        if url.startswith("/") and self.base_url is None:
            raise TestEnvironmentError(
                f"cannot send {method} {url}: the environment has neither a "
                f"{self.config.service!r} service nor a base_url"
            )
        started = time.perf_counter()
        try:
            response = self.client.request(
                method,
                url,
                headers=self.headers,
                content=raw_body.encode() if raw_body is not None else None,
                json=json_body if raw_body is None else None,
            )
        except httpx.TimeoutException:
            raise TestEnvironmentError(f"{method} {url} timed out") from None
        except httpx.TransportError as exc:
            raise TestEnvironmentError(f"cannot send {method} {url}: {exc}") from None
        self.last_response = response
        self._record(response, round((time.perf_counter() - started) * 1000))
        return response

    def _record(self, response: httpx.Response, duration_ms: int) -> None:
        request = response.request
        limit = self.config.max_body_bytes
        self.exchanges.append(
            {
                "request": {
                    "method": request.method,
                    "url": str(request.url),
                    "headers": mask_headers(request.headers),
                    "body": _truncate(request.content.decode("utf-8", "replace"), limit),
                },
                "response": {
                    "status": response.status_code,
                    "headers": mask_headers(response.headers),
                    "body": _truncate(response.text, limit),
                },
                "duration_ms": duration_ms,
            }
        )


def mask_headers(headers: httpx.Headers) -> dict[str, str]:
    return {
        name: MASK if name.lower() in SENSITIVE_HEADERS else value
        for name, value in headers.items()
    }


def _truncate(text: str, limit: int) -> str:
    return (
        text if len(text) <= limit else text[:limit] + f"... ({len(text) - limit} more characters)"
    )


class HttpxAdapter(TestAdapter):
    name = "httpx"
    capabilities = frozenset({"http"})

    def __init__(self) -> None:
        self.config = HttpConfig()
        self._execution: ExecutionContext | None = None
        self._session: HttpSession | None = None

    def prepare(self, context: ExecutionContext) -> None:
        try:
            self.config = HttpConfig.model_validate(dict(context.config_for(self.name)))
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors(include_url=False)
            )
            raise TestEnvironmentError(
                f"invalid adapters.httpx configuration: {problems}"
            ) from None
        self._execution = context

    def start_test_case(self, test_case: TestCase) -> None:
        self._close()
        execution = self._require()
        environment = execution.environment
        service = environment.services.get(self.config.service)
        base = service or environment.base_url
        base_url = str(base).rstrip("/") if base is not None else None
        client = httpx.Client(
            base_url=base_url or "",
            timeout=execution.settings.step_timeout_seconds,
            verify=self.config.verify_tls,
            follow_redirects=self.config.follow_redirects,
        )
        try:
            headers = {
                name: execution.resolve(value) for name, value in environment.headers.items()
            }
        except MissingSecretError as error:
            client.close()
            raise TestEnvironmentError(f"environment {environment.name!r}: {error}") from None
        self._session = HttpSession(
            client=client,
            config=self.config,
            redactor=execution.redactor,
            base_url=base_url,
            headers=headers,
            read_only=execution.read_only,
            environment=environment.name,
        )

    def collect_evidence(self, test_case: TestCase) -> list[EvidenceReference]:
        session, execution = self._session, self._execution
        try:
            if session is None or execution is None or not session.exchanges:
                return []
            folder = evidence_folder(test_case.id)
            directory = execution.evidence_dir / folder
            directory.mkdir(parents=True, exist_ok=True)
            data = execution.redactor.redact_data({"exchanges": session.exchanges})
            (directory / "http.json").write_text(json.dumps(data, indent=2) + "\n")
            count = len(session.exchanges)
            return [
                EvidenceReference(
                    kind="http-exchanges",
                    path=PurePosixPath(folder) / "http.json",
                    description=f"{count} request{'s' if count != 1 else ''} with responses",
                )
            ]
        finally:
            self._close()

    def cleanup(self) -> None:
        self._close()

    @property
    def resource(self) -> Any:
        if self._session is None:
            raise AdapterNotPreparedError("the HTTP client exists only while a test case runs")
        return self._session

    def _require(self) -> ExecutionContext:
        if self._execution is None:
            raise AdapterNotPreparedError("httpx is not prepared")
        return self._execution

    def _close(self) -> None:
        session, self._session = self._session, None
        if session is not None:
            session.client.close()
