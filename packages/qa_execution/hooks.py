"""Environment setup and cleanup requests (TASK-056).

An environment can list HTTP requests to send before and after every
execution, e.g. to reset the application's test data::

    setup:   ["POST /reset"]
    cleanup: ["POST /reset"]

They are sent to the environment's API service (``adapters.httpx.service``,
default ``api``) or else its ``base_url``, with the environment's headers,
independently of the adapters a test uses.
"""

import time
from collections.abc import Sequence

import httpx
from pydantic import ValidationError

from qa_core.redaction import MissingSecretError
from qa_execution.adapters import ExecutionContext
from qa_execution.errors import TestEnvironmentError
from qa_execution.http.config import HttpConfig
from qa_execution.log import ExecutionLog
from qa_execution.protection import ALLOW_HINT, SAFE_METHODS, ProtectedEnvironmentError


class HookError(TestEnvironmentError):
    """A setup or cleanup request failed."""


def run_hooks(
    phase: str, hooks: Sequence[str], context: ExecutionContext, log: ExecutionLog
) -> None:
    """Send ``hooks`` in order; stop at the first failure.

    Raises:
        HookError: a request could not be sent or answered with status >= 400.
        ProtectedEnvironmentError: a write request in a read-only environment.
    """
    if not hooks:
        return
    environment = context.environment
    for hook in hooks:  # the guard applies before anything is sent
        method = hook.split(" ", 1)[0]
        if context.read_only and method not in SAFE_METHODS:
            raise ProtectedEnvironmentError(
                f"{phase} {hook} was not sent: environment {environment.name!r} is protected "
                f"(read-only); {ALLOW_HINT}"
            )
    try:
        config = HttpConfig.model_validate(dict(context.config_for("httpx")))
    except ValidationError as exc:
        raise HookError(f"{phase}: invalid adapters.httpx configuration: {exc}") from None
    base = environment.services.get(config.service) or environment.base_url
    try:
        headers = {name: context.resolve(value) for name, value in environment.headers.items()}
    except MissingSecretError as error:
        raise HookError(f"{phase}: {error}") from None

    with httpx.Client(
        base_url=str(base).rstrip("/") if base is not None else "",
        headers=headers,
        timeout=context.settings.step_timeout_seconds,
        verify=config.verify_tls,
        follow_redirects=config.follow_redirects,
    ) as client:
        for hook in hooks:
            method, target = hook.split(" ", 1)
            if target.startswith("/") and base is None:
                raise HookError(
                    f"{phase} {hook}: the environment has neither a {config.service!r} "
                    "service nor a base_url"
                )
            started = time.perf_counter()
            try:
                response = client.request(method, context.resolve(target))
            except MissingSecretError as error:
                raise HookError(f"{phase} {hook}: {error}") from None
            except httpx.HTTPError as exc:
                raise HookError(f"{phase} {hook} failed: {exc}") from None
            duration_ms = round((time.perf_counter() - started) * 1000)
            log.event(
                "hook-finished",
                phase=phase,
                request=hook,
                status=response.status_code,
                duration_ms=duration_ms,
            )
            if response.status_code >= 400:
                raise HookError(f"{phase} {hook} answered {response.status_code}")
