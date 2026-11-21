"""Host allowlist: tests only reach their environment (TASK-069).

``127.0.0.1`` is the environment's host; ``localhost`` (the same machine under
another name) plays the foreign host, so we can see what reached it.
"""

import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError
from typer.testing import CliRunner

from qa_cli.main import app
from qa_execution.adapters import ExecutionContext
from qa_execution.http.adapter import HttpxAdapter
from qa_execution.policy import HostNotAllowedError, HostPolicy
from qa_schemas.plan import ExecutionSettings
from qa_schemas.project import Environment
from qa_schemas.specification import TestCase

runner = CliRunner()


class Counting(ThreadingHTTPServer):
    def __init__(self) -> None:
        self.requests: list[str] = []
        self.redirect_to = ""
        super().__init__(("127.0.0.1", 0), _Handler)

    @property
    def port(self) -> int:
        return self.server_address[1]


class _Handler(BaseHTTPRequestHandler):
    server: Counting

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def do_GET(self) -> None:
        self.server.requests.append(f"{self.path} key={self.headers.get('X-Api-Key')}")
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", self.server.redirect_to)
            self.end_headers()
            return
        page = b"<title>T</title><h1>Page</h1>"
        body = b'{"status": "ok"}' if self.path.endswith(".json") else page
        if self.path.endswith(".js"):
            body = b"document.title = 'script loaded';"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_POST = do_GET


@pytest.fixture
def servers() -> Iterator[tuple[Counting, Counting]]:
    own, foreign = Counting(), Counting()
    for server in (own, foreign):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    yield own, foreign
    for server in (own, foreign):
        server.shutdown()
        server.server_close()


@pytest.fixture
def project(
    tmp_path: Path, servers: tuple[Counting, Counting], monkeypatch: pytest.MonkeyPatch
) -> Path:
    own, foreign = servers
    assert runner.invoke(app, ["init", str(tmp_path), "--id", "shop"]).exit_code == 0
    _configure(tmp_path, {
        "name": "app",
        "base_url": f"http://127.0.0.1:{own.port}",
        "services": {"api": f"http://127.0.0.1:{own.port}"},
        "headers": {"X-Api-Key": "${SHOP_API_KEY}"},
        "variables": {"FOREIGN": f"http://localhost:{foreign.port}"},
    })  # fmt: skip
    monkeypatch.setenv("SHOP_API_KEY", "k3y-s3cret")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _configure(project: Path, environment: dict[str, Any], **extra: Any) -> None:
    config = project / "qa.yaml"
    data = yaml.safe_load(config.read_text())
    data["project"]["environments"] = [environment]
    data["project"]["default_environment"] = environment["name"]
    data.update(extra)
    config.write_text(yaml.safe_dump(data))


def _change(project: Path, **changes: Any) -> None:
    config = project / "qa.yaml"
    data = yaml.safe_load(config.read_text())
    data["project"]["environments"][0].update(changes)
    config.write_text(yaml.safe_dump(data))


def _qa(project: Path, scenario: str) -> tuple[int, str]:
    (project / "scenarios" / "s.feature").write_text(scenario)
    result = runner.invoke(app, ["test", "-s", "s.feature"])
    return result.exit_code, result.output


def _api(url: str) -> str:
    return (
        f'Feature: F\n  Scenario: S\n    When the client sends GET "{url}"\n'
        "    Then the response status is 200\n"
    )


# --- API -------------------------------------------------------------------


def test_own_host_is_allowed(project: Path, servers: tuple[Counting, Counting]) -> None:
    own, _ = servers
    code, output = _qa(project, _api(f"http://127.0.0.1:{own.port}/a.json"))
    assert code == 0, output
    assert own.requests == ["/a.json key=k3y-s3cret"]


def test_absolute_url_to_another_host_is_not_executed(
    project: Path, servers: tuple[Counting, Counting]
) -> None:
    _, foreign = servers
    url = f"http://localhost:{foreign.port}/a.json"

    code, output = _qa(project, _api(url))

    assert code == 1
    assert (
        f"NOT RUN  not executed: these steps send requests outside environment 'app': "
        f'line 3: When the client sends GET "{url}"; add the host to allowed_hosts'
    ) in output
    assert foreign.requests == []


def test_allowed_hosts_opens_the_way(project: Path, servers: tuple[Counting, Counting]) -> None:
    _, foreign = servers
    _change(project, allowed_hosts=["localhost"])
    code, output = _qa(project, _api(f"http://localhost:{foreign.port}/a.json"))
    assert code == 0, output
    assert len(foreign.requests) == 1


