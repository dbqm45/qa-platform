"""Host allowlist: where an execution may send requests (TASK-069).

Tests talk to the environment they target and nothing else: the hosts of its
``base_url`` and ``services``, plus the environment's ``allowed_hosts``
(``auth.example.com``, ``*.cdn.example.com``; ``*`` allows every host). This
keeps a scenario written for one environment from reaching another one by an
absolute URL, and keeps the environment's ``headers`` (often credentials)
from being sent to a foreign host.

Enforced for API requests (also after redirects), browser navigation (the
top-level page; images, scripts and other resources of a page may come from
anywhere) and setup/cleanup requests. Hosts are compared by name, not port.
"""

import re
from dataclasses import dataclass
from fnmatch import fnmatchcase
from urllib.parse import urlsplit

from qa_execution.errors import RootCause, TestEnvironmentError
from qa_schemas.base import REFERENCE_PATTERN
from qa_schemas.project import Environment
from qa_schemas.specification import Step, TestSpecification

URL_ACTIONS = frozenset({"browser.open", "browser.navigate", "api.send", "api.send-json"})
"""Built-in steps whose ``url`` parameter is where a request goes."""

_REFERENCE = re.compile(REFERENCE_PATTERN)


class HostNotAllowedError(TestEnvironmentError, RootCause):
    """A request to a host outside the environment."""


@dataclass(frozen=True)
class HostPolicy:
    environment: str
    hosts: frozenset[str]
    patterns: tuple[str, ...]
    """``allowed_hosts`` entries with wildcards; ``*`` allows everything."""

    @classmethod
    def of(cls, environment: Environment) -> "HostPolicy":
        own = {
            urlsplit(str(url)).hostname or ""
            for url in (environment.base_url, *environment.services.values())
            if url is not None
        }
        extra = {h.lower() for h in environment.allowed_hosts}
        plain = {h for h in extra if "*" not in h}
        return cls(
            environment=environment.name,
            hosts=frozenset((own | plain) - {""}),
            patterns=tuple(sorted(extra - plain)),
        )

    def allows(self, url: str) -> bool:
        """Relative URLs go to the environment itself and are always allowed."""
        if url.startswith("/"):
            return True
        host = (urlsplit(url).hostname or "").lower()
        return host in self.hosts or any(fnmatchcase(host, p) for p in self.patterns)

    def refuse(self, what: str, url: str) -> HostNotAllowedError:
        host = urlsplit(url).hostname or url
        return HostNotAllowedError(
            f"{what} {url.split('?', 1)[0]}: host {host!r} is not part of environment "
            f"{self.environment!r}; add it to allowed_hosts in qa.yaml if it should be"
        )


def foreign_url_steps(specification: TestSpecification, policy: HostPolicy) -> list[Step]:
    """Distinct steps with an absolute URL to a host the policy does not allow.

    URLs with ``${NAME}`` references are only known at run time; the adapters
    check those.
    """
    found: dict[tuple[int | None, str], Step] = {}
    for case in specification.test_cases:
        for step in case.steps:
            url = step.parameters.get("url")
            if step.action not in URL_ACTIONS or not isinstance(url, str):
                continue
            if _REFERENCE.search(url) or policy.allows(url):
                continue
            found.setdefault((step.line, step.text), step)
    return list(found.values())


def describe_foreign_steps(policy: HostPolicy, steps: list[Step]) -> str:
    listed = "; ".join(f"line {s.line}: {s.keyword} {s.text}" for s in steps[:3])
    more = f" (and {len(steps) - 3} more)" if len(steps) > 3 else ""
    return (
        f"these steps send requests outside environment {policy.environment!r}: "
        f"{listed}{more}; add the host to allowed_hosts in qa.yaml if it should be reachable"
    )
