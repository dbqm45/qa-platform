"""Fixtures for integration tests: a local web server and a launchable browser."""

import os
import threading
from collections.abc import Iterator
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

FORM_PAGE = """<title>Login</title>
<h1 id="hello">Hello</h1>
<form action="/welcome.html" method="get">
  <label>Email <input name="email"></label>
  <label>Password <input name="password" type="password"></label>
  <label>Country <select name="country">
    <option value="">choose</option>
    <option value="pl">Poland</option>
    <option value="de">Germany</option>
  </select></label>
  <label><input type="checkbox" name="remember"> Remember me</label>
  <button type="submit" data-testid="login-button">Log in</button>
</form>
<button disabled>Delete</button>
<button>Save</button> <button>Save</button>
<span data-testid="Profile">avatar</span> <a href="/profile">Profile</a>
<p style="display:none">Secret</p>
<div id="toast">Saved!</div>
<div id="late-slot"></div>
<script>
  console.error("analytics failed to load");
  setTimeout(() => document.getElementById("toast").remove(), 300);
  const late = () => { document.getElementById("late-slot").innerHTML = "<p>Loaded later</p>"; };
  setTimeout(late, 300);
</script>"""

PAGES = {
    "index.html": "<title>Home</title><h1>Home</h1><a id='next' href='/second.html'>next</a>",
    "second.html": "<title>Second</title><h1>Second</h1>",
    "form.html": FORM_PAGE,
    "welcome.html": "<title>Welcome</title><h1>Welcome</h1>",
}
DEFAULT_EXECUTABLE = Path("/opt/pw-browsers/chromium")


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        pass


@pytest.fixture(scope="session")
def web_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("site")
    for name, html in PAGES.items():
        (root / name).write_text(f"<!doctype html><html><body>{html}</body></html>")
    return root


@pytest.fixture(scope="session")
def web_server(web_root: Path) -> Iterator[str]:
    """Base URL of a local HTTP server serving ``web_root``; missing files give 404."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(_QuietHandler, directory=str(web_root)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="session")
def browser_config() -> dict[str, Any]:
    """``adapters.playwright`` settings that work on this machine, or skip.

    Uses ``QA_TEST_BROWSER_EXECUTABLE`` or a pre-installed Chromium when present,
    otherwise the browser installed by ``playwright install``.
    """
    from playwright.sync_api import Error, sync_playwright

    executable = os.environ.get("QA_TEST_BROWSER_EXECUTABLE")
    if executable is None and DEFAULT_EXECUTABLE.exists():
        executable = str(DEFAULT_EXECUTABLE)
    config: dict[str, Any] = {"executable_path": executable} if executable else {}
    with sync_playwright() as playwright:
        try:
            playwright.chromium.launch(executable_path=executable).close()
        except Error as exc:
            pytest.skip(
                f"no launchable Chromium ({str(exc).splitlines()[0]}); "
                "run `uv run playwright install chromium`"
            )
    return config