def test_any_step_is_refused_before_sending(
    tmp_path: Path, servers: tuple[Counting, Counting]
) -> None:
    """What a custom step sends through the http resource is checked as well."""
    own, foreign = servers
    environment = Environment.model_validate({
        "name": "app", "services": {"api": f"http://127.0.0.1:{own.port}"},
        "headers": {"X-Api-Key": "${SHOP_API_KEY}"},
    })  # fmt: skip
    context = ExecutionContext(
        execution_id="e", environment=environment, settings=ExecutionSettings(),
        evidence_dir=tmp_path, secret_source={"SHOP_API_KEY": "k3y-s3cret"},
    )  # fmt: skip
    adapter = HttpxAdapter()
    adapter.prepare(context)
    adapter.start_test_case(TestCase.model_construct(id="t.c", name="c", steps=()))
    session = adapter.resource

    session.send("GET", "/a.json")
    with pytest.raises(HostNotAllowedError, match="host 'localhost' is not part of"):
        session.send("GET", f"http://localhost:{foreign.port}/a.json")
    adapter.cleanup()

    assert own.requests == ["/a.json key=k3y-s3cret"]
    assert foreign.requests == []  # the API key never left


def test_redirect_to_another_host_is_not_followed(
    project: Path, servers: tuple[Counting, Counting]
) -> None:
    own, foreign = servers
    own.redirect_to = f"http://localhost:{foreign.port}/stolen.json"
    config = project / "qa.yaml"
    data = yaml.safe_load(config.read_text())
    data["adapters"] = {"httpx": {"follow_redirects": True}}
    config.write_text(yaml.safe_dump(data))

    code, output = _qa(project, _api("/redirect"))

    assert code == 1
    assert "host 'localhost' is not part of environment 'app'" in output
    assert foreign.requests == []


def test_setup_request_to_another_host(project: Path, servers: tuple[Counting, Counting]) -> None:
    _, foreign = servers
    _change(project, setup=[f"POST http://localhost:{foreign.port}/reset"])

    code, output = _qa(project, _api("/a.json"))

    assert code == 1
    assert "environment setup failed: setup POST http://localhost:" in output
    assert foreign.requests == []


def test_star_allows_every_host(project: Path, servers: tuple[Counting, Counting]) -> None:
    _, foreign = servers
    _change(project, allowed_hosts=["*"])
    code, _ = _qa(project, _api(f"http://localhost:{foreign.port}/a.json"))
    assert code == 0


# --- Browser -------------------------------------------------------------------


@pytest.fixture
def browser_project(project: Path, browser_config: dict[str, Any]) -> Path:
    config = project / "qa.yaml"
    data = yaml.safe_load(config.read_text())
    data["adapters"] = {"playwright": browser_config}
    data["project"]["environments"][0]["timeout_seconds"] = 3
    config.write_text(yaml.safe_dump(data))
    return project


def test_navigation_to_another_host_is_blocked(
    browser_project: Path, servers: tuple[Counting, Counting]
) -> None:
    own, foreign = servers
    away = f"http://localhost:{foreign.port}/page.html"
    own.RequestHandlerClass = _with_page(f"<title>T</title><a href='{away}'>Away</a>")
    scenario = (
        'Feature: F\n  Scenario: Leave\n    Given the user opens "/page.html"\n'
        '    When the user clicks "Away"\n'
        '    Then the page shows "Page"\n'
    )

    code, output = _qa(browser_project, scenario)

    assert code == 1
    assert "ERROR     Leave" in output
    assert "navigation to http://localhost:" in output
    assert foreign.requests == []


def test_page_resources_may_come_from_other_hosts(
    browser_project: Path, servers: tuple[Counting, Counting]
) -> None:
    own, foreign = servers
    page = (
        f"<title>T</title><h1>Page</h1><script src='http://localhost:{foreign.port}/x.js'></script>"
    )
    # the own server answers /page.html with its default page; serve this one instead
    own.RequestHandlerClass = _with_page(page)

    code, output = _qa(
        browser_project,
        'Feature: F\n  Scenario: CDN\n    Given the user opens "/page.html"\n'
        '    Then the page shows "Page"\n',
    )

    assert code == 0, output
    assert [r.split()[0] for r in foreign.requests] == ["/x.js"]


def _with_page(html: str) -> type[_Handler]:
    class PageHandler(_Handler):
        def do_GET(self) -> None:
            if self.path == "/page.html":
                body = html.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            super().do_GET()

    return PageHandler


# --- Policy rules -------------------------------------------------------------


def test_policy_rules() -> None:
    policy = HostPolicy.of(
        Environment.model_validate({
            "name": "e", "base_url": "https://shop.example.com",
            "services": {"api": "https://api.example.com"},
            "allowed_hosts": ["Auth.Example.org", "*.cdn.example.net"],
        })
    )  # fmt: skip
    assert policy.allows("/relative")
    assert policy.allows("https://shop.example.com:8443/x")  # ports are not compared
    assert policy.allows("https://API.example.com/x")
    assert policy.allows("https://auth.example.org/login")
    assert policy.allows("https://img.cdn.example.net/a.png")
    assert not policy.allows("https://cdn.example.net/a.png")  # *. means subdomains
    assert not policy.allows("https://shop.example.com.evil.net/")
    assert not policy.allows("https://evil.net/?next=https://shop.example.com")


@pytest.mark.parametrize("entry", ["https://x.com", "x.com/path", "*x.com", "a..b", "", "x.*"])
def test_invalid_allowed_hosts(entry: str) -> None:
    with pytest.raises(ValidationError, match="allowed_hosts"):
        Environment(name="e", allowed_hosts=(entry,))
