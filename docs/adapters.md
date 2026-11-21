# Adapters

An adapter owns one testing resource (a browser, an HTTP client, ...) and its
lifecycle. **It does not run steps**: the runner executes steps one by one,
and each step implementation obtains the resource for its capability from
the adapter that provides it. One test case can therefore use several
adapters (e.g. browser and HTTP in FULL mode).

```python
from typing import Any
from qa_execution.adapters import AdapterNotPreparedError, ExecutionContext, TestAdapter


class MyHttpAdapter(TestAdapter):
    name = "my-http"  # used in Execution Plans
    capabilities = frozenset({"http"})  # what steps can obtain from it

    def prepare(self, context: ExecutionContext) -> None:
        self._client = make_client(context.environment, context.settings)

    def cleanup(self) -> None:  # always called, also after failures
        client, self._client = getattr(self, "_client", None), None
        if client:
            client.close()

    @property
    def resource(self) -> Any:
        if getattr(self, "_client", None) is None:
            raise AdapterNotPreparedError("my-http is not prepared")
        return self._client
```

## Lifecycle

| Call | When | Required |
|------|------|----------|
| `validate(specification)` | before anything starts; returns a list of problems | optional (default: none) |
| `prepare(context)` | once per execution | **yes** |
| `start_test_case(test_case)` | before each test case | optional |
| `resource` | by step implementations, between `prepare` and `cleanup` | **yes** |
| `finish_test_case(test_case, passed)` | after each test case, whatever the outcome | optional |
| `collect_evidence(test_case)` | after each test case; must never change the outcome | optional |
| `cleanup()` | once, always; must be safe to call twice | **yes** |

Each call has a hard time limit (see [execution.md](execution.md#timeouts));
`cleanup` gets 30 s even after the execution deadline, so keep it quick and
idempotent.

`ExecutionContext` carries the execution id, the target `Environment`, the
plan's `ExecutionSettings` and the execution's evidence directory (adapters
write only below it). The API is synchronous.

## Registry and selection

```python
from qa_execution.registry import AdapterRegistry

registry = AdapterRegistry([PlaywrightAdapter, HttpxAdapter])
registry.available_capabilities  # frozenset({"browser", "http"})
registry.select({"browser", "http"})  # one adapter per capability
registry.select({"browser"}, allowed=["playwright"])  # restricted by the plan
```

Adapter classes are registered (not instances): every execution gets fresh
adapters. Registration rejects duplicate names and invalid or empty
capabilities. Selection fails with `AdapterSelectionError` when a capability
has no provider, or several providers that the plan's `adapters` does not
settle, or when the plan names an unknown adapter.

`qa scenario compile` uses the built-in adapters' capabilities: a
specification that needs a capability no adapter provides is `unsupported`.
